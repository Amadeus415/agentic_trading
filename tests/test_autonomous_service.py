import hashlib
import json
import sqlite3
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

import pytest

from edgecraft.autonomous_service import AutonomousService, StaticObservationRuntime
from edgecraft.autonomy import cycle_key
from edgecraft.autonomy_models import AgentCyclePayload, ExecutionResult, Mandate
from edgecraft.context import ContextSnapshot, ContextSource, WebContextPolicy
from edgecraft.execution_models import DecisionEvidenceItem, ExecutionPreflight, TradeProposal
from edgecraft.ledger import AuditLedger

NOW = datetime(2026, 7, 20, 15, 0, tzinfo=UTC)


def _mandate(policy_path: str) -> Mandate:
    return Mandate(
        mandate_id="service_test",
        goal="Invest a small weekly amount into a diversified index portfolio.",
        weekly_budget="10",
        universe=["VTI", "VXUS"],
        strategic_weights={"VTI": "0.60", "VXUS": "0.40"},
        max_tactical_tilt="0.15",
        schedule_weekday=0,
        schedule_time=time(10),
        timezone="America/New_York",
        benchmark="VTI",
        policy_path=policy_path,
    )


def _payload(run_id: str = "placeholder", *, action: str = "invest") -> AgentCyclePayload:
    allocations = (
        [
            {
                "symbol": "VTI",
                "notional": "6",
                "conviction": "0.7",
                "rationale": "Maintain the diversified US core.",
                "evidence_ids": ["quote-vti", "history-vti", "account-state"],
            },
            {
                "symbol": "VXUS",
                "notional": "4",
                "conviction": "0.7",
                "rationale": "Maintain international diversification.",
                "evidence_ids": ["quote-vxus", "history-vxus", "account-state"],
            },
        ]
        if action == "invest"
        else []
    )
    return AgentCyclePayload.model_validate(
        {
            "observed_at": NOW,
            "account": {
                "account_id": "agentic-test",
                "agentic_allowed": True,
                "buying_power": 100,
                "portfolio_value": 100,
                "as_of": NOW,
                "positions": [],
                "open_orders": [],
            },
            "quotes": [
                {
                    "symbol": "VTI",
                    "last": 330,
                    "bid": 329.95,
                    "ask": 330.05,
                    "as_of": NOW,
                    "market_session": "regular",
                    "average_daily_dollar_volume": "1000000000",
                },
                {
                    "symbol": "VXUS",
                    "last": 75,
                    "bid": 74.99,
                    "ask": 75.01,
                    "as_of": NOW,
                    "market_session": "regular",
                    "average_daily_dollar_volume": "100000000",
                },
            ],
            "recent_order_summary": [],
            "realized_pnl_summary": "No realized P&L.",
            "decision": {
                "mandate_id": "service_test",
                "run_id": run_id,
                "as_of": NOW,
                "action": action,
                "confidence": "0.7",
                "hypothesis": "Follow the diversified strategic DCA allocation this week.",
                "evidence": ["Quotes and account state are fresh."],
                "alternatives_considered": ["hold cash"],
                "risks": ["market prices can fall"],
                "allocations": allocations,
                "data_sources": ["captured Robinhood MCP fixture"],
                "evidence_items": [
                    {
                        "evidence_id": "account-state",
                        "category": "broker",
                        "source": "captured Robinhood MCP fixture",
                        "observed_at": NOW,
                        "summary": "Agentic account is eligible with available buying power.",
                        "metrics": [{"name": "buying_power", "value": "100", "unit": "USD"}],
                    },
                    {
                        "evidence_id": "quote-vti",
                        "category": "quote",
                        "source": "captured Robinhood MCP fixture",
                        "symbol": "VTI",
                        "observed_at": NOW,
                        "summary": "Fresh VTI quote used for the proposed allocation.",
                        "metrics": [{"name": "last", "value": "330", "unit": "USD"}],
                    },
                    {
                        "evidence_id": "quote-vxus",
                        "category": "quote",
                        "source": "captured Robinhood MCP fixture",
                        "symbol": "VXUS",
                        "observed_at": NOW,
                        "summary": "Fresh VXUS quote used for the proposed allocation.",
                        "metrics": [{"name": "last", "value": "75", "unit": "USD"}],
                    },
                    {
                        "evidence_id": "history-vti",
                        "category": "historical",
                        "source": "captured completed-session history",
                        "symbol": "VTI",
                        "observed_at": NOW,
                        "source_timestamp": NOW,
                        "summary": "Completed-session VTI history supports the comparison.",
                        "metrics": [{"name": "return_20d", "value": "0.01"}],
                    },
                    {
                        "evidence_id": "history-vxus",
                        "category": "historical",
                        "source": "captured completed-session history",
                        "symbol": "VXUS",
                        "observed_at": NOW,
                        "source_timestamp": NOW,
                        "summary": "Completed-session VXUS history supports the comparison.",
                        "metrics": [{"name": "return_20d", "value": "0.02"}],
                    },
                ],
            },
        }
    )


def _write_policy(tmp_path):
    policy = tmp_path / "policy.json"
    policy.write_text(
        json.dumps(
            {
                "policy_name": "service-shadow",
                "allowed_symbols": ["VTI", "VXUS"],
                "managed_capital_limit": 1000,
                "max_order_notional": 10,
                "max_daily_notional": 10,
                "max_orders_per_day": 2,
                "max_position_weight": 0.75,
                "min_cash_reserve": 0,
                "require_research_evidence": False,
            }
        )
    )
    return policy


class FixedContextCollector:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def collect(self, symbols, *, now=None):
        del symbols, now
        return self.snapshot


def _context_snapshot(*, complete=True):
    sources = [
        ContextSource(
            source_id=f"web-{index}",
            channel="web" if index == 1 else "social",
            title=f"Context {index}",
            url=f"https://source{index}.example/item",
            retrieved_at=NOW,
            published_at=NOW,
        )
        for index in (1, 2)
    ]
    return ContextSnapshot(
        collected_at=NOW,
        provider="test",
        symbols=["VTI", "VXUS"],
        queries=["test query"],
        sources=sources,
        fresh_source_count=2,
        complete=complete,
    )


def test_shadow_cycle_is_idempotent_and_audited(tmp_path):
    policy = _write_policy(tmp_path)
    mandate = _mandate(str(policy))
    ledger = AuditLedger(tmp_path / "state.db")
    service = AutonomousService(tmp_path, ledger, StaticObservationRuntime(_payload()))

    first = service.run_cycle(mandate, now=NOW)
    assert first["ok"]
    assert first["run"]["status"] == "shadow_complete"
    assert first["run"]["payload"]["gross_notional"] == 10
    assert ledger.status()["proposals"] == 1
    assert ledger.status()["decision_packets"] == 1
    packets = ledger.decision_packets_for_run(first["run"]["run_id"])
    assert len(packets) == 1
    packet = packets[0]
    assert packet["attempt"] == 1
    assert packet["payload"]["runtime"]["prompt_version"]
    assert packet["payload"]["mandate"]["mandate_id"] == "service_test"
    assert packet["payload"]["risk_policy"]["policy_name"] == "service-shadow"
    assert packet["payload"]["observation"]["account"]["account_id"].startswith("acct_")
    assert packet["payload"]["observation"]["account"]["account_id"] != "agentic-test"
    assert packet["payload"]["observation"]["quotes"][0]["symbol"] == "VTI"
    assert (
        packet["payload"]["observation"]["decision"]["evidence_items"][0]["evidence_id"]
        == "account-state"
    )
    canonical = json.dumps(packet["payload"], sort_keys=True, separators=(",", ":"))
    assert hashlib.sha256(canonical.encode()).hexdigest() == packet["payload_sha256"]
    proposal = ledger.observability_feed()["proposals"][0]["payload"]
    assert proposal["decision_reasoning"]["hypothesis"] == (
        "Follow the diversified strategic DCA allocation this week."
    )
    assert proposal["decision_reasoning"]["alternatives_considered"] == ["hold cash"]
    assert proposal["decision_reasoning"]["allocation_rationales"]["VTI"] == (
        "Maintain the diversified US core."
    )

    replay = service.run_cycle(mandate, now=NOW)
    assert replay["idempotent_replay"]
    assert replay["run"]["run_id"] == first["run"]["run_id"]
    assert ledger.status()["proposals"] == 1


def test_real_cycle_evaluates_freshness_after_observation(monkeypatch, tmp_path):
    policy = _write_policy(tmp_path)
    mandate = _mandate(str(policy))
    observed_at = NOW + timedelta(minutes=2)
    payload = _payload().model_copy(
        update={
            "observed_at": observed_at,
            "account": _payload().account.model_copy(update={"as_of": observed_at}),
            "quotes": [
                quote.model_copy(update={"as_of": observed_at}) for quote in _payload().quotes
            ],
            "decision": _payload().decision.model_copy(update={"as_of": observed_at}),
        }
    )
    ledger = AuditLedger(tmp_path / "state.db")
    service = AutonomousService(tmp_path, ledger, StaticObservationRuntime(payload))
    wall_times = iter([NOW, observed_at])
    monkeypatch.setattr(
        "edgecraft.autonomous_service.datetime",
        type(
            "ControlledDateTime",
            (),
            {"now": staticmethod(lambda timezone: next(wall_times))},
        ),
    )

    result = service.run_cycle(mandate)

    assert result["run"]["status"] == "shadow_complete"
    assert not any("timestamp is in the future" for item in result["run"]["payload"]["violations"])


def test_external_context_is_audited_and_investment_requires_known_citations(tmp_path):
    policy_path = _write_policy(tmp_path)
    mandate = _mandate(str(policy_path)).model_copy(
        update={"external_context_path": "context.json"}
    )
    snapshot = _context_snapshot()
    context_policy = WebContextPolicy(min_sources=2, min_fresh_sources=2)
    base_decision = _payload().decision
    context_evidence = DecisionEvidenceItem(
        evidence_id="current-web-context",
        category="web",
        source="audited context fixture",
        observed_at=NOW,
        source_timestamp=NOW,
        summary="Current primary reporting supports the allocation comparison.",
        context_source_ids=["web-1"],
    )
    cited_payload = _payload().model_copy(
        update={
            "decision": base_decision.model_copy(
                update={
                    "context_source_ids": ["web-1", "web-2"],
                    "evidence_items": [*base_decision.evidence_items, context_evidence],
                    "allocations": [
                        allocation.model_copy(
                            update={
                                "evidence_ids": [
                                    *allocation.evidence_ids,
                                    "current-web-context",
                                ]
                            }
                        )
                        for allocation in base_decision.allocations
                    ],
                }
            )
        }
    )
    ledger = AuditLedger(tmp_path / "state.db")
    service = AutonomousService(
        tmp_path,
        ledger,
        StaticObservationRuntime(cited_payload),
        context_collector=FixedContextCollector(snapshot),
        context_policy=context_policy,
    )

    result = service.run_cycle(mandate, now=NOW)

    assert result["run"]["status"] == "shadow_complete"
    assert any(
        event["event_type"] == "external_context_collected"
        for event in ledger.observability_feed()["runtime_events"]
    )
    packet = ledger.decision_packets_for_run(result["run"]["run_id"])[0]["payload"]
    assert packet["external_context"]["queries"] == ["test query"]
    assert {item["source_id"] for item in packet["external_context"]["sources"]} == {
        "web-1",
        "web-2",
    }

    uncited_ledger = AuditLedger(tmp_path / "uncited.db")
    uncited = AutonomousService(
        tmp_path,
        uncited_ledger,
        StaticObservationRuntime(_payload()),
        context_collector=FixedContextCollector(snapshot),
        context_policy=context_policy,
    )
    with pytest.raises(ValueError, match="at least 2 external context citations"):
        uncited.run_cycle(mandate, now=NOW)

    unknown_evidence = context_evidence.model_copy(
        update={"context_source_ids": ["not-in-the-snapshot"]}
    )
    unknown_payload = cited_payload.model_copy(
        update={
            "decision": cited_payload.decision.model_copy(
                update={"evidence_items": [*base_decision.evidence_items, unknown_evidence]}
            )
        }
    )
    unknown_ledger = AuditLedger(tmp_path / "unknown-evidence.db")
    unknown_service = AutonomousService(
        tmp_path,
        unknown_ledger,
        StaticObservationRuntime(unknown_payload),
        context_collector=FixedContextCollector(snapshot),
        context_policy=context_policy,
    )
    with pytest.raises(ValueError, match="evidence cited unknown external context"):
        unknown_service.run_cycle(mandate, now=NOW)


def test_incomplete_context_blocks_live_cycle_before_authority(tmp_path):
    policy_path = _write_policy(tmp_path)
    mandate = _mandate(str(policy_path)).model_copy(
        update={"mode": "live", "external_context_path": "context.json"}
    )
    ledger = AuditLedger(tmp_path / "state.db")
    service = AutonomousService(
        tmp_path,
        ledger,
        StaticObservationRuntime(_payload()),
        context_collector=FixedContextCollector(_context_snapshot(complete=False)),
        context_policy=WebContextPolicy(min_sources=2, min_fresh_sources=2),
    )

    with pytest.raises(RuntimeError, match="required external context is incomplete"):
        service.run_cycle(mandate, now=NOW)
    assert not ledger.run_has_permit(ledger.list_runs()[0]["run_id"])


def test_hold_is_a_successful_terminal_decision(tmp_path):
    policy = _write_policy(tmp_path)
    mandate = _mandate(str(policy))
    ledger = AuditLedger(tmp_path / "state.db")
    service = AutonomousService(tmp_path, ledger, StaticObservationRuntime(_payload(action="hold")))

    result = service.run_cycle(mandate, now=NOW)
    assert result["ok"]
    assert result["run"]["status"] == "held"
    assert result["run"]["payload"]["approved_for_review"] is False


def test_investment_without_structured_evidence_is_rejected_before_proposal(tmp_path):
    policy = _write_policy(tmp_path)
    mandate = _mandate(str(policy))
    original = _payload()
    payload = original.model_copy(
        update={
            "decision": original.decision.model_copy(
                update={
                    "evidence_items": [],
                    "allocations": [
                        allocation.model_copy(update={"evidence_ids": []})
                        for allocation in original.decision.allocations
                    ],
                }
            )
        }
    )
    ledger = AuditLedger(tmp_path / "state.db")
    service = AutonomousService(tmp_path, ledger, StaticObservationRuntime(payload))

    with pytest.raises(ValueError, match="structured evidence inventory"):
        service.run_cycle(mandate, now=NOW)

    assert ledger.status()["decision_packets"] == 0
    assert ledger.status()["proposals"] == 0


def test_before_schedule_returns_not_due_without_starting_run(tmp_path):
    policy = _write_policy(tmp_path)
    mandate = _mandate(str(policy))
    ledger = AuditLedger(tmp_path / "state.db")
    before = datetime(2026, 7, 20, 13, 0, tzinfo=UTC)
    service = AutonomousService(tmp_path, ledger, StaticObservationRuntime(_payload()))

    result = service.run_cycle(mandate, now=before)
    assert result["status"] == "not_due"
    assert ledger.status()["runs"] == 0


class FailsOnceRuntime(StaticObservationRuntime):
    def __init__(self, payload):
        super().__init__(payload)
        self.calls = 0

    def observe(
        self,
        mandate,
        *,
        run_id,
        remaining_budget,
        ledger_path,
        risk_policy,
        external_context=None,
        market_intelligence=None,
    ):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("transient MCP failure")
        return super().observe(
            mandate,
            run_id=run_id,
            remaining_budget=remaining_budget,
            ledger_path=ledger_path,
            risk_policy=risk_policy,
            external_context=external_context,
            market_intelligence=market_intelligence,
        )


def test_side_effect_free_failure_retries_same_cycle_safely(tmp_path):
    policy = _write_policy(tmp_path)
    mandate = _mandate(str(policy))
    ledger = AuditLedger(tmp_path / "state.db")
    runtime = FailsOnceRuntime(_payload())
    service = AutonomousService(tmp_path, ledger, runtime)

    with pytest.raises(RuntimeError, match="transient MCP failure"):
        service.run_cycle(mandate, now=NOW)
    retry = service.run_cycle(mandate, now=NOW)
    assert retry["ok"]
    assert retry["run"]["status"] == "shadow_complete"
    assert ledger.run_attempt_count(retry["run"]["run_id"]) == 2


def test_concurrent_cycle_returns_in_progress_without_invoking_runtime(tmp_path):
    policy = _write_policy(tmp_path)
    mandate = _mandate(str(policy))
    ledger = AuditLedger(tmp_path / "state.db")
    runtime = FailsOnceRuntime(_payload())
    service = AutonomousService(tmp_path, ledger, runtime)
    key = cycle_key(mandate, NOW)

    with ledger.cycle_lock(mandate.mandate_id, key) as acquired:
        assert acquired
        result = service.run_cycle(mandate, now=NOW)

    assert result["ok"]
    assert result["status"] == "in_progress"
    assert result["run"] is None
    assert runtime.calls == 0


def test_permit_makes_failed_run_non_retryable(tmp_path):
    policy = _write_policy(tmp_path)
    mandate = _mandate(str(policy)).model_copy(update={"mode": "live"})
    ledger = AuditLedger(tmp_path / "state.db")
    run_id = ledger.start_run(mandate, "service_test:2026-W30", now=NOW)
    proposal = TradeProposal.model_validate(
        {
            "proposal_id": "prop-permit-test",
            "mandate_id": mandate.mandate_id,
            "run_id": run_id,
            "created_at": NOW,
            "mode": "live",
            "account_id": "agentic-test",
            "strategy": "agentic_weekly_dca",
            "rationale": "Test non-retry after authority issuance.",
            "policy_name": "test",
            "snapshot_as_of": NOW,
            "orders": [
                {
                    "order_key": "order-test",
                    "symbol": "VTI",
                    "side": "buy",
                    "notional": 10,
                    "expected_price": 330,
                    "rationale": "Test order.",
                    "quote_as_of": NOW,
                }
            ],
            "risk": {
                "approved_for_review": True,
                "projected_cash": 90,
                "projected_weights": {"VTI": 0.1},
                "gross_notional": 10,
            },
            "robinhood_handoff": {},
        }
    )
    ledger.add_proposal(proposal)
    ledger.issue_permit(run_id, proposal.proposal_id, "order-test", now=NOW)
    ledger.update_run(run_id, "failed", detail="execution uncertainty", now=NOW)
    assert not ledger.run_is_safe_to_retry(run_id)


class FilledLiveRuntime(StaticObservationRuntime):
    def preflight_order(self, mandate, proposal, order, *, ledger_path):
        del mandate, ledger_path
        quote = next(item for item in self.payload.quotes if item.symbol == order.symbol)
        return ExecutionPreflight(
            run_id=proposal.run_id,
            proposal_id=proposal.proposal_id,
            order_key=order.order_key,
            observed_at=NOW,
            account=self.payload.account,
            quote=quote,
            review_approved=True,
            reviewed_notional=Decimal(str(order.notional)),
        )

    def execute_order(
        self,
        mandate,
        proposal,
        order,
        *,
        permit_token,
        ledger_path,
    ):
        del mandate
        token_hash = hashlib.sha256(permit_token.encode()).hexdigest()
        connection = sqlite3.connect(ledger_path)
        connection.execute(
            """
            UPDATE permits SET status = 'claimed', claimed_at = ?
            WHERE token_hash = ? AND status = 'issued'
            """,
            (NOW.isoformat(), token_hash),
        )
        connection.commit()
        connection.close()
        return ExecutionResult(
            run_id=proposal.run_id,
            proposal_id=proposal.proposal_id,
            order_key=order.order_key,
            status="filled",
            broker_order_id="broker-test-order",
            symbol=order.symbol,
            side=order.side,
            requested_notional=Decimal(str(order.notional)),
            filled_notional=Decimal(str(order.notional)),
            average_fill_price=Decimal(str(order.expected_price)),
            observed_at=NOW,
        )

    def reconcile_order(
        self,
        mandate,
        proposal,
        order,
        placed_result,
        *,
        ledger_path,
    ):
        del mandate, proposal, order, ledger_path
        return placed_result


class PlacedThenFilledRuntime(FilledLiveRuntime):
    def __init__(self, payload):
        super().__init__(payload)
        self.reconciliations = 0

    def execute_order(self, mandate, proposal, order, *, permit_token, ledger_path):
        filled = super().execute_order(
            mandate,
            proposal,
            order,
            permit_token=permit_token,
            ledger_path=ledger_path,
        )
        return filled.model_copy(update={"status": "placed", "filled_notional": Decimal("0")})

    def reconcile_order(
        self,
        mandate,
        proposal,
        order,
        placed_result,
        *,
        ledger_path,
    ):
        del mandate, ledger_path
        self.reconciliations += 1
        return placed_result.model_copy(
            update={
                "status": "filled",
                "filled_notional": Decimal(str(order.notional)),
                "average_fill_price": Decimal("330"),
                "proposal_id": proposal.proposal_id,
            }
        )


class MalformedAfterFillRuntime(FilledLiveRuntime):
    def execute_order(self, mandate, proposal, order, *, permit_token, ledger_path):
        super().execute_order(
            mandate,
            proposal,
            order,
            permit_token=permit_token,
            ledger_path=ledger_path,
        )
        raise RuntimeError("structured execution result was malformed")

    def recover_order(
        self,
        mandate,
        proposal,
        order,
        *,
        authority_issued_at,
        failure_observed_at,
        ledger_path,
    ):
        del mandate, authority_issued_at, failure_observed_at, ledger_path
        return ExecutionResult(
            run_id=proposal.run_id,
            proposal_id=proposal.proposal_id,
            order_key=order.order_key,
            status="filled",
            broker_order_id="broker-recovered-order",
            symbol=order.symbol,
            side=order.side,
            requested_notional=Decimal(str(order.notional)),
            filled_notional=Decimal("1.999999"),
            average_fill_price=Decimal("330.123456"),
            observed_at=NOW,
        )


class UnknownAfterPlacementRuntime(MalformedAfterFillRuntime):
    def recover_order(
        self,
        mandate,
        proposal,
        order,
        *,
        authority_issued_at,
        failure_observed_at,
        ledger_path,
    ):
        result = super().recover_order(
            mandate,
            proposal,
            order,
            authority_issued_at=authority_issued_at,
            failure_observed_at=failure_observed_at,
            ledger_path=ledger_path,
        )
        return result.model_copy(
            update={
                "status": "unknown",
                "broker_order_id": None,
                "filled_notional": Decimal("0"),
                "average_fill_price": None,
            }
        )


class RejectedRecoveryRuntime(FilledLiveRuntime):
    def execute_order(self, mandate, proposal, order, *, permit_token, ledger_path):
        del mandate, proposal, order, permit_token, ledger_path
        raise RuntimeError("broker rejected before a structured response was returned")

    def recover_order(
        self,
        mandate,
        proposal,
        order,
        *,
        authority_issued_at,
        failure_observed_at,
        ledger_path,
    ):
        del mandate, authority_issued_at, failure_observed_at, ledger_path
        return ExecutionResult(
            run_id=proposal.run_id,
            proposal_id=proposal.proposal_id,
            order_key=order.order_key,
            status="rejected",
            broker_order_id="broker-rejected-order",
            symbol=order.symbol,
            side=order.side,
            requested_notional=Decimal(str(order.notional)),
            observed_at=NOW,
            detail="broker independently confirmed rejection",
        )


class ClosedMarketPreflightRuntime(FilledLiveRuntime):
    def preflight_order(self, mandate, proposal, order, *, ledger_path):
        result = super().preflight_order(
            mandate,
            proposal,
            order,
            ledger_path=ledger_path,
        )
        return result.model_copy(
            update={"quote": result.quote.model_copy(update={"market_session": "closed"})}
        )


class PolicyMutatingPreflightRuntime(FilledLiveRuntime):
    def __init__(self, payload, policy_path):
        super().__init__(payload)
        self.policy_path = policy_path

    def preflight_order(self, mandate, proposal, order, *, ledger_path):
        result = super().preflight_order(
            mandate,
            proposal,
            order,
            ledger_path=ledger_path,
        )
        policy = json.loads(self.policy_path.read_text())
        policy["max_daily_notional"] = 11
        self.policy_path.write_text(json.dumps(policy))
        return result


def test_live_cycle_records_guarded_fill_and_spend(tmp_path):
    policy_path = tmp_path / "live-policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "policy_name": "service-live",
                "trading_enabled": True,
                "allowed_symbols": ["VTI", "VXUS"],
                "managed_capital_limit": 1000,
                "max_order_notional": 10,
                "max_daily_notional": 10,
                "max_orders_per_day": 2,
                "max_position_weight": 0.75,
                "min_cash_reserve": 0,
                "require_research_evidence": False,
            }
        )
    )
    mandate = _mandate(str(policy_path)).model_copy(update={"mode": "live"})
    ledger = AuditLedger(tmp_path / "state.db")
    service = AutonomousService(tmp_path, ledger, FilledLiveRuntime(_payload()))

    result = service.run_cycle(mandate, now=NOW)
    assert result["ok"]
    assert result["run"]["status"] == "completed"
    assert ledger.daily_placed_notional(NOW.date()) == 10
    assert not ledger.unresolved_order_keys()
    assert ledger.operational_snapshot()["permits_by_status"]["claimed"] == 2
    quality = ledger.execution_quality(mandate.mandate_id)
    assert quality["fill_count"] == 2
    assert quality["notional_weighted_slippage_bps"] == pytest.approx(0)
    assert quality["fees"] == 0


def test_live_preflight_rejection_occurs_before_permit_issuance(tmp_path):
    policy_path = tmp_path / "live-policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "policy_name": "service-live-preflight",
                "trading_enabled": True,
                "allowed_symbols": ["VTI", "VXUS"],
                "managed_capital_limit": 1000,
                "max_order_notional": 10,
                "max_daily_notional": 10,
                "max_orders_per_day": 2,
                "max_position_weight": 0.75,
                "min_cash_reserve": 0,
                "require_research_evidence": False,
            }
        )
    )
    mandate = _mandate(str(policy_path)).model_copy(update={"mode": "live"})
    ledger = AuditLedger(tmp_path / "state.db")

    result = AutonomousService(
        tmp_path,
        ledger,
        ClosedMarketPreflightRuntime(_payload()),
    ).run_cycle(mandate, now=NOW)

    assert result["run"]["status"] == "failed"
    assert not ledger.run_has_permit(result["run"]["run_id"])
    events = ledger.observability_feed()["runtime_events"]
    preflight = next(
        item for item in events if item["event_type"] == "execution_preflight_completed"
    )
    assert any("market session closed" in item for item in preflight["payload"]["violations"])


def test_live_policy_drift_during_preflight_aborts_before_permit(tmp_path):
    policy_path = tmp_path / "live-policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "policy_name": "service-live-policy-drift",
                "trading_enabled": True,
                "allowed_symbols": ["VTI", "VXUS"],
                "managed_capital_limit": 1000,
                "max_order_notional": 10,
                "max_daily_notional": 10,
                "max_orders_per_day": 2,
                "max_position_weight": 0.75,
                "min_cash_reserve": 0,
                "require_research_evidence": False,
            }
        )
    )
    mandate = _mandate(str(policy_path)).model_copy(update={"mode": "live"})
    ledger = AuditLedger(tmp_path / "state.db")
    runtime = PolicyMutatingPreflightRuntime(_payload(), policy_path)

    with pytest.raises(RuntimeError, match="policy changed during execution preflight"):
        AutonomousService(tmp_path, ledger, runtime).run_cycle(mandate, now=NOW)

    run = ledger.list_runs()[0]
    assert run["status"] == "failed"
    assert not ledger.run_has_permit(run["run_id"])


def test_placed_orders_receive_independent_terminal_reconciliation(tmp_path):
    policy_path = tmp_path / "live-policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "policy_name": "service-live-reconcile",
                "trading_enabled": True,
                "allowed_symbols": ["VTI", "VXUS"],
                "managed_capital_limit": 1000,
                "max_order_notional": 10,
                "max_daily_notional": 10,
                "max_orders_per_day": 2,
                "max_position_weight": 0.75,
                "min_cash_reserve": 0,
                "require_research_evidence": False,
            }
        )
    )
    mandate = _mandate(str(policy_path)).model_copy(update={"mode": "live"})
    ledger = AuditLedger(tmp_path / "state.db")
    runtime = PlacedThenFilledRuntime(_payload())
    result = AutonomousService(tmp_path, ledger, runtime).run_cycle(mandate, now=NOW)
    assert result["run"]["status"] == "completed"
    assert runtime.reconciliations == 2
    assert not ledger.unresolved_order_keys()


def test_execution_schema_failure_recovers_broker_fill_and_reasoning(tmp_path):
    policy_path = tmp_path / "live-policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "policy_name": "service-live-recovery",
                "trading_enabled": True,
                "allowed_symbols": ["VTI", "VXUS"],
                "managed_capital_limit": 1000,
                "max_order_notional": 10,
                "max_daily_notional": 10,
                "max_orders_per_day": 2,
                "max_position_weight": 0.75,
                "min_cash_reserve": 0,
                "require_research_evidence": False,
            }
        )
    )
    mandate = _mandate(str(policy_path)).model_copy(update={"mode": "live"})
    ledger = AuditLedger(tmp_path / "state.db")
    runtime = MalformedAfterFillRuntime(_payload())

    result = AutonomousService(tmp_path, ledger, runtime).run_cycle(mandate, now=NOW)

    assert result["run"]["status"] == "completed"
    assert not ledger.trading_halted()
    feed = ledger.observability_feed()
    events = {item["event_type"]: item for item in feed["order_events"]}
    assert set(events) == {"placed", "filled"}
    assert events["filled"]["payload"]["filled_notional"] == 2.0
    assert events["filled"]["payload"]["average_fill_price"] == 330.123456
    reasoning = events["filled"]["payload"]["reasoning"]
    assert reasoning["decision_reasoning"]["risks"] == ["market prices can fall"]
    assert reasoning["order_rationale"] == "Maintain the diversified US core."
    assert ledger.operational_snapshot()["permits_by_status"] == {"claimed": 2}
    runtime_types = {event["event_type"] for event in feed["runtime_events"]}
    assert "execution_recovery_terminal" in runtime_types


def test_terminal_rejection_recovery_revokes_unused_permits_without_halting(tmp_path):
    policy_path = tmp_path / "live-policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "policy_name": "service-live-rejection-recovery",
                "trading_enabled": True,
                "allowed_symbols": ["VTI", "VXUS"],
                "managed_capital_limit": 1000,
                "max_order_notional": 10,
                "max_daily_notional": 10,
                "max_orders_per_day": 2,
                "max_position_weight": 0.75,
                "min_cash_reserve": 0,
                "require_research_evidence": False,
            }
        )
    )
    mandate = _mandate(str(policy_path)).model_copy(update={"mode": "live"})
    ledger = AuditLedger(tmp_path / "state.db")

    result = AutonomousService(
        tmp_path,
        ledger,
        RejectedRecoveryRuntime(_payload()),
    ).run_cycle(mandate, now=NOW)

    assert result["run"]["status"] == "failed"
    assert not ledger.trading_halted()
    assert ledger.operational_snapshot()["permits_by_status"] == {"revoked": 2}


def test_uncertain_recovery_halts_and_requires_incident_reconciliation(tmp_path):
    policy_path = tmp_path / "live-policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "policy_name": "service-live-uncertain-recovery",
                "trading_enabled": True,
                "allowed_symbols": ["VTI", "VXUS"],
                "managed_capital_limit": 1000,
                "max_order_notional": 10,
                "max_daily_notional": 10,
                "max_orders_per_day": 2,
                "max_position_weight": 0.75,
                "min_cash_reserve": 0,
                "require_research_evidence": False,
            }
        )
    )
    mandate = _mandate(str(policy_path)).model_copy(update={"mode": "live"})
    ledger = AuditLedger(tmp_path / "state.db")

    with pytest.raises(RuntimeError, match="broker recovery status=unknown"):
        AutonomousService(
            tmp_path,
            ledger,
            UnknownAfterPlacementRuntime(_payload()),
        ).run_cycle(mandate, now=NOW)

    run = ledger.list_runs()[0]
    assert run["status"] == "failed"
    assert ledger.trading_halted()
    proposal = ledger.observability_feed()["proposals"][0]["payload"]
    for index, order in enumerate(proposal["orders"]):
        broker_order_id = f"independently-verified-order-{index}"
        ledger.record_event(
            proposal["proposal_id"],
            "placed",
            {
                "order_key": order["order_key"],
                "notional": order["notional"],
                "broker_order_id": broker_order_id,
            },
            occurred_at=NOW,
        )
        ledger.record_event(
            proposal["proposal_id"],
            "filled",
            {
                "order_key": order["order_key"],
                "notional": order["notional"],
                "filled_notional": order["notional"],
                "broker_order_id": broker_order_id,
            },
            occurred_at=NOW,
        )

    reconciled = ledger.reconcile_failed_run(
        run["run_id"],
        reason="broker order, position, and cash independently verified",
        now=NOW,
    )
    assert reconciled["status"] == "completed"
    assert reconciled["payload"]["incident_reconciled"] is True
    assert ledger.trading_halted()
