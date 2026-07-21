from datetime import UTC, datetime
from decimal import Decimal

from edgecraft.execution_models import (
    MarketQuote,
    OpenOrderSnapshot,
    PortfolioSnapshot,
    ProposedOrder,
    RiskPolicy,
)
from edgecraft.risk import evaluate_orders

NOW = datetime(2026, 7, 19, 18, 0, tzinfo=UTC)


def _snapshot(**updates) -> PortfolioSnapshot:
    payload = {
        "account_id": "agentic-test",
        "agentic_allowed": True,
        "buying_power": 400,
        "portfolio_value": 400,
        "as_of": NOW,
    }
    payload.update(updates)
    return PortfolioSnapshot(**payload)


def _quote(**updates) -> MarketQuote:
    payload = {
        "symbol": "SPY",
        "last": 600,
        "bid": 599.9,
        "ask": 600.1,
        "as_of": NOW,
        "market_session": "regular",
        "average_daily_dollar_volume": Decimal("1000000000"),
    }
    payload.update(updates)
    return MarketQuote(**payload)


def _order(notional: float = 40) -> ProposedOrder:
    return ProposedOrder(
        order_key="spy-order",
        symbol="SPY",
        side="buy",
        notional=notional,
        expected_price=600,
        rationale="Exercise deterministic controls.",
        quote_as_of=NOW,
    )


def test_live_liquidity_drawdown_turnover_and_order_count_fail_closed():
    quote = _quote(
        bid=599,
        ask=601,
        market_session="after_hours",
        average_daily_dollar_volume=Decimal("1000"),
    )
    policy = RiskPolicy(
        trading_enabled=True,
        allowed_symbols=["SPY"],
        require_research_evidence=False,
        max_orders_per_day=1,
        max_spread_bps=5,
        max_order_adv_fraction=0.01,
        max_rolling_7d_turnover=0.10,
        max_drawdown_fraction=0.10,
    )

    decision = evaluate_orders(
        _snapshot(),
        [quote],
        [_order()],
        policy,
        strategy="plain_dca",
        mode="live",
        daily_placed_order_count=1,
        rolling_7d_placed_notional=25,
        portfolio_high_watermark=500,
        now=NOW,
    )

    assert not decision.approved_for_review
    for expected in (
        "market session",
        "spread",
        "max_order_adv_fraction",
        "drawdown",
        "turnover",
        "placed order(s)",
    ):
        assert any(expected in item for item in decision.violations)


def test_shadow_liquidity_issues_warn_without_granting_live_authority():
    decision = evaluate_orders(
        _snapshot(),
        [_quote(bid=None, ask=None, market_session="closed", average_daily_dollar_volume=None)],
        [_order()],
        RiskPolicy(allowed_symbols=["SPY"], require_research_evidence=False),
        strategy="plain_dca",
        mode="shadow",
        now=NOW,
    )

    assert decision.approved_for_review
    assert any("market session" in item for item in decision.warnings)
    assert any("bid/ask" in item for item in decision.warnings)
    assert any("average daily dollar volume" in item for item in decision.warnings)


def test_stale_account_open_order_and_group_concentration_are_blocked():
    stale = datetime(2026, 7, 19, 17, 0, tzinfo=UTC)
    snapshot = _snapshot(
        as_of=stale,
        open_orders=[
            OpenOrderSnapshot(
                order_id="existing-order",
                symbol="SPY",
                side="buy",
                notional=10,
                status="queued",
            )
        ],
    )
    policy = RiskPolicy(
        allowed_symbols=["SPY"],
        require_research_evidence=False,
        max_order_notional=200,
        max_daily_notional=200,
        max_position_weight=0.8,
        symbol_groups={"growth": ["SPY"]},
        max_group_weight=0.35,
    )

    decision = evaluate_orders(
        snapshot,
        [_quote()],
        [_order(160)],
        policy,
        strategy="plain_dca",
        mode="shadow",
        unresolved_order_keys=["older-order"],
        now=NOW,
    )

    assert not decision.approved_for_review
    for expected in ("snapshot is stale", "open broker order", "unresolved", "growth"):
        assert any(expected in item for item in decision.violations)
