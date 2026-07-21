from __future__ import annotations

import json
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from edgecraft.audit_models import DecisionAuditPacket, DecisionRuntimeMetadata
from edgecraft.autonomy import (
    available_cycle_budget,
    create_weekly_proposal,
    cycle_due,
    cycle_key,
    policy_digest,
)
from edgecraft.autonomy_models import (
    AgentCyclePayload,
    ExecutionResult,
    Mandate,
)
from edgecraft.codex_runtime import PROMPT_VERSION, CodexRuntime, CodexRuntimeConfig
from edgecraft.context import ContextCollector, ContextSnapshot, WebContextPolicy
from edgecraft.evaluation import advance_evaluation
from edgecraft.execution_models import (
    ExecutionPreflight,
    ProposedOrder,
    ResearchEvidence,
    RiskPolicy,
    TradeProposal,
)
from edgecraft.intelligence import MarketIntelligenceCollector, MarketIntelligenceSnapshot
from edgecraft.ledger import AuditLedger, DuplicateProposalError
from edgecraft.observability import log_event
from edgecraft.risk import evaluate_orders

TERMINAL_RUN_STATUSES = {
    "not_due",
    "held",
    "risk_rejected",
    "shadow_complete",
    "completed",
    "failed",
}
SUCCESSFUL_RUN_STATUSES = TERMINAL_RUN_STATUSES - {"failed"}


class AgentRuntime(Protocol):
    def observe(
        self,
        mandate: Mandate,
        *,
        run_id: str,
        remaining_budget: Decimal,
        ledger_path: str | Path,
        risk_policy: RiskPolicy,
        external_context: ContextSnapshot | None = None,
        market_intelligence: MarketIntelligenceSnapshot | None = None,
    ) -> AgentCyclePayload: ...

    def preflight_order(
        self,
        mandate: Mandate,
        proposal: TradeProposal,
        order: ProposedOrder,
        *,
        ledger_path: str | Path,
    ) -> ExecutionPreflight: ...

    def execute_order(
        self,
        mandate: Mandate,
        proposal: TradeProposal,
        order: ProposedOrder,
        *,
        permit_token: str,
        ledger_path: str | Path,
    ) -> ExecutionResult: ...

    def reconcile_order(
        self,
        mandate: Mandate,
        proposal: TradeProposal,
        order: ProposedOrder,
        placed_result: ExecutionResult,
        *,
        ledger_path: str | Path,
    ) -> ExecutionResult: ...

    def recover_order(
        self,
        mandate: Mandate,
        proposal: TradeProposal,
        order: ProposedOrder,
        *,
        authority_issued_at: datetime,
        failure_observed_at: datetime,
        ledger_path: str | Path,
    ) -> ExecutionResult: ...


class AutonomousService:
    def __init__(
        self,
        repository: str | Path,
        ledger: AuditLedger,
        runtime: AgentRuntime | None = None,
        context_collector: ContextCollector | None = None,
        context_policy: WebContextPolicy | None = None,
        market_intelligence_collector: MarketIntelligenceCollector | None = None,
    ) -> None:
        self.repository = Path(repository).resolve()
        self.ledger = ledger
        self.runtime = runtime
        self.context_collector = context_collector
        self.context_policy = context_policy
        self.market_intelligence_collector = market_intelligence_collector

    def run_cycle(
        self,
        mandate: Mandate,
        *,
        now: datetime | None = None,
        force: bool = False,
    ) -> dict:
        use_wall_clock = now is None
        current_time = now or datetime.now(UTC)
        key = cycle_key(mandate, current_time)
        with self.ledger.cycle_lock(mandate.mandate_id, key) as acquired:
            if not acquired:
                existing = self.ledger.get_run_for_cycle(mandate.mandate_id, key)
                log_event(
                    "cycle_already_running",
                    mandate_id=mandate.mandate_id,
                    run_id=existing["run_id"] if existing else None,
                    cycle_key=key,
                )
                return {
                    "ok": True,
                    "status": "in_progress",
                    "cycle_key": key,
                    "run": existing,
                    "trading_halted": self.ledger.trading_halted(),
                }
            return self._run_cycle_locked(
                mandate,
                current_time=current_time,
                key=key,
                use_wall_clock=use_wall_clock,
                force=force,
            )

    def _run_cycle_locked(
        self,
        mandate: Mandate,
        *,
        current_time: datetime,
        key: str,
        use_wall_clock: bool,
        force: bool,
    ) -> dict:
        existing = self.ledger.get_run_for_cycle(mandate.mandate_id, key)
        if existing is not None:
            if (
                existing["status"] == "failed"
                and self.ledger.run_is_safe_to_retry(existing["run_id"])
                and self.runtime is not None
            ):
                self.ledger.record_retry(existing["run_id"], now=current_time)
                log_event(
                    "cycle_retry_started",
                    mandate_id=mandate.mandate_id,
                    run_id=existing["run_id"],
                    attempt=self.ledger.run_attempt_count(existing["run_id"]),
                )
                try:
                    return self._run_started_cycle(
                        mandate,
                        existing["run_id"],
                        current_time,
                        use_wall_clock=use_wall_clock,
                    )
                except Exception as exc:
                    self.ledger.update_run(
                        existing["run_id"],
                        "failed",
                        detail=f"{type(exc).__name__}: {exc}",
                        now=datetime.now(UTC),
                    )
                    log_event(
                        "cycle_retry_failed",
                        mandate_id=mandate.mandate_id,
                        run_id=existing["run_id"],
                        error_type=type(exc).__name__,
                    )
                    raise
            log_event(
                "cycle_idempotent_replay",
                mandate_id=mandate.mandate_id,
                run_id=existing["run_id"],
                status=existing["status"],
            )
            return {
                "ok": existing["status"] in SUCCESSFUL_RUN_STATUSES,
                "idempotent_replay": True,
                "run": existing,
            }
        if not force and not cycle_due(mandate, current_time):
            self.ledger.upsert_mandate(mandate, now=current_time)
            return {
                "ok": True,
                "status": "not_due",
                "cycle_key": key,
                "next_action": "Run again after the mandate's scheduled local time.",
            }
        if mandate.mode == "live" and self.ledger.trading_halted():
            raise RuntimeError("live cycle blocked because the trading kill switch is active")
        if self.runtime is None:
            raise RuntimeError("an agent runtime is required to run a due cycle")

        run_id = self.ledger.start_run(mandate, key, now=current_time)
        log_event(
            "cycle_started",
            mandate_id=mandate.mandate_id,
            run_id=run_id,
            mode=mandate.mode,
            cycle_key=key,
        )
        try:
            return self._run_started_cycle(
                mandate,
                run_id,
                current_time,
                use_wall_clock=use_wall_clock,
            )
        except Exception as exc:
            self.ledger.update_run(
                run_id,
                "failed",
                detail=f"{type(exc).__name__}: {exc}",
                now=datetime.now(UTC),
            )
            if mandate.mode == "live" and self.ledger.run_has_permit(run_id):
                self.ledger.set_trading_halt(
                    True,
                    reason=f"automatic halt after live execution exception in {run_id}",
                )
            log_event(
                "cycle_failed",
                mandate_id=mandate.mandate_id,
                run_id=run_id,
                error_type=type(exc).__name__,
            )
            raise

    def _run_started_cycle(
        self,
        mandate: Mandate,
        run_id: str,
        now: datetime,
        *,
        use_wall_clock: bool,
    ) -> dict:
        budget = available_cycle_budget(mandate, self.ledger, now=now)
        if budget <= 0:
            self.ledger.update_run(
                run_id,
                "completed",
                detail="cycle budget was already fully placed",
                payload={"remaining_budget": "0.00"},
            )
            return self._summary(run_id)

        self.ledger.update_run(
            run_id,
            "observing",
            payload={"remaining_budget": str(budget)},
            now=now,
        )
        policy = self._load_model(mandate.policy_path, RiskPolicy)
        research = (
            self._load_model(mandate.research_evidence_path, ResearchEvidence)
            if mandate.research_evidence_path
            else None
        )
        market_intelligence = self._collect_market_intelligence(mandate, run_id, now)
        external_context = self._collect_context(mandate, run_id, now)
        observation = self.runtime.observe(
            mandate,
            run_id=run_id,
            remaining_budget=budget,
            ledger_path=self.ledger.path,
            risk_policy=policy,
            external_context=external_context,
            market_intelligence=market_intelligence,
        )
        self._validate_observation(
            mandate,
            run_id,
            observation,
            external_context=external_context,
            context_policy=self.context_policy,
        )
        recorded_at = observation.observed_at
        decision_packet = DecisionAuditPacket(
            run_id=run_id,
            attempt=self.ledger.run_attempt_count(run_id),
            recorded_at=recorded_at,
            runtime=DecisionRuntimeMetadata(
                prompt_version=PROMPT_VERSION,
                model=mandate.decision_model or "configured_default",
                reasoning_effort=mandate.decision_reasoning_effort,
            ),
            mandate=mandate,
            risk_policy=policy,
            research_evidence=research,
            external_context=external_context,
            market_intelligence=market_intelligence,
            observation=observation,
        )
        packet_id = self.ledger.add_decision_packet(decision_packet)
        self.ledger.record_runtime_event(
            run_id,
            "observation_completed",
            {**_sanitized_observation_summary(observation), "decision_packet_id": packet_id},
        )

        proposal = create_weekly_proposal(
            mandate,
            observation.decision,
            observation.account,
            observation.quotes,
            policy,
            run_id=run_id,
            cycle_budget=budget,
            ledger=self.ledger,
            research=research,
            # A real observation can take minutes. Evaluate freshness against
            # completion time, not the cycle-start timestamp captured before
            # broker and market reads began. Explicit `now` remains stable for
            # deterministic tests and replay tooling.
            now=datetime.now(UTC) if use_wall_clock else now,
        )
        proposal_summary = {
            "proposal_id": proposal.proposal_id,
            "approved_for_review": proposal.risk.approved_for_review,
            "violations": proposal.risk.violations,
            "warnings": proposal.risk.warnings,
            "gross_notional": proposal.risk.gross_notional,
            "order_count": len(proposal.orders),
            "policy_digest": proposal.policy_digest,
            "prompt_version": PROMPT_VERSION,
            "decision_model": mandate.decision_model or "configured_default",
        }
        self.ledger.record_runtime_event(run_id, "proposal_created", proposal_summary)
        evaluation_state, evaluation_observation = advance_evaluation(
            mandate,
            proposal,
            observation.quotes,
            run_id=run_id,
            cycle_key=self.ledger.get_run(run_id)["cycle_key"],
            observed_at=observation.observed_at,
            prior=self.ledger.evaluation_state(mandate.mandate_id),
            cost_bps=mandate.evaluation_cost_bps,
        )
        evaluation_digest = self.ledger.record_evaluation(
            evaluation_observation,
            evaluation_state,
        )
        self.ledger.record_runtime_event(
            run_id,
            "benchmark_evaluation_recorded",
            {
                "benchmark": mandate.benchmark,
                "agent_action": evaluation_observation.agent_action,
                "contribution": str(evaluation_observation.contribution),
                "payload_sha256": evaluation_digest,
                "post_trade_values": {
                    name: str(value)
                    for name, value in evaluation_observation.post_trade_values.items()
                },
            },
            now=observation.observed_at,
        )

        if observation.decision.action == "hold":
            self.ledger.update_run(
                run_id,
                "held",
                detail=observation.decision.hypothesis,
                payload=proposal_summary,
            )
            return self._summary(run_id)
        if not proposal.risk.approved_for_review:
            self.ledger.update_run(
                run_id,
                "risk_rejected",
                detail="; ".join(proposal.risk.violations),
                payload=proposal_summary,
            )
            return self._summary(run_id)
        if mandate.mode == "shadow":
            self.ledger.update_run(
                run_id,
                "shadow_complete",
                detail="proposal validated; no broker mutation attempted",
                payload=proposal_summary,
            )
            return self._summary(run_id)

        self.ledger.update_run(
            run_id,
            "executing",
            detail="executing approved orders with single-use permits",
            payload=proposal_summary,
        )
        results = []
        for order in proposal.orders:
            result = self._execute_one(
                mandate,
                proposal,
                order,
                policy,
                research,
                now=now,
                use_wall_clock=use_wall_clock,
            )
            results.append(result.model_dump(mode="json"))
            if result.status in {"unknown", "partially_filled"}:
                self.ledger.set_trading_halt(
                    True,
                    reason=(
                        f"automatic halt after {result.status} order state for {order.order_key}"
                    ),
                )
                break
        final_status = (
            "completed"
            if results and all(item["status"] in {"placed", "filled"} for item in results)
            else "failed"
        )
        self.ledger.update_run(
            run_id,
            final_status,
            detail="broker execution cycle reconciled"
            if final_status == "completed"
            else ("execution did not reach a fully reconciled terminal state"),
            payload={**proposal_summary, "execution_results": results},
        )
        return self._summary(run_id)

    def _execute_one(
        self,
        mandate: Mandate,
        proposal: TradeProposal,
        order: ProposedOrder,
        policy: RiskPolicy,
        research: ResearchEvidence | None,
        *,
        now: datetime,
        use_wall_clock: bool,
    ) -> ExecutionResult:
        current_policy = self._load_model(mandate.policy_path, RiskPolicy)
        if policy_digest(current_policy) != proposal.policy_digest:
            raise RuntimeError("live policy changed after proposal creation")
        preflight = self.runtime.preflight_order(
            mandate,
            proposal,
            order,
            ledger_path=self.ledger.path,
        )
        risk_time = datetime.now(UTC) if use_wall_clock else now
        self._validate_preflight(proposal, order, preflight, policy)
        preflight_risk = evaluate_orders(
            preflight.account,
            [preflight.quote],
            [order],
            policy,
            strategy=proposal.strategy,
            mode="live",
            daily_placed_notional=self.ledger.daily_placed_notional(risk_time.date()),
            daily_placed_order_count=self.ledger.daily_placed_order_count(risk_time.date()),
            rolling_7d_placed_notional=self.ledger.rolling_placed_notional(
                since=risk_time - timedelta(days=7),
                before=risk_time,
            ),
            portfolio_high_watermark=self.ledger.portfolio_high_watermark(mandate.mandate_id),
            successful_shadow_cycles=self.ledger.successful_shadow_cycle_count(
                mandate.promotion_source_mandate_id or mandate.mandate_id
            ),
            unresolved_order_keys=self.ledger.unresolved_order_keys(),
            research=research,
            now=risk_time,
        )
        self.ledger.record_runtime_event(
            proposal.run_id or "",
            "execution_preflight_completed",
            {
                "proposal_id": proposal.proposal_id,
                "order_key": order.order_key,
                "approved": preflight_risk.approved_for_review,
                "violations": preflight_risk.violations,
                "warnings": preflight.review_warnings,
                "market_session": preflight.quote.market_session,
                "spread_bps": preflight_risk.spread_bps.get(order.symbol),
            },
            now=risk_time,
        )
        if not preflight_risk.approved_for_review:
            return ExecutionResult(
                run_id=proposal.run_id or "",
                proposal_id=proposal.proposal_id,
                order_key=order.order_key,
                status="aborted",
                symbol=order.symbol,
                side=order.side,
                requested_notional=Decimal(str(order.notional)),
                observed_at=risk_time,
                review_warnings=preflight_risk.violations,
                detail="deterministic execution preflight rejected the order",
            )
        if (
            policy_digest(self._load_model(mandate.policy_path, RiskPolicy))
            != proposal.policy_digest
        ):
            raise RuntimeError("live policy changed during execution preflight")
        constraints = {
            "account_id": proposal.account_id,
            "symbol": order.symbol,
            "side": order.side,
            "dollar_notional": order.notional,
            "order_type": order.order_type,
            "time_in_force": order.time_in_force,
            "market_hours": {
                "regular": "regular_hours",
                "pre_market": "extended_hours",
                "after_hours": "extended_hours",
            }.get(preflight.quote.market_session, "regular_hours"),
        }
        authority_issued_at = datetime.now(UTC)
        token = self.ledger.issue_permit(
            proposal.run_id or "",
            proposal.proposal_id,
            order.order_key,
            constraints=constraints,
        )
        try:
            result = self.runtime.execute_order(
                mandate,
                proposal,
                order,
                permit_token=token,
                ledger_path=self.ledger.path,
            )
            if result.broker_order_id and result.status in {
                "placed",
                "filled",
                "partially_filled",
                "unknown",
            }:
                result = self.runtime.reconcile_order(
                    mandate,
                    proposal,
                    order,
                    result,
                    ledger_path=self.ledger.path,
                )
                self.ledger.record_runtime_event(
                    proposal.run_id or "",
                    "broker_reconciliation_completed",
                    {
                        "proposal_id": proposal.proposal_id,
                        "order_key": order.order_key,
                        "status": result.status,
                    },
                )
            self._validate_execution_identity(proposal, order, result)
        except Exception as execution_error:
            failure_observed_at = datetime.now(UTC)
            self.ledger.record_runtime_event(
                proposal.run_id or "",
                "execution_result_failed_after_authority",
                {
                    "proposal_id": proposal.proposal_id,
                    "order_key": order.order_key,
                    "error_type": type(execution_error).__name__,
                },
                now=failure_observed_at,
            )
            recovered: ExecutionResult | None = None
            try:
                recovered = self.runtime.recover_order(
                    mandate,
                    proposal,
                    order,
                    authority_issued_at=authority_issued_at,
                    failure_observed_at=failure_observed_at,
                    ledger_path=self.ledger.path,
                )
                self._validate_execution_identity(proposal, order, recovered)
                self._record_execution_result(proposal, order, recovered)
                self.ledger.record_runtime_event(
                    proposal.run_id or "",
                    "broker_recovery_completed",
                    {
                        "proposal_id": proposal.proposal_id,
                        "order_key": order.order_key,
                        "status": recovered.status,
                        "broker_order_id_present": bool(recovered.broker_order_id),
                    },
                )
                recovery_status = recovered.status
            except Exception as recovery_error:
                self.ledger.record_runtime_event(
                    proposal.run_id or "",
                    "broker_recovery_failed",
                    {
                        "proposal_id": proposal.proposal_id,
                        "order_key": order.order_key,
                        "error_type": type(recovery_error).__name__,
                    },
                )
                recovery_status = "unavailable"
            if recovered is not None and recovered.status in {"filled", "rejected", "canceled"}:
                if recovered.status in {"rejected", "canceled"}:
                    self.ledger.revoke_permit(token)
                self.ledger.record_runtime_event(
                    proposal.run_id or "",
                    "execution_recovery_terminal",
                    {
                        "proposal_id": proposal.proposal_id,
                        "order_key": order.order_key,
                        "status": recovered.status,
                        "original_error_type": type(execution_error).__name__,
                    },
                )
                return recovered
            self.ledger.set_trading_halt(
                True,
                reason=f"automatic halt after live execution recovery in {proposal.run_id}",
            )
            raise RuntimeError(
                "execution result failed after authority; "
                f"read-only broker recovery status={recovery_status}"
            ) from execution_error
        if result.status in {"aborted", "reviewed", "rejected", "canceled"}:
            self.ledger.revoke_permit(token)
        self._record_execution_result(proposal, order, result)
        return result

    @staticmethod
    def _validate_execution_identity(
        proposal: TradeProposal,
        order: ProposedOrder,
        result: ExecutionResult,
    ) -> None:
        if (
            result.run_id != proposal.run_id
            or result.proposal_id != proposal.proposal_id
            or result.order_key != order.order_key
            or result.symbol != order.symbol
            or result.side != order.side
            or result.requested_notional != Decimal(str(order.notional))
        ):
            raise RuntimeError("execution result does not match the permitted order")

    def _record_execution_result(
        self,
        proposal: TradeProposal,
        order: ProposedOrder,
        result: ExecutionResult,
    ) -> None:
        self.ledger.record_runtime_event(
            proposal.run_id or "",
            "broker_execution_observed",
            {
                "proposal_id": proposal.proposal_id,
                "order_key": order.order_key,
                "status": result.status,
                "broker_order_id_present": bool(result.broker_order_id),
                "requested_notional": str(result.requested_notional),
                "filled_notional": str(result.filled_notional),
            },
        )
        reasoning = {
            "proposal_rationale": proposal.rationale,
            "order_rationale": order.rationale,
            "decision_reasoning": (
                proposal.decision_reasoning.model_dump(mode="json")
                if proposal.decision_reasoning
                else None
            ),
        }
        if result.status in {"placed", "filled", "partially_filled"}:
            placed_payload = {
                "order_key": order.order_key,
                "notional": float(result.requested_notional),
                "broker_order_id": result.broker_order_id,
                "reasoning": reasoning,
            }
            self._record_once(
                proposal.proposal_id,
                "placed",
                placed_payload,
                occurred_at=result.observed_at,
            )
        if result.status in {"filled", "partially_filled", "rejected", "canceled"}:
            terminal_payload = {
                "order_key": order.order_key,
                "notional": float(result.requested_notional),
                "filled_notional": float(result.filled_notional),
                "broker_order_id": result.broker_order_id,
                "average_fill_price": (
                    float(result.average_fill_price) if result.average_fill_price else None
                ),
                "fees": str(result.fees),
                "reasoning": reasoning,
            }
            self._record_once(
                proposal.proposal_id,
                result.status,
                terminal_payload,
                occurred_at=result.observed_at,
            )

    @staticmethod
    def _validate_preflight(
        proposal: TradeProposal,
        order: ProposedOrder,
        preflight: ExecutionPreflight,
        policy: RiskPolicy,
    ) -> None:
        if (
            preflight.run_id != proposal.run_id
            or preflight.proposal_id != proposal.proposal_id
            or preflight.order_key != order.order_key
            or preflight.account.account_id != proposal.account_id
            or preflight.quote.symbol != order.symbol
            or preflight.reviewed_notional != Decimal(str(order.notional))
        ):
            raise RuntimeError("execution preflight identity does not match the approved order")
        if not preflight.review_approved or preflight.review_warnings:
            review_kind = (
                "Robinhood review" if policy.require_review else "standing-authority preflight"
            )
            raise RuntimeError(f"{review_kind} did not approve the exact order")

    def _record_once(
        self,
        proposal_id: str,
        event_type: str,
        payload: dict,
        *,
        occurred_at: datetime,
    ) -> None:
        with suppress(DuplicateProposalError):
            self.ledger.record_event(
                proposal_id,
                event_type,
                payload,
                occurred_at=occurred_at,
            )

    def _load_model(self, configured_path: str | None, model_type):
        if not configured_path:
            raise ValueError(f"{model_type.__name__} path is required")
        path = Path(configured_path)
        resolved = path if path.is_absolute() else self.repository / path
        with resolved.open(encoding="utf-8") as handle:
            return model_type.model_validate(json.load(handle))

    def _collect_context(
        self,
        mandate: Mandate,
        run_id: str,
        now: datetime,
    ) -> ContextSnapshot | None:
        if not mandate.external_context_path:
            return None
        if self.context_collector is None or self.context_policy is None:
            raise RuntimeError(
                "mandate requires external context but no context collector is configured"
            )
        context_symbols = list(dict.fromkeys([*mandate.universe, mandate.benchmark]))
        snapshot = self.context_collector.collect(context_symbols, now=now)
        self.ledger.record_runtime_event(
            run_id,
            "external_context_collected",
            snapshot.model_dump(mode="json"),
            now=now,
        )
        if (
            self.context_policy.require_for_live
            and mandate.mode == "live"
            and not snapshot.complete
        ):
            raise RuntimeError("live cycle blocked because required external context is incomplete")
        return snapshot

    def _collect_market_intelligence(
        self,
        mandate: Mandate,
        run_id: str,
        now: datetime,
    ) -> MarketIntelligenceSnapshot | None:
        if self.market_intelligence_collector is None:
            return None
        snapshot = self.market_intelligence_collector.collect(
            mandate.universe,
            benchmark=mandate.benchmark,
            now=now,
        )
        self.ledger.record_runtime_event(
            run_id,
            "market_intelligence_collected",
            {
                "provider": snapshot.provider,
                "benchmark": snapshot.benchmark,
                "symbol_count": len(snapshot.symbols),
                "history_sessions": snapshot.history_sessions,
                "last_completed_session": snapshot.last_completed_session.isoformat(),
                "input_sha256": snapshot.input_sha256,
                "warnings": snapshot.warnings,
            },
            now=now,
        )
        return snapshot

    @staticmethod
    def _validate_observation(
        mandate: Mandate,
        run_id: str,
        observation: AgentCyclePayload,
        *,
        external_context: ContextSnapshot | None = None,
        context_policy: WebContextPolicy | None = None,
    ) -> None:
        if observation.decision.mandate_id != mandate.mandate_id:
            raise ValueError("agent observation returned the wrong mandate_id")
        if observation.decision.run_id != run_id:
            raise ValueError("agent observation returned the wrong run_id")
        decision_symbols = {allocation.symbol for allocation in observation.decision.allocations}
        if not decision_symbols.issubset(set(mandate.universe)):
            raise ValueError("agent observation proposed a symbol outside the mandate universe")
        quote_symbols = {quote.symbol for quote in observation.quotes}
        required_quotes = {mandate.benchmark, *mandate.strategic_weights}
        missing_quotes = sorted(required_quotes - quote_symbols)
        if missing_quotes:
            raise ValueError(f"agent observation is missing evaluation quotes: {missing_quotes}")
        if external_context is not None:
            known_ids = {source.source_id for source in external_context.sources}
            cited_ids = set(observation.decision.context_source_ids)
            if not cited_ids.issubset(known_ids):
                raise ValueError("agent observation cited an unknown external context source")
            required = context_policy.min_decision_citations if context_policy else 1
            if observation.decision.action == "invest" and len(cited_ids) < required:
                raise ValueError(
                    f"invest decision requires at least {required} external context citations"
                )
        evidence_by_id = {item.evidence_id: item for item in observation.decision.evidence_items}
        evidence_ids = set(evidence_by_id)
        if not evidence_ids:
            raise ValueError("every decision requires a structured evidence inventory")
        if external_context is not None:
            evidence_context_ids = {
                source_id
                for item in observation.decision.evidence_items
                for source_id in item.context_source_ids
            }
            unknown_evidence_context = evidence_context_ids - known_ids
            if unknown_evidence_context:
                raise ValueError(
                    "decision evidence cited unknown external context sources: "
                    f"{sorted(unknown_evidence_context)}"
                )
            uncited_evidence_context = evidence_context_ids - cited_ids
            if uncited_evidence_context:
                raise ValueError(
                    "decision evidence used external context absent from the decision citations: "
                    f"{sorted(uncited_evidence_context)}"
                )
        future_evidence = [
            item.evidence_id
            for item in observation.decision.evidence_items
            if item.observed_at > observation.observed_at
            or (
                item.source_timestamp is not None
                and item.source_timestamp > observation.observed_at
            )
        ]
        if future_evidence:
            raise ValueError(f"decision evidence is newer than observation: {future_evidence}")
        if observation.decision.action == "invest":
            uncited_allocations = [
                allocation.symbol
                for allocation in observation.decision.allocations
                if not allocation.evidence_ids
            ]
            if uncited_allocations:
                raise ValueError(
                    f"invest allocations require evidence IDs: {sorted(uncited_allocations)}"
                )
            for allocation in observation.decision.allocations:
                cited = [evidence_by_id[evidence_id] for evidence_id in allocation.evidence_ids]
                has_quote = any(
                    item.category == "quote" and item.symbol == allocation.symbol for item in cited
                )
                has_market_history = any(
                    item.category in {"technical", "historical", "research"}
                    and item.symbol == allocation.symbol
                    for item in cited
                )
                if not has_quote or not has_market_history:
                    raise ValueError(
                        f"allocation {allocation.symbol} requires symbol-specific quote and "
                        "historical/technical/research evidence"
                    )
                if external_context is not None and not any(
                    item.category in {"web", "regulatory"} and item.context_source_ids
                    for item in cited
                ):
                    raise ValueError(
                        f"allocation {allocation.symbol} requires cited web or regulatory evidence"
                    )

    def _summary(self, run_id: str) -> dict:
        run = self.ledger.get_run(run_id)
        log_event(
            "cycle_finished",
            mandate_id=run["mandate_id"],
            run_id=run_id,
            status=run["status"],
            mode=run["mode"],
        )
        return {
            "ok": run["status"] in SUCCESSFUL_RUN_STATUSES,
            "idempotent_replay": False,
            "run": run,
            "trading_halted": self.ledger.trading_halted(),
        }


class StaticObservationRuntime:
    """Deterministic integration-test/runtime adapter for a captured MCP payload."""

    def __init__(self, payload: AgentCyclePayload) -> None:
        self.payload = payload

    def observe(
        self,
        mandate: Mandate,
        *,
        run_id: str,
        remaining_budget: Decimal,
        ledger_path: str | Path,
        risk_policy: RiskPolicy,
        external_context: ContextSnapshot | None = None,
        market_intelligence: MarketIntelligenceSnapshot | None = None,
    ) -> AgentCyclePayload:
        del (
            mandate,
            remaining_budget,
            ledger_path,
            risk_policy,
            external_context,
            market_intelligence,
        )
        if self.payload.decision.run_id != run_id:
            return self.payload.model_copy(
                update={"decision": self.payload.decision.model_copy(update={"run_id": run_id})}
            )
        return self.payload

    def execute_order(
        self,
        mandate: Mandate,
        proposal: TradeProposal,
        order: ProposedOrder,
        *,
        permit_token: str,
        ledger_path: str | Path,
    ) -> ExecutionResult:
        del mandate, proposal, order, permit_token, ledger_path
        raise RuntimeError("captured observations cannot execute live orders")

    def preflight_order(
        self,
        mandate: Mandate,
        proposal: TradeProposal,
        order: ProposedOrder,
        *,
        ledger_path: str | Path,
    ) -> ExecutionPreflight:
        del mandate, proposal, order, ledger_path
        raise RuntimeError("captured observations cannot preflight live orders")

    def reconcile_order(
        self,
        mandate: Mandate,
        proposal: TradeProposal,
        order: ProposedOrder,
        placed_result: ExecutionResult,
        *,
        ledger_path: str | Path,
    ) -> ExecutionResult:
        del mandate, proposal, order, placed_result, ledger_path
        raise RuntimeError("captured observations cannot reconcile live orders")


def build_default_service(
    repository: str | Path,
    ledger_path: str | Path,
) -> AutonomousService:
    repository_path = Path(repository).resolve()
    ledger = AuditLedger(ledger_path)
    runtime = CodexRuntime(config=CodexRuntimeConfig(repository=repository_path))
    return AutonomousService(repository_path, ledger, runtime)


def _sanitized_observation_summary(observation: AgentCyclePayload) -> dict:
    return {
        "observed_at": observation.observed_at.isoformat(),
        "agentic_allowed": observation.account.agentic_allowed,
        "account_restricted": observation.account.account_restricted,
        "portfolio_value": observation.account.portfolio_value,
        "buying_power": observation.account.buying_power,
        "position_symbols": sorted(position.symbol for position in observation.account.positions),
        "open_order_count": len(observation.account.open_orders),
        "quote_symbols": sorted(quote.symbol for quote in observation.quotes),
        "decision_action": observation.decision.action,
        "decision_confidence": str(observation.decision.confidence),
        "allocation_symbols": sorted(
            allocation.symbol for allocation in observation.decision.allocations
        ),
        "allocation_notional": str(
            sum(
                (allocation.notional for allocation in observation.decision.allocations),
                Decimal("0"),
            )
        ),
    }
