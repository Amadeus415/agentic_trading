from __future__ import annotations

import json
from pathlib import Path

from edgecraft.results_charts import short_question

ROOT = Path(__file__).resolve().parents[1]


def test_short_question_keeps_the_outcome_token():
    label = short_question(
        "Will the price of Bitcoin be above $76,000 on September 17?", "polymarket:1:NO"
    )
    assert label == "BTC > $76k on Sep 17 \u00b7 NO"
    assert short_question(None, "polymarket:42:YES").endswith("\u00b7 YES")


def test_committed_results_render_every_chart(tmp_path: Path):
    from edgecraft.results_charts import CHARTS, render_all

    results = json.loads((ROOT / "results/results.json").read_text())
    paths = render_all(results, tmp_path)
    assert sorted(p.name for p in paths) == sorted(CHARTS)
    assert all(p.stat().st_size > 20_000 for p in paths)
