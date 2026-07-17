from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from edgecraft.metrics import calculate_metrics
from edgecraft.models import (
    BacktestResult,
    CostModel,
    Fill,
    OrderIntent,
    PortfolioState,
    StrategyContext,
)
from edgecraft.strategies import Strategy


class BacktestEngine:
    """Daily event loop: prior-close signal, next-open execution, close valuation."""

    def __init__(self, costs: CostModel) -> None:
        self.costs = costs

    def run(
        self,
        data: dict[str, pd.DataFrame],
        strategy: Strategy,
        *,
        initial_capital: float,
        contribution_amount: float,
        contribution_frequency: str,
    ) -> BacktestResult:
        dates = data[next(iter(data))].index
        state = PortfolioState(cash=initial_capital, shares={symbol: 0.0 for symbol in data})
        pending: list[OrderIntent] = []
        fills: list[Fill] = []
        records: list[dict[str, float | pd.Timestamp]] = []
        previous_date: pd.Timestamp | None = None

        for index, current_date in enumerate(dates):
            opens = {symbol: float(frame.loc[current_date, "open"]) for symbol, frame in data.items()}
            closes = {symbol: float(frame.loc[current_date, "close"]) for symbol, frame in data.items()}
            contribution_due = self._contribution_due(
                current_date, previous_date, contribution_frequency
            )
            contribution = contribution_amount if contribution_due and index > 0 else 0.0
            if contribution:
                state.cash += contribution
                state.external_contributions += contribution

            if pending:
                new_fills = self._execute(pending, current_date, opens, state)
                fills.extend(new_fills)
                pending = []

            equity = state.value(closes)
            gross = (
                sum(abs(state.shares[symbol] * closes[symbol]) for symbol in closes) / equity
                if equity > 0
                else 0.0
            )
            records.append(
                {
                    "date": current_date,
                    "equity": equity,
                    "cash": state.cash,
                    "contribution": contribution,
                    "net_invested": initial_capital + state.external_contributions,
                    "gross_exposure": gross,
                }
            )
            history = {symbol: frame.iloc[: index + 1] for symbol, frame in data.items()}
            context = StrategyContext(
                date=current_date,
                session_index=index,
                history=history,
                state=state,
                prices=closes,
                contribution_due=contribution_due,
                contribution_amount=contribution_amount,
            )
            pending = strategy.generate(context)
            previous_date = current_date

        daily = pd.DataFrame.from_records(records).set_index("date")
        previous_equity = daily["equity"].shift()
        daily["return"] = ((daily["equity"] - daily["contribution"]) / previous_equity - 1).fillna(0)
        daily["drawdown"] = (1 + daily["return"]).cumprod()
        daily["drawdown"] = daily["drawdown"] / daily["drawdown"].cummax() - 1
        metrics = calculate_metrics(
            daily,
            initial_capital=initial_capital,
            turnover_notional=state.turnover_notional,
            fills=len(fills),
        )
        return BacktestResult(strategy.name, strategy.params, daily, fills, metrics)

    def _execute(
        self,
        intents: Iterable[OrderIntent],
        date: pd.Timestamp,
        opens: dict[str, float],
        state: PortfolioState,
    ) -> list[Fill]:
        fills: list[Fill] = []
        impact = (self.costs.slippage_bps + self.costs.spread_bps / 2) / 10_000
        for intent in sorted(intents, key=lambda order: order.side == "buy"):
            if intent.symbol not in opens or intent.notional <= 0:
                continue
            raw_price = opens[intent.symbol]
            price = raw_price * (1 + impact if intent.side == "buy" else 1 - impact)
            commission = self.costs.commission_per_order
            if intent.side == "buy":
                spend = min(intent.notional, max(0.0, state.cash - commission))
                quantity = spend / price
                if quantity <= 1e-10:
                    continue
                state.cash -= quantity * price + commission
                state.shares[intent.symbol] = state.shares.get(intent.symbol, 0.0) + quantity
            else:
                available = state.shares.get(intent.symbol, 0.0)
                quantity = min(available, intent.notional / price)
                if quantity <= 1e-10:
                    continue
                state.shares[intent.symbol] = available - quantity
                state.cash += quantity * price - commission
            notional = quantity * price
            state.turnover_notional += notional
            fills.append(
                Fill(date, intent.symbol, intent.side, quantity, price, notional, commission, intent.reason)
            )
        return fills

    @staticmethod
    def _contribution_due(current: pd.Timestamp, previous: pd.Timestamp | None, frequency: str) -> bool:
        if previous is None:
            return True
        if frequency == "daily":
            return True
        if frequency == "weekly":
            return current.to_period("W") != previous.to_period("W")
        if frequency == "monthly":
            return current.to_period("M") != previous.to_period("M")
        raise ValueError(f"Unsupported contribution frequency: {frequency}")
