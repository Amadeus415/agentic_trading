from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from edgecraft.autonomy_models import AgentCyclePayload, ExecutionResult, Mandate
from edgecraft.execution_models import ProposedOrder, TradeProposal

OutputModel = TypeVar("OutputModel", bound=BaseModel)


class CodexRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CodexRuntimeConfig:
    repository: Path
    state_directory: Path = Path("state/runtime")
    executable: str = "codex"
    timeout_seconds: int = 1_200
    sandbox: str = "workspace-write"


class CodexRuntime:
    """Runs an ephemeral Codex turn using the host's authenticated MCP connections."""

    def __init__(self, config: CodexRuntimeConfig) -> None:
        self.config = config
        executable = shutil.which(config.executable)
        if executable is None:
            raise CodexRuntimeError(f"Codex executable not found: {config.executable}")
        self.executable = executable
        self.repository = config.repository.resolve()
        state = config.state_directory
        self.state_directory = (
            state if state.is_absolute() else (self.repository / state)
        ).resolve()

    def observe(
        self,
        mandate: Mandate,
        *,
        run_id: str,
        remaining_budget: Decimal,
        ledger_path: str | Path,
    ) -> AgentCyclePayload:
        prompt = observation_prompt(
            mandate,
            run_id=run_id,
            remaining_budget=remaining_budget,
        )
        return self._run(
            prompt,
            AgentCyclePayload,
            run_id=run_id,
            phase="observe",
            model=mandate.decision_model,
            ledger_path=ledger_path,
        )

    def execute_order(
        self,
        mandate: Mandate,
        proposal: TradeProposal,
        order: ProposedOrder,
        *,
        permit_token: str,
        ledger_path: str | Path,
    ) -> ExecutionResult:
        if proposal.mode != "live" or not proposal.risk.approved_for_review:
            raise CodexRuntimeError("execution requires an approved live proposal")
        if proposal.run_id is None:
            raise CodexRuntimeError("autonomous proposal is missing run_id")
        prompt = execution_prompt(mandate, proposal, order)
        return self._run(
            prompt,
            ExecutionResult,
            run_id=proposal.run_id,
            phase=f"execute-{order.order_key}",
            model=mandate.decision_model,
            ledger_path=ledger_path,
            permit_token=permit_token,
        )

    def _run(
        self,
        prompt: str,
        output_model: type[OutputModel],
        *,
        run_id: str,
        phase: str,
        model: str | None,
        ledger_path: str | Path,
        permit_token: str | None = None,
    ) -> OutputModel:
        run_directory = self.state_directory / run_id
        run_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        schema_path = run_directory / f"{phase}.schema.json"
        result_path = run_directory / f"{phase}.result.json"
        schema_path.write_text(
            json.dumps(output_model.model_json_schema(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        schema_path.chmod(0o600)
        result_path.unlink(missing_ok=True)

        command = [
            self.executable,
            "exec",
            "--ephemeral",
            "--color",
            "never",
            "--sandbox",
            self.config.sandbox,
            "--config",
            'approval_policy="never"',
            "--dangerously-bypass-hook-trust",
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(result_path),
            "--cd",
            str(self.repository),
        ]
        if model:
            command.extend(["--model", model])
        command.append(prompt)

        environment = os.environ.copy()
        environment["CODEX_NON_INTERACTIVE"] = "1"
        environment["EDGECRAFT_LEDGER_PATH"] = str(Path(ledger_path).resolve())
        if permit_token is None:
            environment.pop("EDGECRAFT_PERMIT_TOKEN", None)
        else:
            environment["EDGECRAFT_PERMIT_TOKEN"] = permit_token

        try:
            completed = subprocess.run(
                command,
                cwd=self.repository,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.config.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise CodexRuntimeError(
                f"Codex {phase} phase timed out after {self.config.timeout_seconds}s"
            ) from exc
        if completed.returncode != 0:
            detail = _safe_process_detail(completed.stdout, completed.stderr)
            raise CodexRuntimeError(f"Codex {phase} phase exited {completed.returncode}: {detail}")
        if not result_path.exists():
            raise CodexRuntimeError(f"Codex {phase} phase produced no structured result")
        result_path.chmod(0o600)
        try:
            return output_model.model_validate_json(result_path.read_text(encoding="utf-8"))
        except Exception as exc:
            digest = hashlib.sha256(result_path.read_bytes()).hexdigest()[:16]
            raise CodexRuntimeError(
                f"Codex {phase} result failed schema validation (sha256={digest})"
            ) from exc


def observation_prompt(
    mandate: Mandate,
    *,
    run_id: str,
    remaining_budget: Decimal,
) -> str:
    mandate_payload = mandate.model_dump(mode="json")
    return f"""
You are the research and decision component of an autonomous, long-only portfolio
manager. This is an OBSERVATION-ONLY phase. Do not place, cancel, create, update,
add, remove, follow, or unfollow anything through Robinhood. Do not edit source
files. The project hook will reject broker mutations.

Use the authenticated Robinhood Trading MCP as broker truth. Perform this cycle:
1. Call get_accounts and select exactly one account explicitly returned as
   agentic_allowed=true. Never use a primary or non-agentic account.
2. Refresh its portfolio, equity positions, equity order history/open orders,
   realized P&L, and trade-by-trade P&L.
3. Fetch current quotes and tradability for every mandate-universe symbol and
   every held symbol. Use Robinhood historicals, fundamentals, and technical
   indicators where useful. Prefer completed bars and name each source used.
4. Evaluate at least three alternatives: plain strategic-weight DCA, a bounded
   tactical tilt, and holding cash. Test the weekly hypothesis against price
   history and the existing Edgecraft research tools when useful. Do not infer
   news or facts you did not retrieve.
5. Return one structured decision. Total proposed notional must not exceed
   ${remaining_budget:.2f}. Every symbol must be in the mandate universe. A hold
   is valid when evidence, freshness, confidence, or price quality is weak.

The model is advisory only. Edgecraft will independently enforce budget, symbol,
concentration, cash, freshness, and risk limits. Never claim that a trade is
safe, guaranteed, or already placed. Preserve exact UTC source timestamps.

Active run_id: {run_id}
Remaining hard cycle budget: {remaining_budget:.2f}
Mandate:
{json.dumps(mandate_payload, indent=2, sort_keys=True)}

Return only the JSON object required by the supplied output schema. Set the
decision mandate_id and run_id exactly to the values above. The account field
must be a fresh canonical PortfolioSnapshot; include open broker orders. Quotes
must be fresh canonical MarketQuote objects with MCP tradability results.
""".strip()


def execution_prompt(
    mandate: Mandate,
    proposal: TradeProposal,
    order: ProposedOrder,
) -> str:
    constraints = {
        "mandate_id": mandate.mandate_id,
        "run_id": proposal.run_id,
        "proposal_id": proposal.proposal_id,
        "order": order.model_dump(mode="json"),
        "snapshot_as_of": proposal.snapshot_as_of.isoformat(),
        "policy_name": proposal.policy_name,
    }
    return f"""
You are the narrowly scoped execution component of an autonomous portfolio
manager. You are authorized to handle exactly ONE approved long-equity order
described below. Do not edit files and do not perform any other broker mutation.

Before placement:
1. Refresh get_accounts and select only the account returned as
   agentic_allowed=true that matches the proposal.
2. Refresh portfolio, positions, open equity orders, quote, and tradability.
3. ABORT without placing if there is an unknown open order, account restriction,
   account mismatch, insufficient buying power, non-tradability, a quote older
   than five minutes, or price movement over 100 bps from expected_price.
4. Call review_equity_order for the exact symbol, side, dollar notional, order
   type, and time in force. ABORT on any warning, transformed amount, or mismatch.
5. Only then call place_equity_order once. A single-use Edgecraft hook permit
   enforces this. Never place an option, margin, short, crypto, or second order.
6. Query get_equity_orders to reconcile the resulting broker order. Report the
   observed state honestly; "unknown" is preferable to guessing.

Exact approved constraints:
{json.dumps(constraints, indent=2, sort_keys=True)}

Return only the JSON object required by the supplied output schema. Copy run_id,
proposal_id, order_key, symbol, side, and requested_notional exactly. Include no
account number or token in the output.
""".strip()


def _safe_process_detail(stdout: str, stderr: str) -> str:
    text = (stderr or stdout).strip().replace("\n", " ")
    if not text:
        return "no diagnostic output"
    lowered = text.lower()
    if any(term in lowered for term in ("account", "token", "portfolio", "position")):
        return "diagnostic output redacted because it may contain broker data"
    return text[-500:]
