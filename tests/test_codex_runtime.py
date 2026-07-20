from edgecraft.autonomy_models import AgentCyclePayload, Mandate
from edgecraft.codex_runtime import (
    CodexRuntimeConfig,
    _runtime_environment,
    observation_prompt,
    strict_output_schema,
)


def test_runtime_defaults_to_read_only_workspace(tmp_path):
    assert CodexRuntimeConfig(repository=tmp_path).sandbox == "read-only"


def test_runtime_does_not_inherit_unrelated_shell_secrets(monkeypatch):
    monkeypatch.setenv("PATH", "/safe/bin")
    monkeypatch.setenv("UNRELATED_API_TOKEN", "must-not-cross-boundary")
    environment = _runtime_environment()
    assert environment["PATH"] == "/safe/bin"
    assert "UNRELATED_API_TOKEN" not in environment


def test_strict_output_schema_closes_objects_and_requires_fields():
    schema = strict_output_schema(AgentCyclePayload)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])

    definitions = schema["$defs"]
    for definition in definitions.values():
        if "properties" in definition:
            assert definition["additionalProperties"] is False
            assert set(definition["required"]) == set(definition["properties"])
    assert "pattern" not in str(schema)


def test_observation_prompt_includes_hard_budget_and_policy():
    mandate = Mandate(
        mandate_id="prompt_test",
        goal="Invest a bounded amount into a diversified index portfolio.",
        weekly_budget="10",
        universe=["VTI"],
        strategic_weights={"VTI": "1"},
        policy_path="policy.json",
    )
    prompt = observation_prompt(
        mandate,
        run_id="run-test",
        remaining_budget=mandate.weekly_budget,
        policy={"min_order_notional": 1, "max_daily_notional": 10},
    )
    assert "Remaining hard cycle budget: 10.00" in prompt
    assert '"min_order_notional": 1' in prompt
