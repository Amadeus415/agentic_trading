"""Charts for results/results.json. One function per chart, all in one visual style.

White background so the PNGs read in GitHub's dark mode, one teal accent, neutral
inks, burnt orange only for a baseline or a second category. Titles state the
finding; subtitles state the setup and the sample size.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.ticker import FuncFormatter, PercentFormatter  # noqa: E402

ACCENT = "#087F90"
OTHER = "#C2410C"
INK = "#18202B"
MUTED = "#5B6B7D"
RULE = "#D5DDE3"
LIGHT = "#9AA8B5"
CLASS_COLORS = {"prediction": ACCENT, "stock": OTHER, "crypto": LIGHT}
CLASS_NAMES = {"prediction": "Prediction contracts", "stock": "Stocks", "crypto": "Crypto"}
WIDTH = 8.0
DPI = 200


def _font() -> str:
    installed = {font.name for font in font_manager.fontManager.ttflist}
    for name in ("Inter", "Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"):
        if name in installed:
            return name
    return "sans-serif"


plt.rcParams.update(
    {
        "font.family": _font(),
        "font.size": 9,
        "axes.edgecolor": RULE,
        "axes.labelcolor": MUTED,
        "axes.titlecolor": INK,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "xtick.labelsize": 8.5,
        "ytick.labelsize": 8.5,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.spines.left": False,
        "axes.grid": False,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "savefig.facecolor": "white",
        "lines.solid_capstyle": "round",
        "lines.solid_joinstyle": "round",
        "text.parse_math": False,
    }
)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _money(value: float, signed: bool = False) -> str:
    sign = ("+" if value > 0 else "−" if value < 0 else "") if signed else ""
    if not signed and value < 0:
        sign = "−"
    return f"{sign}${abs(value):,.2f}"


def _pct(value: float, digits: int = 1, signed: bool = False) -> str:
    sign = ("+" if value > 0 else "−" if value < 0 else "") if signed else ""
    if not signed and value < 0:
        sign = "−"
    return f"{sign}{abs(value) * 100:.{digits}f}%"


def _dollars(value: float, _: object = None) -> str:
    return f"{'−' if value < 0 else ''}${abs(value):,.0f}"


def _day(value: str) -> str:
    stamp = _dt(value)
    return f"{stamp:%b} {stamp.day}"


def _figure(height: float, title: str, subtitle: str, footer: str) -> plt.Figure:
    fig = plt.figure(figsize=(WIDTH, height), dpi=DPI)
    top = 1 - 0.32 / height
    fig.text(0.04, top, title, fontsize=13.5, fontweight="semibold", color=INK, va="top")
    fig.text(
        0.04, top - 0.36 / height, subtitle, fontsize=8.8, color=MUTED, va="top", linespacing=1.45
    )
    fig.text(0.04, 0.18 / height, footer, fontsize=7.2, color=LIGHT, va="bottom")
    return fig


def _grid(ax: plt.Axes, axis: str = "y") -> None:
    ax.grid(axis=axis, color=RULE, linewidth=0.6)
    ax.set_axisbelow(True)
    ax.tick_params(length=0, pad=4)
    ax.spines["bottom"].set_color(RULE)


def _save(fig: plt.Figure, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    return path


def _footer(results: dict[str, Any]) -> str:
    return (
        f"Paper money only. Ledger as of {results['as_of'][:10]}. "
        "Source: results/results.json, built by `make results`."
    )


def short_question(question: str | None, instrument_id: str) -> str:
    """A chart-sized label for a Polymarket question and the outcome token held."""
    side = instrument_id.rsplit(":", 1)[-1]
    text = (question or instrument_id).strip().rstrip("?")
    replacements = [
        (r"^Will the price of Bitcoin be ", "BTC "),
        (r"^Will the price of Ethereum be ", "ETH "),
        (r"^Will Bitcoin ", "BTC "),
        (r"^Will the Fed increase interest rates by 25 bps after the ", "Fed hikes 25 bp at "),
        (
            r"^Will any presidential candidate win outright in the first round of the Brazil election",
            "Brazil: outright first-round winner",
        ),
        (r"^Will ", ""),
        (r"\babove\b", ">"),
        (r"\$(\d{1,3}),000\b", r"$\1k"),
        (r"\bSeptember\b", "Sep"),
        (r"\bAugust\b", "Aug"),
        (r"\bOctober\b", "Oct"),
        (r" 2026 meeting", " meeting"),
    ]
    for pattern, repl in replacements:
        text = re.sub(pattern, repl, text)
    if len(text) > 44:
        text = text[:43].rstrip() + "…"
    return f"{text} · {side}"


def _instrument_label(trip: dict[str, Any]) -> str:
    instrument = trip["instrument_id"]
    if instrument.startswith("polymarket:"):
        return short_question(trip.get("question"), instrument)
    side = "short" if trip["side"] == "short" else "long"
    return f"{instrument} ({side})"


# --------------------------------------------------------------------------- charts


def equity_chart(results: dict[str, Any], path: Path) -> Path:
    v1, v2 = results["funds"]["v1"], results["funds"].get("v2", {})
    equity = v1["equity"]
    points = equity["points"]
    times = [_dt(p["at"]) for p in points]
    navs = [p["nav"] for p in points]
    dds = [-p["drawdown"] for p in points]
    spy = equity.get("spy")
    title = (
        f"v1 ended {_pct(equity['return'], signed=True)} on $1,000 of paper money, "
        f"after a {_pct(equity['max_drawdown'], 0)} drawdown"
    )
    subtitle = (
        f"Nightshift v1 (stocks, crypto, Polymarket): NAV after each of {v1['cycles']} recorded cycles, "
        f"{_day(equity['first_cycle_at'])} – {_day(equity['last_cycle_at'])}, 2026.\n"
        f"SPY total return over the same window: {_pct(spy['total_return'], 2, signed=True)}. "
        "v2 (prediction markets only) restarted at $1,000 on Oct 17."
        if spy
        else "SPY benchmark unavailable."
    )
    fig = _figure(5.4, title, subtitle, _footer(results))
    ax = fig.add_axes([0.085, 0.36, 0.76, 0.44])
    dd = fig.add_axes([0.085, 0.12, 0.76, 0.17], sharex=ax)

    ax.axhline(1000, color=RULE, linewidth=0.9, zorder=1)
    if spy:
        spy_times = [
            datetime.fromisoformat(row["date"]).replace(hour=20, tzinfo=UTC)
            for row in spy["series"]
        ]
        ax.plot(spy_times, [r["nav"] for r in spy["series"]], color=OTHER, linewidth=1.2, zorder=2)
        label_at = len(spy_times) * 2 // 3
        ax.text(
            spy_times[label_at],
            spy["series"][label_at]["nav"] + 9,
            f"SPY, total return ({_pct(spy['total_return'], 2, signed=True)})",
            color=INK,
            fontsize=8.2,
            va="bottom",
            ha="center",
        )
    gap_start, gap_end = max(
        zip(times, times[1:], strict=False), key=lambda pair: pair[1] - pair[0]
    )
    if gap_end - gap_start > timedelta(days=3):
        for axis in (ax, dd):
            axis.axvspan(gap_start, gap_end, color=RULE, alpha=0.35, linewidth=0, zorder=0)
        ax.text(
            gap_start + (gap_end - gap_start) / 2,
            1215,
            "no cycles ran",
            fontsize=7.6,
            color=MUTED,
            ha="center",
            va="top",
        )
    ax.plot(times, navs, color=ACCENT, linewidth=1.7, drawstyle="steps-post", zorder=3)
    ax.text(
        times[-1] + timedelta(hours=10),
        navs[-1] + 6,
        f"v1 fund {_money(navs[-1])[:-3]}",
        color=INK,
        fontsize=8.5,
        va="bottom",
        fontweight="semibold",
    )
    if v2.get("created_at"):
        start = _dt(v2["created_at"])
        ax.scatter([start], [1000], s=34, color="white", edgecolor=ACCENT, linewidth=1.6, zorder=4)
        ax.text(
            start, 1000 + 14, "v2 starts\n$1,000", color=INK, fontsize=8, ha="center", va="bottom"
        )

    peak_at, peak = _dt(equity["peak_at"]), equity["peak_nav"]
    trough_at, trough = _dt(equity["max_drawdown_trough_at"]), equity["max_drawdown_trough_nav"]
    notes = [
        (
            peak_at,
            peak,
            "Peak $1,189: a BTC $80k longshot\nmarked up before it expired at $0",
            (10, -2),
            "left",
        ),
        (
            trough_at,
            trough,
            "Low $863, then a BTC $82k\nYES settles at $1 (+$105)",
            (12, -6),
            "left",
        ),
    ]
    for at, value, text, offset, ha in notes:
        ax.annotate(
            text,
            (at, value),
            xytext=offset,
            textcoords="offset points",
            fontsize=7.6,
            color=MUTED,
            ha=ha,
            va="top" if offset[1] < 0 else "bottom",
            linespacing=1.3,
        )
        ax.scatter([at], [value], s=16, color=ACCENT, edgecolor="white", linewidth=1.2, zorder=5)
    ax.set_ylim(820, 1230)
    ax.yaxis.set_major_formatter(FuncFormatter(_dollars))
    _grid(ax)
    ax.tick_params(labelbottom=False)
    ax.spines["bottom"].set_visible(False)

    dd.fill_between(times, dds, 0, step="post", color=MUTED, alpha=0.14, linewidth=0)
    dd.plot(times, dds, color=MUTED, linewidth=1.0, drawstyle="steps-post")
    dd.set_ylim(-0.32, 0.0)
    dd.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    dd.set_yticks([0, -0.15, -0.30])
    dd.text(
        trough_at + timedelta(hours=14),
        -equity["max_drawdown"],
        f"max drawdown {_pct(equity['max_drawdown'])}",
        fontsize=7.6,
        color=MUTED,
        va="center",
    )
    dd.text(0.0, 1.06, "Drawdown from peak", transform=dd.transAxes, fontsize=7.6, color=MUTED)
    _grid(dd)
    dd.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO))
    dd.xaxis.set_major_formatter(mdates.DateFormatter("%b %-d"))
    dd.set_xlim(
        times[0] - timedelta(days=1),
        _dt(v2.get("created_at") or points[-1]["at"]) + timedelta(days=2),
    )
    return _save(fig, path)


def asset_class_chart(results: dict[str, Any], path: Path) -> Path:
    trades = results["funds"]["v1"]["trades"]
    rows = sorted(trades["by_asset_class"].items(), key=lambda kv: kv[1]["realized_pnl_after_cost"])
    title = "Prediction contracts made the money in v1; stocks lost it"
    subtitle = (
        f"Realized P&L after fees by asset class, {trades['closed']} closed v1 round trips, "
        "Aug 22 – Oct 5, 2026. Small samples: read as direction, not proof."
    )
    fig = _figure(3.4, title, subtitle, _footer(results))
    ax = fig.add_axes([0.30, 0.16, 0.58, 0.58])
    for index, (name, row) in enumerate(rows):
        value = row["realized_pnl_after_cost"]
        ax.barh(index, value, height=0.42, color=CLASS_COLORS.get(name, LIGHT))
        ax.text(
            value + (2.5 if value >= 0 else -2.5),
            index,
            _money(value, signed=True),
            va="center",
            ha="left" if value >= 0 else "right",
            fontsize=9,
            color=INK,
            fontweight="semibold",
        )
        ax.text(
            -0.03,
            index,
            f"{CLASS_NAMES.get(name, name)}\n{row['closed']} trades, {row['wins']} won",
            transform=ax.get_yaxis_transform(),
            ha="right",
            va="center",
            fontsize=8.8,
            color=INK,
            linespacing=1.35,
        )
    ax.axvline(0, color=INK, linewidth=0.8)
    limit = max(abs(r["realized_pnl_after_cost"]) for _, r in rows) * 1.45
    ax.set_xlim(-limit, limit)
    ax.set_yticks([])
    ax.xaxis.set_major_formatter(FuncFormatter(_dollars))
    _grid(ax, "x")
    return _save(fig, path)


def round_trip_chart(results: dict[str, Any], path: Path) -> Path:
    v1 = results["funds"]["v1"]
    trips = v1["trades"]["round_trips"]
    big = sorted(trips, key=lambda t: abs(t["realized_pnl_after_cost"]), reverse=True)[:3]
    swing = sum(abs(t["realized_pnl_after_cost"]) for t in big)
    rest = sum(t["realized_pnl_after_cost"] for t in trips if t not in big)
    title = (
        f"Three trades swung ${swing:,.0f}; the other {len(trips) - 3} netted "
        f"{_money(rest, signed=True)[:-3]}"
    )
    subtitle = (
        f"Every closed v1 round trip ({len(trips)}), realized P&L after fees, sorted. "
        "Two of the three big ones were BTC price-threshold bets,\n"
        "which v2 keeps out of LLM research."
    )
    height = 1.6 + 0.24 * len(trips)
    fig = _figure(height, title, subtitle, _footer(results))
    top = 1 - 1.25 / height
    ax = fig.add_axes([0.40, 0.75 / height, 0.50, top - 0.75 / height])
    for index, trip in enumerate(trips):
        value = trip["realized_pnl_after_cost"]
        ax.barh(index, value, height=0.62, color=CLASS_COLORS.get(trip["asset_class"], LIGHT))
        ax.text(
            value + (2 if value >= 0 else -2),
            index,
            _money(value, signed=True),
            va="center",
            ha="left" if value >= 0 else "right",
            fontsize=7.4,
            color=INK,
        )
        ax.text(
            -0.02,
            index,
            _instrument_label(trip),
            transform=ax.get_yaxis_transform(),
            ha="right",
            va="center",
            fontsize=7.6,
            color=INK,
        )
    ax.axvline(0, color=INK, linewidth=0.8)
    ax.set_ylim(-0.7, len(trips) - 0.3)
    ax.set_xlim(-215, 160)
    ax.set_yticks([])
    ax.xaxis.set_major_formatter(FuncFormatter(_dollars))
    _grid(ax, "x")
    for x, name in zip((0.40, 0.585, 0.68), ("prediction", "stock", "crypto"), strict=True):
        fig.patches.append(
            plt.Rectangle(
                (x, top + 0.12 / height),
                0.012,
                0.09 / height,
                transform=fig.transFigure,
                color=CLASS_COLORS[name],
            )
        )
        fig.text(
            x + 0.018, top + 0.165 / height, CLASS_NAMES[name], fontsize=8, color=INK, va="center"
        )
    return _save(fig, path)


def gate_chart(results: dict[str, Any], path: Path) -> Path:
    gate = results["funds"]["v1"]["gate"]
    risk = gate["risk_checks"]
    title = (
        f"Python sized {gate['sized']} of {gate['entry_candidates']} trade proposals; "
        f"{_pct(gate['blocked_share'], 0)} never reached the book"
    )
    subtitle = (
        f"v1 research cycles from {_day(gate['python_sizing_since'])} (when code took over sizing) "
        f"to Oct 5, 2026: {gate['cycles_with_sizing']} cycles.\n"
        f"Separately, {risk['evaluated']} limit checks (exposure, drawdown, cash, position size) ran on all "
        f"{gate['research_cycles'] + gate['monitor_cycles']} cycles with {risk['failed']} breaches, "
        f"and {len(gate['rejected_cycles'])} whole packets were rejected."
    )
    fig = _figure(3.9, title, subtitle, _footer(results))
    funnel = fig.add_axes([0.25, 0.17, 0.30, 0.52])
    stages = [
        ("Hypotheses journaled", gate["hypotheses_journaled"]),
        ("Trade proposals sent\nto Python sizing", gate["entry_candidates"]),
        ("Sized and filled", gate["sized"]),
    ]
    for index, (label, value) in enumerate(stages):
        y = len(stages) - 1 - index
        funnel.barh(y, value, height=0.5, color=ACCENT)
        funnel.text(
            value + 5, y, f"{value}", va="center", fontsize=9, color=INK, fontweight="semibold"
        )
        funnel.text(
            -0.04,
            y,
            label,
            transform=funnel.get_yaxis_transform(),
            ha="right",
            va="center",
            fontsize=8.6,
            color=INK,
            linespacing=1.3,
        )
    funnel.set_xlim(0, max(v for _, v in stages) * 1.18)
    funnel.set_yticks([])
    funnel.set_xticks([])
    funnel.spines["bottom"].set_visible(False)
    funnel.text(
        0,
        1.04,
        "What happened to the agent's ideas",
        transform=funnel.transAxes,
        fontsize=8.4,
        color=MUTED,
    )

    blocked = fig.add_axes([0.72, 0.17, 0.20, 0.52])
    labels = {
        "below_edge_threshold": "Expected return after\nfees below the minimum",
        "market_closed_queued": "Stock market closed,\norder dropped",
    }
    reasons = [(k, v) for k, v in gate["reasons"].items() if k != "sized"]
    for index, (reason, value) in enumerate(reasons):
        y = len(reasons) - 1 - index
        blocked.barh(y, value, height=0.42, color=OTHER)
        blocked.text(
            value + 1.5, y, f"{value}", va="center", fontsize=9, color=INK, fontweight="semibold"
        )
        blocked.text(
            -0.05,
            y,
            labels.get(reason, reason),
            transform=blocked.get_yaxis_transform(),
            ha="right",
            va="center",
            fontsize=8.2,
            color=INK,
            linespacing=1.3,
        )
    blocked.set_xlim(0, max(v for _, v in reasons) * 1.3)
    blocked.set_ylim(-0.7, len(reasons) - 0.3)
    blocked.set_yticks([])
    blocked.set_xticks([])
    blocked.spines["bottom"].set_visible(False)
    blocked.text(
        -0.95,
        1.04,
        f"Why {gate['blocked']} proposals were blocked",
        transform=blocked.transAxes,
        fontsize=8.4,
        color=MUTED,
    )
    return _save(fig, path)


def forecast_chart(results: dict[str, Any], path: Path) -> Path:
    forecasts = results["funds"]["v1"]["forecasts"]
    summary = forecasts["summary"]
    rows = [c for c in forecasts["contracts"] if c["outcome"] is not None]
    rows.sort(key=lambda c: c["forecast_at"])
    without = summary["without_largest_gain"]
    agent_wins = summary["agent_brier"] < summary["market_brier"]
    flips = (
        without["market_brier"] is not None
        and (without["agent_brier"] < without["market_brier"]) != agent_wins
    )
    title = f"Agent {summary['agent_brier']:.3f} vs market {summary['market_brier']:.3f} Brier" + (
        ", and one BTC contract carries the gap" if flips else f" on {len(rows)} resolved contracts"
    )
    subtitle = (
        f"{len(rows)} resolved Polymarket contracts: the agent's first settlement probability "
        "(p_win) vs the market price at that moment,\n"
        f"{_day(rows[0]['forecast_at'])} – {_day(rows[-1]['forecast_at'])}, 2026. Lower Brier is "
        f"better. Agent closer on {summary['agent_closer']}, market closer on "
        f"{summary['market_closer']}, {summary['ties']} ties.\n"
        f"Without the BTC $82k contract: agent {without['agent_brier']:.3f}, market "
        f"{without['market_brier']:.3f}. n is far too small to claim an edge."
    )
    height = 2.5 + 0.3 * len(rows)
    fig = _figure(height, title, subtitle, _footer(results))
    top = 1 - 1.75 / height
    ax = fig.add_axes([0.38, 0.85 / height, 0.47, top - 0.85 / height])
    for index, row in enumerate(rows):
        y = len(rows) - 1 - index
        ax.plot([row["market_p"], row["agent_p"]], [y, y], color=RULE, linewidth=2.2, zorder=1)
        ax.scatter(
            [row["market_p"]], [y], s=34, color=OTHER, edgecolor="white", linewidth=1.2, zorder=3
        )
        ax.scatter(
            [row["agent_p"]], [y], s=34, color=ACCENT, edgecolor="white", linewidth=1.2, zorder=4
        )
        ax.text(
            -0.02,
            y,
            short_question(row["question"], row["instrument_id"]),
            transform=ax.get_yaxis_transform(),
            ha="right",
            va="center",
            fontsize=7.8,
            color=INK,
        )
        ax.text(
            1.03,
            y,
            f"paid ${row['outcome']:.0f}",
            transform=ax.get_yaxis_transform(),
            ha="left",
            va="center",
            fontsize=7.8,
            color=INK,
        )
    ax.set_xlim(-0.02, 1.02)
    ax.set_ylim(-0.6, len(rows) - 0.4)
    ax.xaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    ax.set_yticks([])
    ax.set_xlabel("Probability that this outcome token pays $1", fontsize=8.2)
    _grid(ax, "x")
    legend_y = top + 0.17 / height
    for offset, (color, label) in enumerate(((ACCENT, "Agent p_win"), (OTHER, "Market price"))):
        x = 0.38 + offset * 0.16
        fig.lines.append(
            plt.Line2D(
                [x + 0.006],
                [legend_y],
                marker="o",
                markersize=5.5,
                color=color,
                transform=fig.transFigure,
                linestyle="none",
            )
        )
        fig.text(x + 0.018, legend_y, label, fontsize=8, color=INK, va="center")
    return _save(fig, path)


def calibration_chart(results: dict[str, Any], path: Path) -> Path:
    cal = results["funds"]["v1"]["calibration"]
    classes = ", ".join(f"{n} {name}" for name, n in cal["by_asset_class"].items())
    title = (
        f"The agent's theses said {_pct(cal['mean_stated'], 0)} on average "
        f"and won {_pct(cal['win_rate'], 0)} of the time"
    )
    subtitle = (
        f"{cal['theses']} independent v1 theses ({classes}): first statement of each, "
        f"from {cal['journaled_hypotheses']} journal entries.\n"
        "A win is the target hit, or a profitable close, before the stop or deadline. "
        f"Brier {cal['brier']:.3f}; always saying 50% would score 0.250."
    )
    fig = _figure(4.6, title, subtitle, _footer(results))
    ax = fig.add_axes([0.12, 0.17, 0.5, 0.58])
    ax.plot([0, 1], [0, 1], color=RULE, linewidth=1.0, zorder=1)
    ax.text(0.78, 0.83, "perfectly\ncalibrated", color=MUTED, fontsize=7.6, rotation=0, ha="left")
    xs = [b["mean_forecast"] for b in cal["bins"]]
    ys = [b["hit_rate"] for b in cal["bins"]]
    sizes = [18 + 9 * b["count"] for b in cal["bins"]]
    ax.scatter(
        xs, ys, s=sizes, color=ACCENT, edgecolor="white", linewidth=1.4, zorder=3, alpha=0.95
    )
    for b in cal["bins"]:
        ax.annotate(
            f"n={b['count']}",
            (b["mean_forecast"], b["hit_rate"]),
            xytext=(0, 9 + b["count"] * 0.25),
            textcoords="offset points",
            ha="center",
            fontsize=7.4,
            color=INK,
        )
    ax.set_xlim(0, 1)
    ax.set_ylim(-0.04, 1.04)
    ax.xaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    ax.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    ax.set_xlabel("Stated probability (bin average)", fontsize=8.2)
    ax.set_ylabel("Theses that won", fontsize=8.2)
    _grid(ax, "both")
    busiest = max(cal["bins"], key=lambda b: b["count"])
    fig.text(
        0.67,
        0.62,
        f"The busiest bin: {busiest['count']} theses\n"
        f"stated {_pct(busiest['mean_forecast'], 0)} and won {_pct(busiest['hit_rate'], 0)}.\n\n"
        "That gap is why v2 scores\nsettlement probabilities against\nthe market price, not against\nthe agent's own targets.",
        fontsize=8.4,
        color=INK,
        va="top",
        linespacing=1.45,
    )
    return _save(fig, path)


def exposure_chart(results: dict[str, Any], path: Path) -> Path:
    exposure = results["funds"]["v1"]["exposure"]
    series = exposure["series"]
    times = [_dt(p["at"]) for p in series]
    gross = [p["gross_exposure"] for p in series]
    gaps = sorted(zip(times, times[1:], strict=False), key=lambda pair: pair[1] - pair[0])[-1]
    title = (
        f"v1 sat flat {_pct(exposure['share_of_time_flat'], 0)} of the time; "
        f"gross exposure averaged {_pct(exposure['time_weighted_gross_exposure'], 0)} of NAV"
    )
    subtitle = (
        "Gross exposure as a share of NAV after each recorded cycle, time-weighted. "
        f"Peak {_pct(exposure['max_gross_exposure'], 0)}.\n"
        f"No cycles ran between {gaps[0]:%b} {gaps[0].day} and {gaps[1]:%b} {gaps[1].day}."
    )
    fig = _figure(3.6, title, subtitle, _footer(results))
    ax = fig.add_axes([0.085, 0.15, 0.86, 0.54])
    if gaps[1] - gaps[0] > timedelta(days=3):
        ax.axvspan(gaps[0], gaps[1], color=RULE, alpha=0.35, linewidth=0, zorder=0)
        ax.text(
            gaps[0] + (gaps[1] - gaps[0]) / 2,
            1.33,
            "no cycles ran",
            fontsize=7.6,
            color=MUTED,
            ha="center",
            va="top",
        )
    ax.fill_between(times, gross, 0, step="post", color=ACCENT, alpha=0.12, linewidth=0)
    ax.plot(times, gross, color=ACCENT, linewidth=1.5, drawstyle="steps-post")
    ax.axhline(1.0, color=RULE, linewidth=0.9)
    ax.text(times[0], 1.03, "100% of NAV", fontsize=7.6, color=MUTED, va="bottom")
    ax.set_ylim(0, 1.4)
    ax.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %-d"))
    _grid(ax)
    return _save(fig, path)


def lineage_chart(results: dict[str, Any], path: Path) -> Path:
    segments = results["funds"]["v1"]["lineage"]
    moves = sorted((abs(s["nav_change"]) for s in segments), reverse=True)
    share = sum(moves[:3]) / sum(moves) if sum(moves) else 0
    title = f"Three code revisions account for {_pct(share, 0)} of v1's NAV movement"
    subtitle = (
        "NAV change while each revision was live. v1 cycles did not record their commit, so the "
        "revision is inferred\nfrom deploy times (history/deployments.json). A timeline of which code "
        "ran, not proof that a change helped."
    )
    fig = _figure(3.9, title, subtitle, _footer(results))
    ax = fig.add_axes([0.085, 0.22, 0.86, 0.50])
    for index, segment in enumerate(segments):
        value = segment["nav_change"]
        ax.bar(index, value, width=0.5, color=ACCENT if value >= 0 else OTHER)
        if abs(value) >= 1:
            ax.text(
                index,
                value + (4 if value >= 0 else -4),
                _money(value, signed=True)[:-3],
                ha="center",
                va="bottom" if value >= 0 else "top",
                fontsize=7.6,
                color=INK,
            )
    ax.axhline(0, color=INK, linewidth=0.8)
    ax.set_xticks(
        range(len(segments)),
        [
            f"{s['revision'][:7]}\n{_day(s['started_at'])}\n{s['cycles']} cycle{'' if s['cycles'] == 1 else 's'}"
            for s in segments
        ],
        fontsize=7.2,
    )
    ax.set_ylim(-175, 140)
    ax.yaxis.set_major_formatter(FuncFormatter(_dollars))
    _grid(ax)
    return _save(fig, path)


CHARTS = {
    "v1-equity.png": equity_chart,
    "v1-pnl-by-asset-class.png": asset_class_chart,
    "v1-round-trips.png": round_trip_chart,
    "v1-gates.png": gate_chart,
    "v1-agent-vs-market.png": forecast_chart,
    "v1-calibration.png": calibration_chart,
    "v1-exposure.png": exposure_chart,
    "v1-lineage.png": lineage_chart,
}


def render_all(results: dict[str, Any], directory: Path) -> list[Path]:
    if "v1" not in results["funds"] or "equity" not in results["funds"]["v1"]:
        return []
    return [chart(results, directory / name) for name, chart in CHARTS.items()]
