"""Score the first funded forecast per contract against the entry market.

Refreshes, scale-ins, and repeated holds cannot multiply the sample. Resolution
requires an official SETTLED quote; target hits and profitable exits do not count
as binary outcomes. CLV uses the last recorded pre-settlement mark and is labelled
sampled because the ledger does not guarantee a quote at the market's close.
"""

from collections import defaultdict
from decimal import Decimal
from typing import Any


def prediction_scores(cycles: list[dict[str, Any]]) -> dict[str, Any]:
    entries: dict[str, dict] = {}
    observations: dict[str, list[dict]] = defaultdict(list)
    for cycle in cycles:
        hypotheses = {
            h["instrument_id"]: h
            for h in (cycle["decision"].get("journal") or {}).get("hypotheses", [])
        }
        quotes = {q["instrument_id"]: q for q in cycle.get("quotes", [])}
        for quote in quotes.values():
            if quote["asset_class"] == "prediction":
                observations[quote["instrument_id"]].append(quote)
        runtime = (cycle.get("audit") or {}).get("runtime") or {}
        for fill in cycle.get("fills", []):
            instrument = fill["instrument_id"]
            hypothesis = hypotheses.get(instrument, {})
            if (
                fill["asset_class"] != "prediction"
                or fill["side"] != "buy"
                or instrument in entries
                or hypothesis.get("p_win") is None
                or instrument not in quotes
            ):
                continue
            entries[instrument] = dict(
                instrument_id=instrument,
                playbook_id=hypothesis.get("playbook_id") or "unassigned",
                source_revision=runtime.get("source_revision") or "unknown",
                entered_at=cycle["as_of"],
                p_win=str(hypothesis["p_win"]),
                entry_market_price=str(quotes[instrument]["price"]),
            )
    rows = []
    for instrument, entry in entries.items():
        later = sorted(
            (q for q in observations[instrument] if q["observed_at"] >= entry["entered_at"]),
            key=lambda q: q["observed_at"],
        )
        settlement = next((q for q in later if q.get("status") == "settled"), None)
        preclose = [
            q
            for q in later
            if q.get("status", "open") == "open"
            and q["observed_at"] > entry["entered_at"]
            and settlement
            and q["observed_at"] < settlement["observed_at"]
        ]
        p, market = Decimal(entry["p_win"]), Decimal(entry["entry_market_price"])
        outcome = Decimal(settlement["price"]) if settlement else None
        rows.append(
            {
                **entry,
                "outcome": str(outcome) if outcome is not None else None,
                "model_brier": str((p - outcome) ** 2) if outcome is not None else None,
                "market_brier": str((market - outcome) ** 2) if outcome is not None else None,
                "brier_improvement": str((market - outcome) ** 2 - (p - outcome) ** 2)
                if outcome is not None
                else None,
                "sampled_clv": str(Decimal(preclose[-1]["price"]) - market) if preclose else None,
                "clv_observed_at": preclose[-1]["observed_at"] if preclose else None,
            }
        )

    def aggregate(group):
        result = {"contracts": len(group)}
        for metric in ("model_brier", "market_brier", "brier_improvement", "sampled_clv"):
            values = [Decimal(r[metric]) for r in group if r[metric] is not None]
            result[metric + "_count"] = len(values)
            result[metric] = str(sum(values) / len(values)) if values else None
        return result

    cuts = {}
    for key in ("playbook_id", "source_revision"):
        groups: dict[str, list] = defaultdict(list)
        for row in rows:
            groups[row[key]].append(row)
        cuts[key] = [{key: name, **aggregate(group)} for name, group in sorted(groups.items())]
    return {
        "summary": aggregate(rows),
        "cuts": cuts,
        "contracts": rows,
        "interpretation": "One first funded forecast per contract. Lower Brier is better; "
        "positive Brier improvement beats the entry market forecast. "
        "Positive sampled CLV means the purchased outcome rose before settlement. "
        "CLV is the last recorded pre-settlement mark, not guaranteed closing price. "
        "Unresolved contracts remain unscored; correlated events and selection "
        "bias limit conclusions about LLM alpha.",
    }
