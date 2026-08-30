import json
from pathlib import Path

from edgecraft.fund_visualization import render_fund_progress
from edgecraft.paper_fund import FundMandate, PaperFundLedger

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
    assert "<script" not in svg
