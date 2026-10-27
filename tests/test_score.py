from decimal import Decimal as D

from nightshift.score import (
    _edge,
    _skill,
    bootstrap,
    closed_positions,
    compare_arms,
    first_forecasts,
)


def ev(kind, at, **data):
    return {"kind": kind, "at": at, **data}


def test_closed_positions_count_fees_and_settlement():
    events = [
        ev(
            "fill",
            "t1",
            market="a",
            outcome="YES",
            event="E",
            side="buy",
            shares="100",
            cash="-42.5",
        ),
        ev("settle", "t2", market="a", outcome="YES", cash="100"),
        ev("fill", "t3", market="b", outcome="NO", event="F", side="buy", shares="10", cash="-6"),
        ev("fill", "t4", market="b", outcome="NO", event="F", side="sell", shares="10", cash="5"),
        ev("fill", "t5", market="c", outcome="NO", event="G", side="buy", shares="10", cash="-6"),
    ]
    closed = closed_positions(events)
    assert [(p["market"], p["pnl"], p["staked"], p["how"]) for p in closed] == [
        ("a", D("57.5"), D("42.5"), "settled"),
        ("b", D("-1"), D("6"), "sold"),
    ]


def test_first_forecast_per_market_wins_and_buys_count_as_forecasts():
    events = [
        ev("fill", "t1", market="a", outcome="NO", side="buy", p_yes="0.2", market_yes="0.3"),
        ev("forecast", "t2", market="a", p_yes="0.9", market_yes="0.3"),
        ev("forecast", "t3", market="b", p_yes="0.6", market_yes="0.5"),
    ]
    got = {f["market"]: f["p_yes"] for f in first_forecasts(events)}
    assert got == {"a": 0.2, "b": 0.6}


def test_skill_is_relative_to_the_market_brier():
    assert _skill([(0.04, 0.16), (0.04, 0.16)]) == 0.75
    assert _skill([(0.25, 0.25)]) == 0.0
    assert _edge([(100.0, 10.0), (100.0, -30.0)]) == -0.1


def test_bootstrap_resamples_whole_events_and_is_repeatable():
    clusters = {"e1": [(10.0, 5.0), (10.0, 5.0)], "e2": [(10.0, -5.0)], "e3": [(10.0, 1.0)]}
    first = bootstrap(clusters, _edge)
    assert first == bootstrap(clusters, _edge)
    assert first[0] < _edge([p for ps in clusters.values() for p in ps]) < first[1]
    assert bootstrap({"only": [(1.0, 1.0)]}, _edge) is None


def test_arms_compare_evolving_against_frozen_per_model():
    runs = [
        {"kind": "agent", "model": "m", "arm": "evolving", "return": 0.10, "skill": 0.1},
        {"kind": "agent", "model": "m", "arm": "evolving", "return": 0.00, "skill": 0.0},
        {"kind": "agent", "model": "m", "arm": "frozen", "return": -0.02, "skill": None},
        {"kind": "baseline", "model": None, "arm": None, "return": 0.5, "skill": None},
    ]
    (row,) = compare_arms(runs)
    assert row["evolving"]["mean_return"] == 0.05
    assert row["difference"] == 0.07
