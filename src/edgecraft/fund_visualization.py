from __future__ import annotations

import html
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from edgecraft.paper_fund import FundMandate, FundState, PaperFundLedger


def render_fund_progress(
    ledger: PaperFundLedger,
    fund_id: str,
    mandate: FundMandate,
    output: Path,
) -> dict[str, Any]:
    """Render a deterministic, GitHub-safe SVG from the read-only fund ledger."""
    verification = ledger.verify(fund_id)
    if not verification.ok:
        raise ValueError("refusing to visualize an unverified paper-fund ledger")

    state = ledger.get_state(fund_id)
    history = ledger.state_history(fund_id)
    svg = _svg(fund_id, mandate, state, history)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(svg, encoding="utf-8")
    return {
        "ok": True,
        "paper_only": True,
        "fund_id": fund_id,
        "output": str(output),
        "cycle_count": len(history),
        "nav": str(state.nav),
        "as_of": state.as_of.isoformat().replace("+00:00", "Z"),
        "verification": {
            "chain_ok": verification.chain_ok,
            "accounting_ok": verification.accounting_ok,
        },
    }


def _svg(
    fund_id: str,
    mandate: FundMandate,
    state: FundState,
    history: list[dict[str, Any]],
) -> str:
    initial = mandate.initial_cash
    target = mandate.growth_objective.target_nav
    navs = [initial, *(Decimal(row["nav"]) for row in history)]
    gross = [Decimal("0"), *(Decimal(row["gross_exposure"]) for row in history)]
    dates = [state.as_of, *(_parse_time(row["as_of"]) for row in history)]
    start_time = min(dates)
    end_time = max(dates)
    pnl = state.nav - initial
    return_pct = (state.nav / initial - 1) * 100
    progress = max(Decimal("0"), min(Decimal("1"), (state.nav - initial) / (target - initial)))
    fills = sum(int(row["fill_count"]) for row in history)
    trades = sum(row["action"] == "trade" for row in history)

    chart_x, chart_y, chart_w, chart_h = 70, 297, 1060, 205
    all_values = navs + gross
    low = min(all_values)
    high = max(all_values)
    padding = max((high - low) * Decimal("0.14"), Decimal("10"))
    low -= padding
    high += padding
    nav_points = _points(navs, chart_x, chart_y, chart_w, chart_h, low, high)
    gross_points = _points(gross, chart_x, chart_y, chart_w, chart_h, low, high)
    area_points = (
        f"{chart_x},{chart_y + chart_h} {gross_points} {chart_x + chart_w},{chart_y + chart_h}"
    )
    positive = pnl >= 0
    accent = "#34d399" if positive else "#fb7185"
    sign = "+" if positive else ""
    updated = state.as_of.strftime("%Y-%m-%d %H:%M UTC")
    start_label = start_time.strftime("%b %d")
    end_label = end_time.strftime("%b %d")
    progress_width = int(1030 * float(progress))

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630" role="img" aria-labelledby="title desc">
<title id="title">Edgecraft paper fund progress</title>
<desc id="desc">Verified paper-fund NAV is {_money(state.nav)}, a {sign}{return_pct:.2f}% return across {len(history)} cycles.</desc>
<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#07111f"/><stop offset="1" stop-color="#101d35"/></linearGradient>
  <linearGradient id="area" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#60a5fa" stop-opacity=".28"/><stop offset="1" stop-color="#60a5fa" stop-opacity="0"/></linearGradient>
  <filter id="glow"><feGaussianBlur stdDeviation="5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
</defs>
<rect width="1200" height="630" rx="24" fill="url(#bg)"/>
<circle cx="1080" cy="45" r="180" fill="#2563eb" opacity=".08"/><circle cx="1040" cy="620" r="230" fill="#10b981" opacity=".06"/>
<g font-family="ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif">
  <text x="54" y="59" fill="#f8fafc" font-size="27" font-weight="800" letter-spacing="2">EDGECRAFT</text>
  <text x="54" y="86" fill="#94a3b8" font-size="14" letter-spacing="1.5">AUTONOMOUS PAPER FUND · VERIFIED LEDGER</text>
  <rect x="946" y="39" width="200" height="42" rx="21" fill="#102a25" stroke="#34d399" stroke-opacity=".45"/>
  <circle cx="970" cy="60" r="5" fill="#34d399"/><text x="984" y="66" fill="#a7f3d0" font-size="15" font-weight="700">100% FAKE MONEY</text>

  {_card(54, 119, 252, "NET ASSET VALUE", _money(state.nav), accent)}
  {_card(322, 119, 252, "ALL-TIME RETURN", f"{sign}{return_pct:.2f}%", accent)}
  {_card(590, 119, 252, "GROSS EXPOSURE", _money(state.gross_exposure), "#60a5fa")}
  {_card(858, 119, 288, "ACTIVITY", f"{len(history)} cycles · {fills} fills", "#c4b5fd")}

  <text x="54" y="276" fill="#f8fafc" font-size="17" font-weight="700">NAV AND DEPLOYED CAPITAL</text>
  <line x1="70" y1="502" x2="1130" y2="502" stroke="#334155"/>
  <line x1="70" y1="400" x2="1130" y2="400" stroke="#334155" stroke-dasharray="4 8" opacity=".7"/>
  <line x1="70" y1="297" x2="1130" y2="297" stroke="#334155" stroke-dasharray="4 8" opacity=".7"/>
  <polygon points="{area_points}" fill="url(#area)"/>
  <polyline points="{gross_points}" fill="none" stroke="#60a5fa" stroke-width="3" opacity=".75"/>
  <polyline points="{nav_points}" fill="none" stroke="{accent}" stroke-width="5" stroke-linecap="round" stroke-linejoin="round" filter="url(#glow)"/>
  <circle cx="1130" cy="{_last_y(navs, chart_y, chart_h, low, high):.1f}" r="6" fill="{accent}"/>
  <text x="70" y="525" fill="#64748b" font-size="12">{start_label}</text><text x="1093" y="525" fill="#64748b" font-size="12">{end_label}</text>
  <circle cx="886" cy="272" r="4" fill="{accent}"/><text x="898" y="277" fill="#94a3b8" font-size="12">NAV</text>
  <circle cx="958" cy="272" r="4" fill="#60a5fa"/><text x="970" y="277" fill="#94a3b8" font-size="12">GROSS EXPOSURE</text>

  <text x="54" y="564" fill="#94a3b8" font-size="13">100× OBJECTIVE</text>
  <text x="1146" y="564" text-anchor="end" fill="#cbd5e1" font-size="13">{_money(state.nav)} / {_money(target)}</text>
  <rect x="54" y="577" width="1030" height="12" rx="6" fill="#1e293b"/><rect x="54" y="577" width="{max(progress_width, 4)}" height="12" rx="6" fill="{accent}"/>
  <text x="1146" y="590" text-anchor="end" fill="#64748b" font-size="12">{float(progress) * 100:.3f}%</text>
  <text x="54" y="614" fill="#64748b" font-size="12">Updated {updated} · {trades} trade cycles · append-only accounting · {html.escape(fund_id)}</text>
</g></svg>'''


def _card(x: int, y: int, width: int, label: str, value: str, color: str) -> str:
    return f'''<rect x="{x}" y="{y}" width="{width}" height="105" rx="15" fill="#111f34" stroke="#26364e"/>
  <text x="{x + 20}" y="{y + 31}" fill="#7f91aa" font-size="12" font-weight="700" letter-spacing="1">{label}</text>
  <text x="{x + 20}" y="{y + 75}" fill="{color}" font-size="30" font-weight="800">{html.escape(value)}</text>'''


def _points(
    values: list[Decimal], x: int, y: int, width: int, height: int, low: Decimal, high: Decimal
) -> str:
    steps = max(len(values) - 1, 1)
    return " ".join(
        f"{x + width * index / steps:.1f},{_last_y([value], y, height, low, high):.1f}"
        for index, value in enumerate(values)
    )


def _last_y(values: list[Decimal], y: int, height: int, low: Decimal, high: Decimal) -> float:
    return y + height - float((values[-1] - low) / (high - low)) * height


def _money(value: Decimal) -> str:
    return f"${value:,.2f}"


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
