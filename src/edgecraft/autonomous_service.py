from __future__ import annotations

import json
from contextlib import suppress
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from edgecraft.autonomy import (
    available_cycle_budget,
    create_weekly_proposal,
    cycle_due,
    cycle_key,
)
from edgecraft.autonomy_models import (
    AgentCyclePayload,
    ExecutionResult,
    Mandate,
)
from edgecraft.codex_runtime import CodexRuntime, CodexRuntimeConfig
from edgecraft.context import ContextCollector, ContextSnapshot, WebContextPolicy
from edgecraft.execution_models import (
    ProposedOrder,
    ResearchEvidence,
    RiskPolicy,
    TradeProposal,
)
from edgecraft.ledger import AuditLedger, DuplicateProposalError
from edgecraft.observability import log_event

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
        external_context: ContextSnapshot | None = None,
    ) -> AgentCyclePayload: ...

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


class AutonomousService:
    def __init__(
        self,
        repository: str | Path,
        ledger: AuditLedger,
        runtime: AgentRuntime | None = None,
        context_collector: ContextCollector | None = None,
        context_policy: WebContextPolicy | None = None,
    ) -> None:
        self.repository = Path(repository).resolve()
        self.ledger = ledger
        self.runtime = runtime
        self.context_collector = context_collector
        self.context_policy = context_policy

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
        external_context = self._collect_context(mandate, run_id, now)
        observation = self.runtime.observe(
            mandate,
            run_id=run_id,
            remaining_budget=budget,
            ledger_path=self.ledger.path,
            external_context=external_context,
        )
        self._validate_observation(
            mandate,
            run_id,
            observation,
            external_context=external_context,
            context_policy=self.context_policy,
        )
        self.ledger.record_runtime_event(
            run_id,
            "observation_completed",
            _sanitized_observation_summary(observation),
        )

        policy = self._load_model(mandate.policy_path, RiskPolicy)
        research = (
            self._load_model(mandate.research_evidence_path, ResearchEvidence)
            if mandate.research_evidence_path
            else None
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
        }
        self.ledger.record_runtime_event(run_id, "proposal_created", proposal_summary)

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
            result = self._execute_one(mandate, proposal, order)
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
    ) -> ExecutionResult:
        constraints = {
            "account_id": proposal.account_id,
            "symbol": order.symbol,
            "side": order.side,
            "dollar_notional": order.notional,
            "order_type": order.order_type,
            "time_in_force": order.time_in_force,
        }
        token = self.ledger.issue_permit(
            proposal.run_id or "",
            proposal.proposal_id,
            order.order_key,
            constraints=constraints,
        )
        result = self.runtime.execute_order(
            mandate,
            proposal,
            order,
            permit_token=token,
            ledger_path=self.ledger.path,
        )
        placement_confirmed = result.status in {
            "placed",
            "filled",
            "partially_filled",
        }
        if result.status == "placed":
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
        if result.status in {"aborted", "reviewed", "rejected", "canceled"}:
            self.ledger.revoke_permit(token)
        if (
            result.run_id != proposal.run_id
            or result.proposal_id != proposal.proposal_id
            or result.order_key != order.order_key
            or result.symbol != order.symbol
            or result.side != order.side
            or result.requested_notional != Decimal(str(order.notional))
        ):
            self.ledger.set_trading_halt(
                True, reason=f"execution result identity mismatch for {order.order_key}"
            )
            raise RuntimeError("execution result does not match the permitted order")
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
        if placement_confirmed or result.status in {"filled", "partially_filled"}:
            placed_payload = {
                "order_key": order.order_key,
                "notional": float(result.requested_notional),
                "broker_order_id": result.broker_order_id,
            }
            self._record_once(proposal.proposal_id, "placed", placed_payload)
        if result.status in {"filled", "partially_filled", "rejected", "canceled"}:
            terminal_payload = {
                "order_key": order.order_key,
                "notional": float(result.requested_notional),
                "filled_notional": float(result.filled_notional),
                "broker_order_id": result.broker_order_id,
            }
            self._record_once(proposal.proposal_id, result.status, terminal_payload)
        return result

    def _record_once(
        self,
        proposal_id: str,
        event_type: str,
        payload: dict,
    ) -> None:
        with suppress(DuplicateProposalError):
            self.ledger.record_event(proposal_id, event_type, payload)

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
        snapshot = self.context_collector.collect(mandate.universe, now=now)
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
        external_context: ContextSnapshot | None = None,
    ) -> AgentCyclePayload:
        del mandate, remaining_budget, ledger_path, external_context
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
