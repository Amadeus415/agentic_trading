from __future__ import annotations

import html
import math
from datetime import datetime
from decimal import ROUND_FLOOR, Decimal
from pathlib import Path
from typing import Any

from edgecraft.paper_fund import FundMandate, FundState, PaperFundLedger

# GitHub-safe palette. The line stays indigo so a later drawdown does not
# repaint the whole history as a loss.
_BG = "#0b0f17"
_PANEL = "#121826"
_PANEL_STROKE = "#1e293b"
_GRID = "#243044"
_MUTED = "#8b97ab"
_LABEL = "#c5cddb"
_INK = "#f8fafc"
_FUND = "#818cf8"
_FUND_SOFT = "#6366f1"
_UP = "#34d399"
_DOWN = "#fb7185"
_START = "#94a3b8"
_MONO = "ui-monospace,SFMono-Regular,Menlo,monospace"
_SANS = "ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif"


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
    series = _series(initial, state, history)
    navs = [point["nav"] for point in series]
    times = [point["time"] for point in series]
    pnl = state.nav - initial
    return_pct = (state.nav / initial - 1) * 100
    fills = sum(int(row["fill_count"]) for row in history)
    trades = sum(row["action"] == "trade" for row in history)
    positive = pnl >= 0
    pnl_color = _UP if positive else _DOWN
    delta_sign = "+" if positive else "-"
    open_count = sum(1 for position in state.positions if position.quantity != 0)
    peak = max(navs)
    updated = state.as_of.strftime("%Y-%m-%d %H:%M UTC")
    book_label = (
        "All cash"
        if open_count == 0
        else (f"{open_count} position" if open_count == 1 else f"{open_count} positions")
    )

    chart_x, chart_y, chart_w, chart_h = 108, 278, 1016, 248
    low, high = _bounds(navs, initial)
    ticks = _nice_ticks(low, high)
    xs = _xs(times, chart_x, chart_w)
    ys = [_y(value, chart_y, chart_h, low, high) for value in navs]
    start_y = _y(initial, chart_y, chart_h, low, high)
    nav_points = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys, strict=True))
    area_points = (
        f"{xs[0]:.1f},{chart_y + chart_h:.1f} {nav_points} {xs[-1]:.1f},{chart_y + chart_h:.1f}"
    )
    grid = _grid(chart_x, chart_y, chart_w, chart_h, ticks, low, high)
    date_labels = _date_labels(times, xs)
    dots = _dots(series, xs, ys)
    peak_mark = _peak_callout(xs, ys, navs, state.nav)
    last_x, last_y = xs[-1], ys[-1]

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="680" viewBox="0 0 1200 680" role="img" aria-labelledby="title desc">
<title id="title">Edgecraft paper fund value</title>
<desc id="desc">Verified paper-fund value is {_money(state.nav)}, {delta_sign}{abs(return_pct):.2f}% from a {_money(initial)} start across {len(history)} sessions. The dashed line is starting capital.</desc>
<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop stop-color="{_BG}"/><stop offset="1" stop-color="#111827"/></linearGradient>
  <linearGradient id="area" x1="0" y1="0" x2="0" y2="1"><stop stop-color="{_FUND_SOFT}" stop-opacity=".28"/><stop offset="1" stop-color="{_FUND_SOFT}" stop-opacity="0"/></linearGradient>
  <filter id="glow"><feGaussianBlur stdDeviation="4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
</defs>
<rect width="1200" height="680" rx="28" fill="url(#bg)"/>
<circle cx="1120" cy="40" r="170" fill="#4f46e5" opacity=".07"/>
<circle cx="80" cy="640" r="190" fill="#22d3ee" opacity=".05"/>
<g font-family="{_SANS}">
  <text x="48" y="52" fill="{_INK}" font-size="22" font-weight="800" letter-spacing="2.4">EDGECRAFT</text>
  <text x="48" y="76" fill="{_MUTED}" font-size="14">Autonomous paper fund · started with {_money(initial)}</text>
  <rect x="936" y="34" width="216" height="40" rx="20" fill="#102a25" stroke="#34d399" stroke-opacity=".45"/>
  <circle cx="960" cy="54" r="5" fill="{_UP}"/>
  <text x="974" y="59" fill="#a7f3d0" font-size="14" font-weight="700">100% FAKE MONEY</text>

  <text x="48" y="128" fill="{_MUTED}" font-size="12" font-weight="700" letter-spacing="1.6">FUND VALUE</text>
  <text x="48" y="176" fill="{_INK}" font-size="52" font-weight="800" font-family="{_MONO}">{_money(state.nav)}</text>
  <text x="48" y="206" fill="{pnl_color}" font-size="18" font-weight="700" font-family="{_MONO}">{delta_sign}{_money(abs(pnl))}  ({delta_sign}{abs(return_pct):.2f}%) vs start</text>

  {_stat(520, 128, "PEAK", _money(peak))}
  {_stat(748, 128, "CASH", _money(state.cash))}
  {_stat(976, 128, "SESSIONS", str(len(history)))}

  <rect x="48" y="228" width="1104" height="368" rx="20" fill="{_PANEL}" stroke="{_PANEL_STROKE}"/>
  <text x="72" y="258" fill="{_INK}" font-size="15" font-weight="700">How the {_money(initial)} has moved</text>
  <circle cx="780" cy="253" r="4" fill="{_FUND}"/>
  <text x="792" y="258" fill="{_LABEL}" font-size="12">Fund value</text>
  <line x1="900" y1="253" x2="928" y2="253" stroke="{_START}" stroke-width="2" stroke-dasharray="5 5"/>
  <text x="936" y="258" fill="{_LABEL}" font-size="12">Started at {_money(initial)}</text>

  {grid}
  <line x1="{chart_x}" y1="{start_y:.1f}" x2="{chart_x + chart_w}" y2="{start_y:.1f}" stroke="{_START}" stroke-width="1.5" stroke-dasharray="5 6" opacity=".9"/>
  <polygon points="{area_points}" fill="url(#area)"/>
  <polyline points="{nav_points}" fill="none" stroke="{_FUND}" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round" filter="url(#glow)"/>
  {dots}
  {peak_mark}
  <circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="6" fill="{_FUND}" stroke="{_BG}" stroke-width="2"/>
  <text x="{last_x - 12:.1f}" y="{last_y + 20:.1f}" text-anchor="end" fill="{_LABEL}" font-size="12" font-family="{_MONO}">{_money(state.nav)}</text>
  {date_labels}

  <text x="48" y="630" fill="{_MUTED}" font-size="13">Goal: compound toward {_money(target)} over ten years · not a return promise</text>
  <text x="48" y="654" fill="#64748b" font-size="12">Updated {updated} · {html.escape(book_label)} · {trades} trades · {fills} fills · {html.escape(fund_id)}</text>
</g></svg>
'''


def _series(
    initial: Decimal, state: FundState, history: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if not history:
        point = {"time": state.as_of, "nav": initial, "action": "init"}
        return [point, {**point, "action": "end"}]
    points = [
        {
            "time": _parse_time(row["as_of"]),
            "nav": Decimal(row["nav"]),
            "action": row["action"],
        }
        for row in history
    ]
    if len(points) == 1:
        first = points[0]
        return [first, {**first, "action": "end"}]
    return points


def _stat(x: int, y: int, label: str, value: str) -> str:
    return (
        f'<text x="{x}" y="{y}" fill="{_MUTED}" font-size="11" font-weight="700" '
        f'letter-spacing="1.4">{html.escape(label)}</text>'
        f'<text x="{x}" y="{y + 32}" fill="{_INK}" font-size="18" font-weight="700" '
        f'font-family="{_MONO}">{html.escape(value)}</text>'
    )


def _bounds(navs: list[Decimal], initial: Decimal) -> tuple[Decimal, Decimal]:
    low = min([initial, *navs])
    high = max([initial, *navs])
    padding = max((high - low) * Decimal("0.16"), Decimal("25"))
    return low - padding, high + padding


def _nice_ticks(low: Decimal, high: Decimal, target: int = 4) -> list[Decimal]:
    span = max(high - low, Decimal("1"))
    raw = float(span / Decimal(target))
    magnitude = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    residual = raw / magnitude
    if residual <= 1:
        step_float = magnitude
    elif residual <= 2:
        step_float = 2 * magnitude
    elif residual <= 5:
        step_float = 5 * magnitude
    else:
        step_float = 10 * magnitude
    step = Decimal(str(step_float))
    start = (low / step).to_integral_value(rounding=ROUND_FLOOR) * step
    ticks: list[Decimal] = []
    value = start
    guard = 0
    while value <= high + (step / 2) and guard < 12:
        if value >= low - (step / 4):
            ticks.append(value)
        value += step
        guard += 1
    return ticks or [low, high]


def _xs(times: list[datetime], x: int, width: int) -> list[float]:
    start = times[0]
    span = (times[-1] - start).total_seconds()
    if span <= 0:
        step = width / max(len(times) - 1, 1)
        return [x + step * index for index in range(len(times))]
    return [x + width * (moment - start).total_seconds() / span for moment in times]


def _y(value: Decimal, y: int, height: int, low: Decimal, high: Decimal) -> float:
    span = high - low
    if span == 0:
        return y + height / 2
    return y + height - float((value - low) / span) * height


def _grid(
    x: int, y: int, width: int, height: int, ticks: list[Decimal], low: Decimal, high: Decimal
) -> str:
    parts = [
        f'<line x1="{x}" y1="{y + height}" x2="{x + width}" y2="{y + height}" stroke="{_GRID}"/>'
    ]
    for tick in ticks:
        tick_y = _y(tick, y, height, low, high)
        if tick_y < y + 8 or tick_y > y + height - 4:
            continue
        parts.append(
            f'<line x1="{x}" y1="{tick_y:.1f}" x2="{x + width}" y2="{tick_y:.1f}" '
            f'stroke="{_GRID}" stroke-dasharray="3 7" opacity=".85"/>'
        )
        parts.append(
            f'<text x="{x - 10}" y="{tick_y + 4:.1f}" text-anchor="end" fill="{_MUTED}" '
            f'font-size="11" font-family="{_MONO}">{_axis_money(tick)}</text>'
        )
    return "\n  ".join(parts)


def _date_labels(times: list[datetime], xs: list[float]) -> str:
    chosen = _pick_dates(times, xs)
    parts = []
    for index, (x, moment) in enumerate(chosen):
        anchor = "end" if index == len(chosen) - 1 else "start" if index == 0 else "middle"
        parts.append(
            f'<text x="{x:.1f}" y="548" text-anchor="{anchor}" fill="{_MUTED}" '
            f'font-size="12">{moment.strftime("%b %d")}</text>'
        )
    return "".join(parts)


def _pick_dates(times: list[datetime], xs: list[float]) -> list[tuple[float, datetime]]:
    last = len(times) - 1
    wanted = [0, last // 3, (2 * last) // 3, last]
    picked: list[tuple[float, datetime]] = []
    seen_days: set[str] = set()
    for index in wanted:
        label = times[index].strftime("%Y-%m-%d")
        if picked and (xs[index] - picked[-1][0] < 72 or label in seen_days):
            continue
        seen_days.add(label)
        picked.append((xs[index], times[index]))
    last_point = (xs[-1], times[-1])
    if not picked or picked[-1][1] != last_point[1]:
        if picked and last_point[0] - picked[-1][0] < 72:
            picked[-1] = last_point
        else:
            picked.append(last_point)
    return picked


def _dots(series: list[dict[str, Any]], xs: list[float], ys: list[float]) -> str:
    parts = []
    for point, x, y in zip(series, xs, ys, strict=True):
        radius = 3.4 if point["action"] == "trade" else 2.4
        fill = _FUND if point["action"] == "trade" else "#1e293b"
        stroke = _FUND
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="1.4"/>'
        )
    return "\n  ".join(parts)


def _peak_callout(
    xs: list[float],
    ys: list[float],
    navs: list[Decimal],
    current: Decimal,
) -> str:
    peak = max(navs)
    if peak <= current or len(navs) < 2:
        return ""
    index = navs.index(peak)
    x, y = xs[index], ys[index]
    label_x = x - 10
    label_y = max(y - 16, 286)
    return (
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="{_INK}"/>'
        f'<text x="{label_x:.1f}" y="{label_y:.1f}" text-anchor="end" fill="{_LABEL}" '
        f'font-size="11" font-family="{_MONO}">peak {_money(peak)}</text>'
    )


def _money(value: Decimal) -> str:
    return f"${value:,.2f}"


def _axis_money(value: Decimal) -> str:
    return f"${value:,.0f}"


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
