import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from edgecraft.fund_visualization import _nice_ticks, _svg, render_fund_progress
from edgecraft.paper_fund import FundMandate, FundState, PaperFundLedger

ROOT = Path(__file__).resolve().parents[1]


def test_render_fund_progress_is_verified_github_safe_svg(tmp_path: Path) -> None:
    config = json.loads((ROOT / "examples" / "fund.mandate.json").read_text())
    mandate = FundMandate.model_validate(config["mandate"])
    output = tmp_path / "nested" / "progress.svg"
    with PaperFundLedger(tmp_path / "fund.db") as ledger:
        ledger.initialize(config["fund_id"], mandate)
        result = render_fund_progress(ledger, config["fund_id"], mandate, output)

    svg = output.read_text()
    assert result["paper_only"] is True
    assert result["verification"] == {"chain_ok": True, "accounting_ok": True}
    assert '<svg xmlns="http://www.w3.org/2000/svg"' in svg
    assert "100% FAKE MONEY" in svg
    assert "$1,000.00" in svg
    assert "FUND VALUE" in svg
    assert "Started at $1,000.00" in svg
    assert "How the $1,000.00 has moved" in svg
    assert "<script" not in svg
    assert "GROSS EXPOSURE" not in svg


def test_chart_explains_a_drawdown_against_starting_capital() -> None:
    config = json.loads((ROOT / "examples" / "fund.mandate.aggressive.json").read_text())
    mandate = FundMandate.model_validate(config["mandate"])
    state = FundState(
        fund_id="edgecraft-aggressive",
        as_of=datetime(2026, 9, 1, 20, 19, tzinfo=UTC),
        cash=Decimal("446.82"),
        positions=(),
        nav=Decimal("932.13"),
        peak_nav=Decimal("1189.88"),
        drawdown=Decimal("0.22"),
        gross_exposure=Decimal("1193.57"),
        net_exposure=Decimal("485.31"),
        short_exposure=Decimal("354.13"),
        cycle_count=3,
        last_cycle_key="2026-09-01-session-us-close",
    )
    history = [
        {
            "as_of": "2026-08-22T17:35:00Z",
            "nav": "1000.00",
            "action": "hold",
            "fill_count": 0,
        },
        {
            "as_of": "2026-08-31T17:23:42Z",
            "nav": "1189.88",
            "action": "trade",
            "fill_count": 2,
        },
        {
            "as_of": "2026-09-01T20:19:00Z",
            "nav": "932.13",
            "action": "trade",
            "fill_count": 3,
        },
    ]

    svg = _svg("edgecraft-aggressive", mandate, state, history)

    assert "FUND VALUE" in svg
    assert "$932.13" in svg
    assert "-$67.87" in svg
    assert "-6.79%" in svg
    assert "Started at $1,000.00" in svg
    assert "peak $1,189.88" in svg
    assert "$1,000" in svg
    assert "#818cf8" in svg
    assert 'stroke="#fb7185"' not in svg
    assert "All cash" in svg
    assert "100% FAKE MONEY" in svg
    assert "<script" not in svg


def test_nice_ticks_include_round_dollar_marks() -> None:
    ticks = _nice_ticks(Decimal("890"), Decimal("1230"))
    assert Decimal("1000") in ticks
    assert all(tick == tick.to_integral_value() for tick in ticks)
