from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field, SkipValidation, field_validator, model_validator

from edgecraft.autonomy_models import AgentCyclePayload, Mandate
from edgecraft.context import ContextSnapshot
from edgecraft.decision_memory import DecisionMemorySnapshot
from edgecraft.execution_models import ResearchEvidence, RiskPolicy
from edgecraft.intelligence import MarketIntelligenceSnapshot


class DecisionRuntimeMetadata(BaseModel):
    prompt_version: str = Field(min_length=1, max_length=200)
    model: str = Field(min_length=1, max_length=200)
    reasoning_effort: str | None = Field(default=None, max_length=50)


class DecisionAuditPacket(BaseModel):
    """Immutable, replayable record of every normalized decision input and output."""

    schema_version: str = "edgecraft.decision-audit.v2"
    run_id: str = Field(min_length=1)
    attempt: int = Field(ge=1)
    recorded_at: datetime
    runtime: DecisionRuntimeMetadata
    mandate: SkipValidation[Mandate]
    risk_policy: RiskPolicy
    research_evidence: ResearchEvidence | None = None
    external_context: ContextSnapshot | None = None
    market_intelligence: MarketIntelligenceSnapshot | None = None
    decision_memory: DecisionMemorySnapshot | None = None
    observation: AgentCyclePayload

    @field_validator("recorded_at")
    @classmethod
    def recorded_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("recorded_at must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def identities_cohere(self) -> DecisionAuditPacket:
        decision = self.observation.decision
        if decision.run_id != self.run_id:
            raise ValueError("decision run_id does not match audit packet")
        if decision.mandate_id != self.mandate.mandate_id:
            raise ValueError("decision mandate_id does not match audit packet")
        if self.decision_memory is not None:
            if self.decision_memory.mandate_id != self.mandate.mandate_id:
                raise ValueError("decision memory mandate_id does not match audit packet")
            known_prior_runs = {item.run_id for item in self.decision_memory.prior_decisions}
            referenced = set(decision.referenced_prior_run_ids)
            if self.run_id in referenced:
                raise ValueError("decision cannot reference its own run as prior memory")
            if not referenced.issubset(known_prior_runs):
                raise ValueError("decision references a run absent from decision memory")
        elif decision.referenced_prior_run_ids:
            raise ValueError("decision references prior runs without decision memory")
        if self.external_context is not None:
            known = {source.source_id for source in self.external_context.sources}
            cited = set(decision.context_source_ids)
            if not cited.issubset(known):
                raise ValueError("decision audit packet contains unknown context citations")
            evidence_citations = {
                source_id
                for item in decision.evidence_items
                for source_id in item.context_source_ids
            }
            if not evidence_citations.issubset(known):
                raise ValueError(
                    "decision audit packet evidence contains unknown context citations"
                )
            if not evidence_citations.issubset(cited):
                raise ValueError(
                    "decision audit packet evidence contains context absent from decision citations"
                )
        return self
