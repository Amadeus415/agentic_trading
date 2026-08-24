"""Focused tests for the deterministic paper-fund accounting core."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from edgecraft import __version__
from edgecraft.fund_brain import build_fund_brain
from edgecraft.paper_fund import (
    AssetClass,
    CycleRuntimeMetadata,
    DecisionAction,
    DecisionJournal,
    FundDecision,
    FundEvidence,
    FundHypothesis,
    FundMandate,
    FundOrder,
    FundQuote,
    HypothesisStance,
    OrderSide,
    PaperFundIdempotencyError,
    PaperFundIntegrityError,
    PaperFundLedger,
    PaperFundValidationError,
    QuoteStatus,
    mandate_digest,
    validate_decision_journal,
)

AS_OF = datetime(2026, 8, 6, 15, 0, tzinfo=UTC)
FUND_ID = "paper-fund-1"


def _ev(
    eid: str,
    *,
    instruments: tuple[str, ...] = (),
    claim: str = "evidence claim",
) -> FundEvidence:
    observed_at = AS_OF - timedelta(minutes=5)
    return FundEvidence(
        evidence_id=eid,
        observed_at=observed_at,
        source_timestamp=observed_at,
        source_name="test-source",
        source_url="https://example.test/evidence",
        claim=claim,
        summary=claim,
        instrument_ids=instruments,
        content=claim,
    )


def _quote(
    instrument_id: str,
    price: str | Decimal,
    asset_class: AssetClass,
    *,
    quote_id: str | None = None,
    observed_at: datetime | None = None,
    source_timestamp: datetime | None = None,
    status: QuoteStatus = QuoteStatus.OPEN,
) -> FundQuote:
    observed_at = observed_at or (AS_OF - timedelta(minutes=1))
    return FundQuote(
        quote_id=quote_id or f"q-{instrument_id}",
        instrument_id=instrument_id,
        asset_class=asset_class,
        price=Decimal(str(price)),
        observed_at=observed_at,
        source_timestamp=source_timestamp or observed_at,
        source_name="test-quotes",
        source_url="https://example.test/quotes",
        status=status,
    )


def _decision(
    cycle_key: str,
    *,
    action: DecisionAction = DecisionAction.TRADE,
    orders: tuple[FundOrder, ...] = (),
    evidence: tuple[FundEvidence, ...] = (),
    as_of: datetime = AS_OF,
    thesis: str = "test thesis",
) -> FundDecision:
    return FundDecision(
        decision_id=f"d-{cycle_key}",
        fund_id=FUND_ID,
        cycle_key=cycle_key,
        as_of=as_of,
        action=action,
        thesis=thesis,
        alternatives="none",
        risks="market risk",
        evidence=evidence,
        orders=orders,
    )


def _buy(
    instrument_id: str,
    qty: str,
    asset_class: AssetClass,
    evidence_ids: tuple[str, ...] = ("e1",),
) -> FundOrder:
    return FundOrder(
        instrument_id=instrument_id,
        asset_class=asset_class,
        side=OrderSide.BUY,
        quantity=Decimal(qty),
        rationale=f"buy {instrument_id}",
        evidence_ids=evidence_ids,
    )


def _sell(
    instrument_id: str,
    qty: str,
    asset_class: AssetClass,
    evidence_ids: tuple[str, ...] = ("e1",),
) -> FundOrder:
    return FundOrder(
        instrument_id=instrument_id,
        asset_class=asset_class,
        side=OrderSide.SELL,
        quantity=Decimal(qty),
        rationale=f"sell {instrument_id}",
        evidence_ids=evidence_ids,
    )


def _short(
    instrument_id: str,
    qty: str,
    asset_class: AssetClass,
    evidence_ids: tuple[str, ...] = ("e1",),
) -> FundOrder:
    return FundOrder(
        instrument_id=instrument_id,
        asset_class=asset_class,
        side=OrderSide.SHORT,
        quantity=Decimal(qty),
        rationale=f"short {instrument_id}",
        evidence_ids=evidence_ids,
    )


def _cover(
    instrument_id: str,
    qty: str,
    asset_class: AssetClass,
    evidence_ids: tuple[str, ...] = ("e1",),
) -> FundOrder:
    return FundOrder(
        instrument_id=instrument_id,
        asset_class=asset_class,
        side=OrderSide.COVER,
        quantity=Decimal(qty),
        rationale=f"cover {instrument_id}",
        evidence_ids=evidence_ids,
    )


def _ledger(tmp_path: Path) -> PaperFundLedger:
    return PaperFundLedger(tmp_path / "paper_fund.db")


def _mandate(**kwargs: object) -> FundMandate:
    base = dict(
        fee_bps=Decimal("10"),  # 10 bps = 0.10%
        slippage_bps=Decimal("0"),  # simplify P&L checks when 0
        max_gross_exposure=Decimal("5000"),
        max_absolute_net_exposure=Decimal("5000"),
        max_short_exposure=Decimal("2000"),
        max_single_position_weight=Decimal("1"),
        max_cycle_turnover=Decimal("5000"),
        max_order_count=50,
        max_drawdown=Decimal("0.50"),
        scale_limits_with_nav=False,
    )
    base.update(kwargs)
    return FundMandate(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 1. One-time $1,000 initialization; no recurring contribution
# ---------------------------------------------------------------------------


def test_one_time_initialization_and_no_cash_injection(tmp_path: Path) -> None:
    with _ledger(tmp_path) as ledger:
        state = ledger.initialize(FUND_ID, _mandate())
        assert state.cash == Decimal("1000.00")
        assert state.nav == Decimal("1000.00")
        assert state.positions == ()
        assert state.cycle_count == 0

        with pytest.raises(PaperFundValidationError, match="already initialized"):
            ledger.initialize(FUND_ID, _mandate())

        # Hold cycle cannot inject cash — cash unchanged
        result = ledger.execute_cycle(
            _decision(
                "hold-1",
                action=DecisionAction.HOLD,
                evidence=(_ev("e-hold"),),
            ),
            quotes=[],
        )
        assert result.state.cash == Decimal("1000.00")
        assert result.state.nav == Decimal("1000.00")


# ---------------------------------------------------------------------------
# 2. Buy, later sell, realized P&L, fees, NAV/exposure identity
# ---------------------------------------------------------------------------


def test_buy_sell_realized_pnl_fees_nav_identity(tmp_path: Path) -> None:
    # fee 10 bps, no slippage for arithmetic clarity
    mandate = _mandate(fee_bps=Decimal("10"), slippage_bps=Decimal("0"))
    with _ledger(tmp_path) as ledger:
        ledger.initialize(FUND_ID, mandate)
        ev = _ev("e1", instruments=("AAPL",))
        buy = ledger.execute_cycle(
            _decision(
                "c-buy",
                orders=(_buy("AAPL", "5", AssetClass.STOCK),),
                evidence=(ev,),
            ),
            quotes=[_quote("AAPL", "100", AssetClass.STOCK)],
        )
        # gross=500, fee=0.5, cash=1000-500.5=499.5
        assert buy.fills[0].fee == Decimal("0.5")
        assert buy.state.cash == Decimal("499.5")
        assert len(buy.state.positions) == 1
        assert buy.state.positions[0].quantity == Decimal("5")
        assert buy.state.positions[0].average_entry == Decimal("100")
        # NAV = 499.5 + 5*100 = 999.5
        assert buy.state.nav == Decimal("999.5")
        assert buy.state.gross_exposure == Decimal("500")
        assert buy.state.net_exposure == Decimal("500")
        assert buy.state.cash + buy.state.net_exposure == buy.state.nav

        sell = ledger.execute_cycle(
            _decision(
                "c-sell",
                orders=(_sell("AAPL", "5", AssetClass.STOCK),),
                evidence=(ev,),
                as_of=AS_OF + timedelta(hours=1),
            ),
            quotes=[
                _quote(
                    "AAPL",
                    "110",
                    AssetClass.STOCK,
                    observed_at=AS_OF + timedelta(hours=1) - timedelta(minutes=1),
                )
            ],
        )
        # exec=110, gross=550, fee=0.55, cash_delta=549.45
        # realized = (110-100)*5 - 0.55 = 50 - 0.55 = 49.45
        assert sell.fills[0].realized_pnl == Decimal("49.45")
        assert sell.state.cash == Decimal("499.5") + Decimal("549.45")
        assert sell.state.positions == ()
        assert sell.state.realized_pnl_cumulative == Decimal("49.45")
        assert sell.state.nav == sell.state.cash
        assert sell.state.gross_exposure == Decimal("0")


# ---------------------------------------------------------------------------
# 3. Short, later cover, realized P&L
# ---------------------------------------------------------------------------


def test_short_cover_realized_pnl(tmp_path: Path) -> None:
    mandate = _mandate(fee_bps=Decimal("10"), slippage_bps=Decimal("0"))
    with _ledger(tmp_path) as ledger:
        ledger.initialize(FUND_ID, mandate)
        ev = _ev("e1", instruments=("TSLA",))

        short = ledger.execute_cycle(
            _decision(
                "c-short",
                orders=(_short("TSLA", "2", AssetClass.STOCK),),
                evidence=(ev,),
            ),
            quotes=[_quote("TSLA", "200", AssetClass.STOCK)],
        )
        # gross=400, fee=0.4, cash_delta=+399.6, cash=1399.6
        assert short.state.cash == Decimal("1399.6")
        assert short.state.positions[0].quantity == Decimal("-2")
        assert short.state.positions[0].average_entry == Decimal("200")
        # NAV = 1399.6 + (-2)*200 = 999.6
        assert short.state.nav == Decimal("999.6")
        assert short.state.short_exposure == Decimal("400")

        cover = ledger.execute_cycle(
            _decision(
                "c-cover",
                orders=(_cover("TSLA", "2", AssetClass.STOCK),),
                evidence=(ev,),
                as_of=AS_OF + timedelta(hours=1),
            ),
            quotes=[
                _quote(
                    "TSLA",
                    "180",
                    AssetClass.STOCK,
                    observed_at=AS_OF + timedelta(hours=1) - timedelta(minutes=1),
                )
            ],
        )
        # exec=180, gross=360, fee=0.36, cash_delta=-360.36
        # realized = (200-180)*2 - 0.36 = 40 - 0.36 = 39.64
        assert cover.fills[0].realized_pnl == Decimal("39.64")
        assert cover.state.positions == ()
        assert cover.state.realized_pnl_cumulative == Decimal("39.64")
        assert cover.state.cash == Decimal("1399.6") - Decimal("360.36")
        assert cover.state.nav == cover.state.cash


# ---------------------------------------------------------------------------
# 4. Stock + crypto + prediction in one cycle
# ---------------------------------------------------------------------------


def test_multi_asset_class_single_cycle(tmp_path: Path) -> None:
    mandate = _mandate(fee_bps=Decimal("0"), slippage_bps=Decimal("0"))
    with _ledger(tmp_path) as ledger:
        ledger.initialize(FUND_ID, mandate)
        evidence = (
            _ev("e-stock", instruments=("SPY",)),
            _ev("e-crypto", instruments=("BTC-USD",)),
            _ev("e-pred", instruments=("ELECTION-2028",)),
        )
        result = ledger.execute_cycle(
            _decision(
                "c-multi",
                orders=(
                    FundOrder(
                        instrument_id="SPY",
                        asset_class=AssetClass.STOCK,
                        side=OrderSide.BUY,
                        quantity=Decimal("1"),
                        rationale="equity core",
                        evidence_ids=("e-stock",),
                    ),
                    FundOrder(
                        instrument_id="BTC-USD",
                        asset_class=AssetClass.CRYPTO,
                        side=OrderSide.BUY,
                        quantity=Decimal("0.001"),
                        rationale="crypto satellite",
                        evidence_ids=("e-crypto",),
                    ),
                    FundOrder(
                        instrument_id="ELECTION-2028",
                        asset_class=AssetClass.PREDICTION,
                        side=OrderSide.BUY,
                        quantity=Decimal("100"),
                        rationale="prediction market",
                        evidence_ids=("e-pred",),
                    ),
                ),
                evidence=evidence,
            ),
            quotes=[
                _quote("SPY", "200", AssetClass.STOCK),
                _quote("BTC-USD", "50000", AssetClass.CRYPTO),
                _quote("ELECTION-2028", "0.40", AssetClass.PREDICTION),
            ],
        )
        # costs: 200 + 50 + 40 = 290
        ids = {p.instrument_id for p in result.state.positions}
        assert ids == {"SPY", "BTC-USD", "ELECTION-2028"}
        assert len(result.fills) == 3
        assert result.state.cash == Decimal("710")
        assert len(result.state.positions) == 3
        assert result.state.nav == Decimal("1000")  # marks at cost, no fee


def test_many_positions_can_open_atomically_in_one_cycle(tmp_path: Path) -> None:
    instruments = tuple(f"STOCK{index}" for index in range(12))
    evidence = tuple(
        _ev(f"e-{instrument}", instruments=(instrument,)) for instrument in instruments
    )
    orders = tuple(
        _buy(
            instrument,
            "1",
            AssetClass.STOCK,
            evidence_ids=(f"e-{instrument}",),
        )
        for instrument in instruments
    )
    quotes = [_quote(instrument, "50", AssetClass.STOCK) for instrument in instruments]

    with _ledger(tmp_path) as ledger:
        ledger.initialize(FUND_ID, _mandate(fee_bps=Decimal("0")))
        result = ledger.execute_cycle(
            _decision("many-positions", orders=orders, evidence=evidence),
            quotes,
        )

    assert len(result.state.positions) == 12
    assert result.state.gross_exposure == Decimal("600")
    assert result.audit is not None
    assert result.audit.risk.order_count == 12


# ---------------------------------------------------------------------------
# 5. Prediction settlement at 0 and 1 exactly once
# ---------------------------------------------------------------------------


def test_prediction_settlement_once_at_zero_and_one(tmp_path: Path) -> None:
    mandate = _mandate(fee_bps=Decimal("0"), slippage_bps=Decimal("0"))
    with _ledger(tmp_path) as ledger:
        ledger.initialize(FUND_ID, mandate)
        # Open two prediction positions
        ledger.execute_cycle(
            _decision(
                "c-open-pred",
                orders=(
                    _buy("YES-EVENT", "100", AssetClass.PREDICTION, ("e1",)),
                    _buy("NO-EVENT", "50", AssetClass.PREDICTION, ("e2",)),
                ),
                evidence=(
                    _ev("e1", instruments=("YES-EVENT",)),
                    _ev("e2", instruments=("NO-EVENT",)),
                ),
            ),
            quotes=[
                _quote("YES-EVENT", "0.40", AssetClass.PREDICTION),
                _quote("NO-EVENT", "0.60", AssetClass.PREDICTION),
            ],
        )
        # Settle YES at 1, NO at 0
        settled = ledger.execute_cycle(
            _decision(
                "c-settle",
                action=DecisionAction.HOLD,
                evidence=(_ev("e-settle"),),
                as_of=AS_OF + timedelta(hours=1),
            ),
            quotes=[
                _quote(
                    "YES-EVENT",
                    "1",
                    AssetClass.PREDICTION,
                    quote_id="q-yes-settle",
                    observed_at=AS_OF + timedelta(hours=1) - timedelta(minutes=1),
                    status=QuoteStatus.SETTLED,
                ),
                _quote(
                    "NO-EVENT",
                    "0",
                    AssetClass.PREDICTION,
                    quote_id="q-no-settle",
                    observed_at=AS_OF + timedelta(hours=1) - timedelta(minutes=1),
                    status=QuoteStatus.SETTLED,
                ),
            ],
        )
        assert len(settled.settlements) == 2
        assert settled.state.positions == ()
        # YES: buy 100@0.40 cost 40, settle 1 -> +100 cash, realized +60
        # NO: buy 50@0.60 cost 30, settle 0 -> +0 cash, realized -30
        # cash after open: 1000-40-30=930; after settle +100+0=1030
        assert settled.state.cash == Decimal("1030")
        assert settled.state.realized_pnl_cumulative == Decimal("30")

        # Second settlement attempt with same instruments but no positions: no double settle fills
        again = ledger.execute_cycle(
            _decision(
                "c-settle-again",
                action=DecisionAction.HOLD,
                evidence=(_ev("e-settle2"),),
                as_of=AS_OF + timedelta(hours=2),
            ),
            quotes=[
                _quote(
                    "YES-EVENT",
                    "1",
                    AssetClass.PREDICTION,
                    quote_id="q-yes-settle-2",
                    observed_at=AS_OF + timedelta(hours=2) - timedelta(minutes=1),
                    status=QuoteStatus.SETTLED,
                ),
            ],
        )
        assert again.settlements == ()

        # Cannot order on settled instrument
        with pytest.raises(PaperFundValidationError, match="settled instrument"):
            ledger.execute_cycle(
                _decision(
                    "c-order-settled",
                    orders=(_buy("YES-EVENT", "1", AssetClass.PREDICTION),),
                    evidence=(_ev("e1", instruments=("YES-EVENT",)),),
                    as_of=AS_OF + timedelta(hours=3),
                ),
                quotes=[
                    _quote(
                        "YES-EVENT",
                        "1",
                        AssetClass.PREDICTION,
                        quote_id="q-yes-3",
                        observed_at=AS_OF + timedelta(hours=3) - timedelta(minutes=1),
                        status=QuoteStatus.SETTLED,
                    ),
                ],
            )


# ---------------------------------------------------------------------------
# 6. Hold does not change cash/positions; still audited
# ---------------------------------------------------------------------------


def test_hold_no_change_but_audited(tmp_path: Path) -> None:
    with _ledger(tmp_path) as ledger:
        ledger.initialize(FUND_ID, _mandate())
        before = ledger.get_state(FUND_ID)
        result = ledger.execute_cycle(
            _decision("hold-x", action=DecisionAction.HOLD, evidence=(_ev("eh"),)),
            quotes=[],
        )
        assert result.action is DecisionAction.HOLD
        assert result.fills == ()
        assert result.state.cash == before.cash
        assert result.state.positions == before.positions
        assert result.state.cycle_count == before.cycle_count + 1
        events = ledger.list_events(FUND_ID)
        assert any(e.event_type == "cycle_completed" for e in events)
        assert any(e.event_type == "fund_initialized" for e in events)
        cycles = ledger.list_cycles(FUND_ID)
        assert len(cycles) == 1
        assert cycles[0]["cycle_key"] == "hold-x"


# ---------------------------------------------------------------------------
# 7. Idempotent replay and same-key tamper rejection
# ---------------------------------------------------------------------------


def test_idempotent_replay_and_tamper_rejection(tmp_path: Path) -> None:
    mandate = _mandate(fee_bps=Decimal("0"), slippage_bps=Decimal("0"))
    with _ledger(tmp_path) as ledger:
        ledger.initialize(FUND_ID, mandate)
        ev = _ev("e1", instruments=("AAPL",))
        decision = _decision(
            "idem-1",
            orders=(_buy("AAPL", "1", AssetClass.STOCK),),
            evidence=(ev,),
        )
        quotes = [_quote("AAPL", "100", AssetClass.STOCK)]
        first = ledger.execute_cycle(decision, quotes)
        second = ledger.execute_cycle(decision, quotes)
        assert first.replayed is False
        assert second.replayed is True
        assert second.state.cash == first.state.cash
        assert second.request_digest == first.request_digest
        # No extra cycle row
        assert len(ledger.list_cycles(FUND_ID)) == 1
        # Same key different payload
        other = _decision(
            "idem-1",
            orders=(_buy("AAPL", "2", AssetClass.STOCK),),
            evidence=(ev,),
        )
        with pytest.raises(PaperFundIdempotencyError, match="different request"):
            ledger.execute_cycle(other, quotes)


# ---------------------------------------------------------------------------
# 8. Oversell, over-cover, illegal side crossing, quote failures
# ---------------------------------------------------------------------------


def test_illegal_sides_and_quote_failures(tmp_path: Path) -> None:
    mandate = _mandate(fee_bps=Decimal("0"), slippage_bps=Decimal("0"))
    with _ledger(tmp_path) as ledger:
        ledger.initialize(FUND_ID, mandate)
        ev = _ev("e1", instruments=("AAPL", "TSLA", "MSFT", "NVDA"))
        ledger.execute_cycle(
            _decision(
                "seed-long",
                orders=(_buy("AAPL", "2", AssetClass.STOCK),),
                evidence=(ev,),
            ),
            quotes=[_quote("AAPL", "50", AssetClass.STOCK)],
        )
        ledger.execute_cycle(
            _decision(
                "seed-short",
                orders=(_short("TSLA", "1", AssetClass.STOCK),),
                evidence=(ev,),
                as_of=AS_OF + timedelta(minutes=10),
            ),
            quotes=[
                _quote(
                    "AAPL",
                    "50",
                    AssetClass.STOCK,
                    observed_at=AS_OF + timedelta(minutes=9),
                ),
                _quote(
                    "TSLA",
                    "100",
                    AssetClass.STOCK,
                    observed_at=AS_OF + timedelta(minutes=9),
                ),
            ],
        )

        t = AS_OF + timedelta(hours=1)
        q_aapl = _quote("AAPL", "50", AssetClass.STOCK, observed_at=t - timedelta(minutes=1))
        q_tsla = _quote("TSLA", "100", AssetClass.STOCK, observed_at=t - timedelta(minutes=1))

        # Oversell
        with pytest.raises(PaperFundValidationError, match="oversell"):
            ledger.execute_cycle(
                _decision(
                    "bad-oversell",
                    orders=(_sell("AAPL", "5", AssetClass.STOCK),),
                    evidence=(ev,),
                    as_of=t,
                ),
                quotes=[q_aapl, q_tsla],
            )

        # Over-cover
        with pytest.raises(PaperFundValidationError, match="over-cover"):
            ledger.execute_cycle(
                _decision(
                    "bad-overcover",
                    orders=(_cover("TSLA", "5", AssetClass.STOCK),),
                    evidence=(ev,),
                    as_of=t,
                ),
                quotes=[q_aapl, q_tsla],
            )

        # Buy cannot cover short
        with pytest.raises(PaperFundValidationError, match="buy cannot cover"):
            ledger.execute_cycle(
                _decision(
                    "bad-buy-cover",
                    orders=(_buy("TSLA", "1", AssetClass.STOCK),),
                    evidence=(ev,),
                    as_of=t,
                ),
                quotes=[q_aapl, q_tsla],
            )

        # Sell cannot open short
        with pytest.raises(PaperFundValidationError, match="sell cannot"):
            ledger.execute_cycle(
                _decision(
                    "bad-sell-short",
                    orders=(_sell("MSFT", "1", AssetClass.STOCK),),
                    evidence=(ev,),
                    as_of=t,
                ),
                quotes=[
                    q_aapl,
                    q_tsla,
                    _quote("MSFT", "10", AssetClass.STOCK, observed_at=t - timedelta(minutes=1)),
                ],
            )

        # Short cannot reduce long
        with pytest.raises(PaperFundValidationError, match="short cannot reduce"):
            ledger.execute_cycle(
                _decision(
                    "bad-short-long",
                    orders=(_short("AAPL", "1", AssetClass.STOCK),),
                    evidence=(ev,),
                    as_of=t,
                ),
                quotes=[q_aapl, q_tsla],
            )

        # Cover cannot open long
        with pytest.raises(PaperFundValidationError, match="cover cannot open"):
            ledger.execute_cycle(
                _decision(
                    "bad-cover-long",
                    orders=(_cover("MSFT", "1", AssetClass.STOCK),),
                    evidence=(ev,),
                    as_of=t,
                ),
                quotes=[
                    q_aapl,
                    q_tsla,
                    _quote("MSFT", "10", AssetClass.STOCK, observed_at=t - timedelta(minutes=1)),
                ],
            )

        # Missing quote
        with pytest.raises(PaperFundValidationError, match="missing quote"):
            ledger.execute_cycle(
                _decision(
                    "bad-missing",
                    orders=(_buy("NVDA", "1", AssetClass.STOCK),),
                    evidence=(ev,),
                    as_of=t,
                ),
                quotes=[q_aapl, q_tsla],
            )

        # Stale quote
        with pytest.raises(PaperFundValidationError, match="stale quote"):
            ledger.execute_cycle(
                _decision(
                    "bad-stale",
                    orders=(_buy("NVDA", "1", AssetClass.STOCK),),
                    evidence=(ev,),
                    as_of=t,
                ),
                quotes=[
                    q_aapl,
                    q_tsla,
                    _quote(
                        "NVDA",
                        "10",
                        AssetClass.STOCK,
                        observed_at=t - timedelta(hours=2),
                    ),
                ],
            )

        # Future quote
        with pytest.raises(PaperFundValidationError, match="future quote"):
            ledger.execute_cycle(
                _decision(
                    "bad-future",
                    orders=(_buy("NVDA", "1", AssetClass.STOCK),),
                    evidence=(ev,),
                    as_of=t,
                ),
                quotes=[
                    q_aapl,
                    q_tsla,
                    _quote(
                        "NVDA",
                        "10",
                        AssetClass.STOCK,
                        observed_at=t + timedelta(minutes=5),
                    ),
                ],
            )

        # A freshly retrieved quote cannot disguise an old underlying source price.
        with pytest.raises(PaperFundValidationError, match="stale source price"):
            ledger.execute_cycle(
                _decision(
                    "bad-stale-source",
                    orders=(_buy("NVDA", "1", AssetClass.STOCK),),
                    evidence=(ev,),
                    as_of=t,
                ),
                quotes=[
                    q_aapl,
                    q_tsla,
                    _quote(
                        "NVDA",
                        "10",
                        AssetClass.STOCK,
                        observed_at=t - timedelta(minutes=1),
                        source_timestamp=t - timedelta(days=5),
                    ),
                ],
            )

        # Mismatched asset class
        with pytest.raises(PaperFundValidationError, match="mismatch"):
            ledger.execute_cycle(
                _decision(
                    "bad-mismatch",
                    orders=(_buy("NVDA", "1", AssetClass.STOCK),),
                    evidence=(ev,),
                    as_of=t,
                ),
                quotes=[
                    q_aapl,
                    q_tsla,
                    _quote(
                        "NVDA",
                        "10",
                        AssetClass.CRYPTO,
                        observed_at=t - timedelta(minutes=1),
                    ),
                ],
            )

        # Duplicate quote instrument
        with pytest.raises(PaperFundValidationError, match="duplicate quote"):
            ledger.execute_cycle(
                _decision(
                    "bad-dup",
                    action=DecisionAction.HOLD,
                    evidence=(_ev("eh"),),
                    as_of=t,
                ),
                quotes=[q_aapl, q_tsla, q_aapl.model_copy(update={"quote_id": "other"})],
            )

        # Failed cycle must not persist
        keys = {c["cycle_key"] for c in ledger.list_cycles(FUND_ID)}
        assert "bad-oversell" not in keys
        assert "bad-stale" not in keys


# ---------------------------------------------------------------------------
# 9. Risk gates with atomic rejection
# ---------------------------------------------------------------------------


def test_risk_gates_atomic_rejection(tmp_path: Path) -> None:
    # Concentration / gross
    mandate = _mandate(
        fee_bps=Decimal("0"),
        slippage_bps=Decimal("0"),
        max_gross_exposure=Decimal("200"),
        max_absolute_net_exposure=Decimal("200"),
        max_short_exposure=Decimal("50"),
        max_single_position_weight=Decimal("0.30"),
        max_cycle_turnover=Decimal("150"),
        max_order_count=1,
        max_drawdown=Decimal("0.10"),
    )
    with _ledger(tmp_path) as ledger:
        ledger.initialize(FUND_ID, mandate)
        ev = _ev("e1", instruments=("AAPL", "TSLA", "MSFT"))

        # max_order_count
        with pytest.raises(PaperFundValidationError, match="order count"):
            ledger.execute_cycle(
                _decision(
                    "r-orders",
                    orders=(
                        _buy("AAPL", "1", AssetClass.STOCK),
                        _buy("MSFT", "1", AssetClass.STOCK),
                    ),
                    evidence=(ev,),
                ),
                quotes=[
                    _quote("AAPL", "10", AssetClass.STOCK),
                    _quote("MSFT", "10", AssetClass.STOCK),
                ],
            )

        # turnover
        with pytest.raises(PaperFundValidationError, match="turnover"):
            ledger.execute_cycle(
                _decision(
                    "r-turn",
                    orders=(_buy("AAPL", "20", AssetClass.STOCK),),  # notional 200 > 150
                    evidence=(ev,),
                ),
                quotes=[_quote("AAPL", "10", AssetClass.STOCK)],
            )

    # Separate ledger for gross
    m2 = _mandate(
        fee_bps=Decimal("0"),
        slippage_bps=Decimal("0"),
        max_gross_exposure=Decimal("100"),
        max_absolute_net_exposure=Decimal("5000"),
        max_short_exposure=Decimal("5000"),
        max_single_position_weight=Decimal("1"),
        max_cycle_turnover=Decimal("5000"),
        max_order_count=10,
        max_drawdown=Decimal("0.99"),
    )
    with PaperFundLedger(tmp_path / "risk2.db") as ledger:
        ledger.initialize(FUND_ID, m2)
        ev = _ev("e1", instruments=("AAPL",))
        with pytest.raises(PaperFundValidationError, match="gross exposure"):
            ledger.execute_cycle(
                _decision(
                    "r-gross",
                    orders=(_buy("AAPL", "5", AssetClass.STOCK),),  # 5*50=250 > 100
                    evidence=(ev,),
                ),
                quotes=[_quote("AAPL", "50", AssetClass.STOCK)],
            )
        assert ledger.list_cycles(FUND_ID) == []
        assert ledger.get_state(FUND_ID).cash == Decimal("1000.00")

    # short exposure
    m3 = _mandate(
        fee_bps=Decimal("0"),
        slippage_bps=Decimal("0"),
        max_gross_exposure=Decimal("5000"),
        max_absolute_net_exposure=Decimal("5000"),
        max_short_exposure=Decimal("50"),
        max_single_position_weight=Decimal("1"),
        max_cycle_turnover=Decimal("5000"),
        max_order_count=10,
        max_drawdown=Decimal("0.99"),
    )
    with PaperFundLedger(tmp_path / "risk3.db") as ledger:
        ledger.initialize(FUND_ID, m3)
        ev = _ev("e1", instruments=("TSLA",))
        with pytest.raises(PaperFundValidationError, match="short exposure"):
            ledger.execute_cycle(
                _decision(
                    "r-short",
                    orders=(_short("TSLA", "2", AssetClass.STOCK),),  # 2*100=200 > 50
                    evidence=(ev,),
                ),
                quotes=[_quote("TSLA", "100", AssetClass.STOCK)],
            )

    # A cheap binary short is capped by its remaining $1 settlement liability,
    # not by the deceptively small current marked value.
    with PaperFundLedger(tmp_path / "risk3-prediction.db") as ledger:
        ledger.initialize(FUND_ID, m3)
        ev = _ev("e1", instruments=("polymarket:tail:YES",))
        with pytest.raises(PaperFundValidationError, match="short exposure"):
            ledger.execute_cycle(
                _decision(
                    "r-prediction-short",
                    orders=(_short("polymarket:tail:YES", "100", AssetClass.PREDICTION),),
                    evidence=(ev,),
                ),
                quotes=[
                    _quote("polymarket:tail:YES", "0.10", AssetClass.PREDICTION),
                ],
            )

    # concentration (single position weight)
    m4 = _mandate(
        fee_bps=Decimal("0"),
        slippage_bps=Decimal("0"),
        max_gross_exposure=Decimal("5000"),
        max_absolute_net_exposure=Decimal("5000"),
        max_short_exposure=Decimal("5000"),
        max_single_position_weight=Decimal("0.20"),
        max_cycle_turnover=Decimal("5000"),
        max_order_count=10,
        max_drawdown=Decimal("0.99"),
    )
    with PaperFundLedger(tmp_path / "risk4.db") as ledger:
        ledger.initialize(FUND_ID, m4)
        ev = _ev("e1", instruments=("AAPL",))
        with pytest.raises(PaperFundValidationError, match="position weight"):
            ledger.execute_cycle(
                _decision(
                    "r-weight",
                    orders=(_buy("AAPL", "5", AssetClass.STOCK),),  # 500/1000=0.5 > 0.2
                    evidence=(ev,),
                ),
                quotes=[_quote("AAPL", "100", AssetClass.STOCK)],
            )

    # net exposure
    m5 = _mandate(
        fee_bps=Decimal("0"),
        slippage_bps=Decimal("0"),
        max_gross_exposure=Decimal("5000"),
        max_absolute_net_exposure=Decimal("100"),
        max_short_exposure=Decimal("5000"),
        max_single_position_weight=Decimal("1"),
        max_cycle_turnover=Decimal("5000"),
        max_order_count=10,
        max_drawdown=Decimal("0.99"),
    )
    with PaperFundLedger(tmp_path / "risk5.db") as ledger:
        ledger.initialize(FUND_ID, m5)
        ev = _ev("e1", instruments=("AAPL",))
        with pytest.raises(PaperFundValidationError, match="net exposure"):
            ledger.execute_cycle(
                _decision(
                    "r-net",
                    orders=(_buy("AAPL", "5", AssetClass.STOCK),),  # net 500 > 100
                    evidence=(ev,),
                ),
                quotes=[_quote("AAPL", "100", AssetClass.STOCK)],
            )

    # Drawdown gate: lose money then refuse risk-increasing
    m6 = _mandate(
        fee_bps=Decimal("0"),
        slippage_bps=Decimal("0"),
        max_gross_exposure=Decimal("5000"),
        max_absolute_net_exposure=Decimal("5000"),
        max_short_exposure=Decimal("5000"),
        max_single_position_weight=Decimal("1"),
        max_cycle_turnover=Decimal("5000"),
        max_order_count=10,
        max_drawdown=Decimal("0.05"),  # 5%
    )
    with PaperFundLedger(tmp_path / "risk6.db") as ledger:
        ledger.initialize(FUND_ID, m6)
        ev = _ev("e1", instruments=("AAPL", "MSFT"))
        # Buy AAPL at 100
        ledger.execute_cycle(
            _decision(
                "dd-buy",
                orders=(_buy("AAPL", "5", AssetClass.STOCK),),
                evidence=(ev,),
            ),
            quotes=[_quote("AAPL", "100", AssetClass.STOCK)],
        )
        # Mark down hard -> drawdown > 5%
        t2 = AS_OF + timedelta(hours=1)
        ledger.execute_cycle(
            _decision(
                "dd-mark",
                action=DecisionAction.HOLD,
                evidence=(_ev("eh"),),
                as_of=t2,
            ),
            quotes=[
                _quote(
                    "AAPL",
                    "50",
                    AssetClass.STOCK,
                    observed_at=t2 - timedelta(minutes=1),
                )
            ],
        )
        state = ledger.get_state(FUND_ID)
        assert state.drawdown > Decimal("0.05")
        # Risk-increasing: add more gross
        t3 = AS_OF + timedelta(hours=2)
        with pytest.raises(PaperFundValidationError, match="drawdown"):
            ledger.execute_cycle(
                _decision(
                    "dd-increase",
                    orders=(_buy("MSFT", "1", AssetClass.STOCK),),
                    evidence=(ev,),
                    as_of=t3,
                ),
                quotes=[
                    _quote(
                        "AAPL",
                        "50",
                        AssetClass.STOCK,
                        observed_at=t3 - timedelta(minutes=1),
                    ),
                    _quote(
                        "MSFT",
                        "100",
                        AssetClass.STOCK,
                        observed_at=t3 - timedelta(minutes=1),
                    ),
                ],
            )
        assert "dd-increase" not in {c["cycle_key"] for c in ledger.list_cycles(FUND_ID)}
        # Risk-reducing / non-increasing: sell part of AAPL should be allowed
        reduce = ledger.execute_cycle(
            _decision(
                "dd-reduce",
                orders=(_sell("AAPL", "2", AssetClass.STOCK),),
                evidence=(ev,),
                as_of=t3,
            ),
            quotes=[
                _quote(
                    "AAPL",
                    "50",
                    AssetClass.STOCK,
                    observed_at=t3 - timedelta(minutes=1),
                ),
            ],
        )
        assert reduce.state.positions[0].quantity == Decimal("3")


# ---------------------------------------------------------------------------
# 10. Audit-chain verification and immutable-table triggers
# ---------------------------------------------------------------------------


def test_audit_chain_and_immutable_triggers(tmp_path: Path) -> None:
    with _ledger(tmp_path) as ledger:
        ledger.initialize(FUND_ID, _mandate(fee_bps=Decimal("0"), slippage_bps=Decimal("0")))
        ledger.execute_cycle(
            _decision("h1", action=DecisionAction.HOLD, evidence=(_ev("e"),)),
            quotes=[],
        )
        report = ledger.verify(FUND_ID)
        assert report.ok is True
        assert report.chain_ok is True
        assert report.accounting_ok is True
        assert report.event_count >= 2
        assert report.cycle_count == 1

        # Tamper with event hash via raw connection would be blocked by UPDATE trigger
        conn = ledger.connection
        with pytest.raises(Exception, match="append-only|UPDATE forbidden"):
            conn.execute(
                "UPDATE events SET event_hash = 'deadbeef' WHERE fund_id = ?",
                (FUND_ID,),
            )
            conn.commit()
        conn.rollback()

        with pytest.raises(Exception, match="append-only|DELETE forbidden"):
            conn.execute("DELETE FROM events WHERE fund_id = ?", (FUND_ID,))
            conn.commit()
        conn.rollback()

        with pytest.raises(Exception, match="append-only|UPDATE forbidden"):
            conn.execute(
                "UPDATE cycles SET action = 'tamper' WHERE fund_id = ?",
                (FUND_ID,),
            )
            conn.commit()
        conn.rollback()

        with pytest.raises(Exception, match="append-only|DELETE forbidden"):
            conn.execute("DELETE FROM cycles WHERE fund_id = ?", (FUND_ID,))
            conn.commit()
        conn.rollback()

        with pytest.raises(Exception, match="append-only|UPDATE forbidden"):
            conn.execute(
                "UPDATE funds SET initial_cash = '1' WHERE fund_id = ?",
                (FUND_ID,),
            )
            conn.commit()
        conn.rollback()

        # Still verifies clean after failed tampers
        report2 = ledger.verify(FUND_ID)
        assert report2.ok is True

        # Manually insert a broken event to force chain failure detection
        # (INSERT is allowed — only UPDATE/DELETE blocked)
        conn.execute(
            """
            INSERT INTO events (
                fund_id, sequence, event_type, occurred_at, payload_json, prev_hash, event_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                FUND_ID,
                99,
                "tamper",
                AS_OF.isoformat().replace("+00:00", "Z"),
                "{}",
                "badprev",
                "badhash",
            ),
        )
        conn.commit()
        with pytest.raises(PaperFundIntegrityError):
            ledger.verify(FUND_ID, raise_on_error=True)
        soft = ledger.verify(FUND_ID, raise_on_error=False)
        assert soft.ok is False
        assert soft.chain_ok is False


def test_quote_model_prediction_price_rules() -> None:
    with pytest.raises(ValidationError):
        FundQuote(
            quote_id="q1",
            instrument_id="X",
            asset_class=AssetClass.PREDICTION,
            price=Decimal("0"),
            observed_at=AS_OF,
            source_timestamp=AS_OF,
            source_name="s",
            source_url="https://example.test",
            status=QuoteStatus.OPEN,
        )
    with pytest.raises(ValidationError):
        FundQuote(
            quote_id="q1",
            instrument_id="X",
            asset_class=AssetClass.PREDICTION,
            price=Decimal("0.5"),
            observed_at=AS_OF,
            source_timestamp=AS_OF,
            source_name="s",
            source_url="https://example.test",
            status=QuoteStatus.SETTLED,
        )
    ok = FundQuote(
        quote_id="q1",
        instrument_id="X",
        asset_class=AssetClass.PREDICTION,
        price=Decimal("1"),
        observed_at=AS_OF,
        source_timestamp=AS_OF,
        source_name="s",
        source_url="https://example.test",
        status=QuoteStatus.SETTLED,
    )
    assert ok.price == Decimal("1")

    with pytest.raises(ValidationError, match="source_timestamp"):
        FundQuote(
            quote_id="q-future-source",
            instrument_id="SPY",
            asset_class=AssetClass.STOCK,
            price=Decimal("100"),
            observed_at=AS_OF,
            source_timestamp=AS_OF + timedelta(minutes=2),
            source_name="s",
            source_url="https://example.test",
        )


def test_trade_order_requires_instrument_specific_evidence() -> None:
    with pytest.raises(ValidationError, match="instrument-specific evidence"):
        _decision(
            "generic-evidence",
            orders=(_buy("SPY", "1", AssetClass.STOCK),),
            evidence=(_ev("e1"),),
        )


def test_out_of_order_cycle_is_rejected_and_audited(tmp_path: Path) -> None:
    with _ledger(tmp_path) as ledger:
        ledger.initialize(FUND_ID, _mandate())
        ledger.execute_cycle(
            _decision(
                "first",
                action=DecisionAction.HOLD,
                evidence=(_ev("first-evidence"),),
            ),
            quotes=[],
        )

        with pytest.raises(PaperFundValidationError, match="predates prior state"):
            ledger.execute_cycle(
                _decision(
                    "out-of-order",
                    action=DecisionAction.HOLD,
                    evidence=(_ev("old-evidence"),),
                    as_of=AS_OF - timedelta(minutes=1),
                ),
                quotes=[],
            )

        assert ledger.get_state(FUND_ID).cycle_count == 1
        rejection = ledger.list_events(FUND_ID)[-1]
        assert rejection.event_type == "cycle_rejected"
        assert rejection.payload["cycle_key"] == "out-of-order"
        assert rejection.payload["decision"]["action"] == "hold"
        assert ledger.verify(FUND_ID).ok is True


def test_prediction_short_collateral_cannot_be_redeployed(tmp_path: Path) -> None:
    mandate = _mandate(
        fee_bps=Decimal("0"),
        slippage_bps=Decimal("0"),
        max_gross_exposure=Decimal("1500"),
        max_absolute_net_exposure=Decimal("1000"),
        max_short_exposure=Decimal("500"),
        max_single_position_weight=Decimal("1"),
        max_cycle_turnover=Decimal("1000"),
    )
    prediction = "polymarket:binary:YES"
    with _ledger(tmp_path) as ledger:
        ledger.initialize(FUND_ID, mandate)
        ledger.execute_cycle(
            _decision(
                "open-prediction-short",
                orders=(
                    _short(
                        prediction,
                        "500",
                        AssetClass.PREDICTION,
                        ("prediction",),
                    ),
                ),
                evidence=(_ev("prediction", instruments=(prediction,)),),
            ),
            quotes=[_quote(prediction, "0.50", AssetClass.PREDICTION)],
        )

        later = AS_OF + timedelta(minutes=10)
        with pytest.raises(PaperFundValidationError, match="settlement reserve"):
            ledger.execute_cycle(
                _decision(
                    "redeploy-collateral",
                    orders=(_buy("SPY", "8", AssetClass.STOCK, ("spy",)),),
                    evidence=(_ev("spy", instruments=("SPY",)),),
                    as_of=later,
                ),
                quotes=[
                    _quote(
                        prediction,
                        "0.50",
                        AssetClass.PREDICTION,
                        observed_at=later - timedelta(minutes=1),
                    ),
                    _quote(
                        "SPY",
                        "100",
                        AssetClass.STOCK,
                        observed_at=later - timedelta(minutes=1),
                    ),
                ],
            )

        settlement_time = AS_OF + timedelta(minutes=20)
        result = ledger.execute_cycle(
            _decision(
                "settle-prediction-short",
                action=DecisionAction.HOLD,
                evidence=(_ev("settlement"),),
                as_of=settlement_time,
            ),
            quotes=[
                _quote(
                    prediction,
                    "1",
                    AssetClass.PREDICTION,
                    observed_at=settlement_time - timedelta(minutes=1),
                    status=QuoteStatus.SETTLED,
                )
            ],
        )

        assert result.state.cash == Decimal("750")
        assert result.state.nav == Decimal("750")
        assert result.state.positions == ()
        assert ledger.verify(FUND_ID).ok is True


def test_trade_requires_orders_hold_forbids() -> None:
    with pytest.raises(Exception, match="trade decisions require"):
        _decision("x", action=DecisionAction.TRADE, orders=(), evidence=(_ev("e"),))
    with pytest.raises(Exception, match="hold decisions must not"):
        _decision(
            "y",
            action=DecisionAction.HOLD,
            orders=(_buy("AAPL", "1", AssetClass.STOCK),),
            evidence=(_ev("e", instruments=("AAPL",)),),
        )


def test_default_mandate_is_paper_thousand() -> None:
    m = FundMandate()
    assert m.initial_cash == Decimal("1000.00")
    assert AssetClass.STOCK in m.supported_asset_classes
    assert AssetClass.CRYPTO in m.supported_asset_classes
    assert AssetClass.PREDICTION in m.supported_asset_classes


def test_scheduled_journal_requires_hypothesis_for_every_live_instrument(tmp_path: Path) -> None:
    evidence = _ev("e1", instruments=("AAPL",))
    journal = DecisionJournal(
        market_regime="Test regime",
        opportunity_set="AAPL and cash",
        portfolio_intent="Open one test position",
        what_changed="First cycle",
        hypotheses=(
            FundHypothesis(
                instrument_id="AAPL",
                stance=HypothesisStance.LONG,
                statement="AAPL may rise",
                mechanism="Earnings growth can raise value",
                catalysts=("earnings",),
                falsifiers=("guidance cut",),
                expected_horizon_hours=168,
                confidence=Decimal("0.6"),
                target_price=Decimal("120"),
                invalidation_price=Decimal("90"),
                evidence_ids=("e1",),
            ),
        ),
    )
    opening = _decision(
        "journal-open",
        orders=(_buy("AAPL", "1", AssetClass.STOCK),),
        evidence=(evidence,),
    ).model_copy(update={"journal": journal})

    with _ledger(tmp_path) as ledger:
        ledger.initialize(FUND_ID, _mandate())
        validate_decision_journal(opening, ledger.get_state(FUND_ID))
        ledger.execute_cycle(opening, [_quote("AAPL", "100", AssetClass.STOCK)])
        next_hold = _decision(
            "journal-hold",
            action=DecisionAction.HOLD,
            evidence=(evidence,),
            as_of=AS_OF + timedelta(hours=1),
        ).model_copy(
            update={
                "journal": DecisionJournal(
                    market_regime="Test regime",
                    opportunity_set="AAPL and cash",
                    portfolio_intent="Review the book",
                    what_changed="No change",
                )
            }
        )
        with pytest.raises(PaperFundValidationError, match="AAPL"):
            validate_decision_journal(next_hold, ledger.get_state(FUND_ID))
        with pytest.raises(PaperFundValidationError, match="AAPL"):
            ledger.execute_cycle(next_hold, [], require_brain_journal=True)
        assert ledger.list_events(FUND_ID)[-1].event_type == "cycle_rejected"
        assert "AAPL" in ledger.list_events(FUND_ID)[-1].payload["reason"]


def test_fund_brain_surfaces_losing_exit_as_future_feedback(tmp_path: Path) -> None:
    evidence = _ev("e1", instruments=("AAPL",))
    with _ledger(tmp_path) as ledger:
        ledger.initialize(FUND_ID, _mandate(fee_bps=Decimal("0")))
        ledger.execute_cycle(
            _decision(
                "brain-buy",
                orders=(_buy("AAPL", "1", AssetClass.STOCK),),
                evidence=(evidence,),
            ),
            [_quote("AAPL", "100", AssetClass.STOCK)],
        )
        ledger.execute_cycle(
            _decision(
                "brain-sell",
                orders=(_sell("AAPL", "1", AssetClass.STOCK),),
                evidence=(evidence,),
                as_of=AS_OF + timedelta(hours=1),
            ),
            [
                _quote(
                    "AAPL",
                    "90",
                    AssetClass.STOCK,
                    observed_at=AS_OF + timedelta(minutes=59),
                )
            ],
        )

        brain = build_fund_brain(ledger, FUND_ID, generated_at=AS_OF + timedelta(hours=2))

    aapl = next(item for item in brain.instruments if item.instrument_id == "AAPL")
    assert aapl.losing_exit_count == 1
    assert aapl.realized_pnl == Decimal("-10")
    assert brain.recent_cycles[0].next_cycle_outcome == "negative"
    assert any("AAPL" in prompt for prompt in brain.adaptive_prompts)


# ---------------------------------------------------------------------------
# Full audit trail: risk, provenance, hash-chained payloads, retrieval
# ---------------------------------------------------------------------------


def test_completed_cycle_is_fully_auditable(tmp_path: Path) -> None:
    mandate = _mandate(fee_bps=Decimal("0"), slippage_bps=Decimal("0"))
    with _ledger(tmp_path) as ledger:
        ledger.initialize(FUND_ID, mandate)
        evidence = _ev("spy-e", instruments=("SPY",))
        decision = _decision(
            "audit-trade",
            orders=(_buy("SPY", "1", AssetClass.STOCK, evidence_ids=("spy-e",)),),
            evidence=(evidence,),
            thesis="Buy a unit of SPY after fresh sourced evidence.",
            as_of=AS_OF,
        )
        quotes = [_quote("SPY", "100", AssetClass.STOCK)]
        runtime = CycleRuntimeMetadata(
            edgecraft_version=__version__,
            mandate_digest=mandate_digest(mandate),
            prompt_version="edgecraft.prompts.test",
            model="test-model",
            input_path="/tmp/input.json",
            input_sha256="a" * 64,
            recorded_at=AS_OF,
        )
        result = ledger.execute_cycle(decision, quotes, runtime=runtime)

        assert result.audit is not None
        assert result.audit.risk.approved is True
        assert result.audit.risk.checks
        assert all(check.passed for check in result.audit.risk.checks)
        assert result.audit.runtime.prompt_version == "edgecraft.prompts.test"
        assert result.audit.runtime.model == "test-model"
        assert result.audit.runtime.input_sha256 == "a" * 64
        assert result.audit.quote_freshness[0].instrument_id == "SPY"
        assert result.audit.fill_count == 1

        completed = next(
            event for event in ledger.list_events(FUND_ID) if event.event_type == "cycle_completed"
        )
        assert completed.payload["decision"]["thesis"] == decision.thesis
        assert completed.payload["quotes"][0]["instrument_id"] == "SPY"
        assert completed.payload["fills"][0]["side"] == "buy"
        assert completed.payload["audit"]["risk"]["approved"] is True
        assert completed.payload["audit"]["runtime"]["model"] == "test-model"

        cycle = ledger.get_cycle(FUND_ID, "audit-trade")
        assert cycle["decision"]["decision_id"] == decision.decision_id
        assert cycle["audit"]["runtime"]["prompt_version"] == "edgecraft.prompts.test"

        audit = ledger.cycle_audit(FUND_ID, "audit-trade")
        assert audit["audit_gaps"] == []
        assert audit["reconciliation"]["ledger_ok"] is True
        assert audit["events"][0]["event_type"] == "cycle_completed"
        assert audit["fills"][0]["fee"] == "0"
        assert ledger.verify(FUND_ID).ok is True


def test_risk_rejection_records_structured_risk_audit(tmp_path: Path) -> None:
    mandate = _mandate(max_order_count=0, fee_bps=Decimal("0"), slippage_bps=Decimal("0"))
    with _ledger(tmp_path) as ledger:
        ledger.initialize(FUND_ID, mandate)
        with pytest.raises(PaperFundValidationError, match="order count"):
            ledger.execute_cycle(
                _decision(
                    "too-many",
                    orders=(_buy("SPY", "1", AssetClass.STOCK),),
                    evidence=(_ev("e1", instruments=("SPY",)),),
                ),
                quotes=[_quote("SPY", "100", AssetClass.STOCK)],
            )
        rejection = ledger.list_events(FUND_ID)[-1]
        assert rejection.event_type == "cycle_rejected"
        assert rejection.payload["risk"]["approved"] is False
        assert any(
            check["name"] == "order_count" and check["passed"] is False
            for check in rejection.payload["risk"]["checks"]
        )
        assert rejection.payload["decision"]["cycle_key"] == "too-many"
        assert rejection.payload["runtime"]["edgecraft_version"] == __version__
        assert "mandate_digest" in rejection.payload["runtime"]
        assert ledger.verify(FUND_ID).ok is True
