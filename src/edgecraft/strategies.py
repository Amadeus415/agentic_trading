from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

from edgecraft.indicators import feature_frame, realized_volatility, rsi
from edgecraft.models import OrderIntent, StrategyContext


class Strategy(ABC):
    name: str

    def __init__(self, **params: Any) -> None:
        self.params = params

    @abstractmethod
    def generate(self, context: StrategyContext) -> list[OrderIntent]:
        raise NotImplementedError

    @staticmethod
    def invest_cash(
        context: StrategyContext, symbols: list[str], reason: str, cash_fraction: float = 1.0
    ) -> list[OrderIntent]:
        if not symbols or context.state.cash <= 1:
            return []
        amount = context.state.cash * min(max(cash_fraction, 0), 1) / len(symbols)
        return [OrderIntent(symbol, "buy", amount, reason) for symbol in symbols]

    @staticmethod
    def rebalance(
        context: StrategyContext, weights: dict[str, float], reason: str
    ) -> list[OrderIntent]:
        equity = context.state.value(context.prices)
        intents: list[OrderIntent] = []
        clean_weights = {symbol: max(0.0, float(weight)) for symbol, weight in weights.items()}
        total_weight = sum(clean_weights.values())
        if total_weight > 1.000001:
            clean_weights = {symbol: weight / total_weight for symbol, weight in clean_weights.items()}
        for symbol in context.prices:
            current = context.state.shares.get(symbol, 0.0) * context.prices[symbol]
            target = equity * clean_weights.get(symbol, 0.0)
            delta = target - current
            if abs(delta) >= max(5.0, equity * 0.001):
                intents.append(
                    OrderIntent(symbol, "buy" if delta > 0 else "sell", abs(delta), reason)
                )
        return sorted(intents, key=lambda order: order.side == "buy")


class PlainDCA(Strategy):
    name = "plain_dca"

    def generate(self, context: StrategyContext) -> list[OrderIntent]:
        if context.session_index == 0 or context.contribution_due:
            return self.invest_cash(context, list(context.prices), "scheduled_dca")
        return []


class ValueTiltedDCA(Strategy):
    name = "value_tilted_dca"

    def __init__(
        self,
        drawdown_threshold: float = 0.03,
        rsi_threshold: float = 40,
        lookback: int = 63,
        max_wait_sessions: int = 5,
        **params: Any,
    ) -> None:
        super().__init__(
            drawdown_threshold=drawdown_threshold,
            rsi_threshold=rsi_threshold,
            lookback=lookback,
            max_wait_sessions=max_wait_sessions,
            **params,
        )
        self.drawdown_threshold = drawdown_threshold
        self.rsi_threshold = rsi_threshold
        self.lookback = lookback
        self.max_wait_sessions = max_wait_sessions
        self.waiting = 0

    def generate(self, context: StrategyContext) -> list[OrderIntent]:
        if context.state.cash > max(1.0, context.contribution_amount * 0.05):
            self.waiting += 1
        else:
            self.waiting = 0
        if context.session_index == 0:
            self.waiting = self.max_wait_sessions
        selected: list[str] = []
        for symbol, history in context.history.items():
            if len(history) < max(self.lookback, 20):
                continue
            close = history["close"]
            drawdown = 1 - close.iloc[-1] / close.iloc[-self.lookback :].max()
            current_rsi = float(rsi(close).iloc[-1])
            if drawdown >= self.drawdown_threshold or current_rsi <= self.rsi_threshold:
                selected.append(symbol)
        forced = self.waiting >= self.max_wait_sessions
        if selected or forced:
            self.waiting = 0
            return self.invest_cash(
                context,
                selected or list(context.prices),
                "drawdown_or_rsi" if selected else "forced_dca_deadline",
            )
        return []


class TrendVolTarget(Strategy):
    name = "trend_vol_target"

    def __init__(
        self,
        fast_window: int = 50,
        slow_window: int = 200,
        vol_window: int = 20,
        target_volatility: float = 0.12,
        rebalance_sessions: int = 5,
        **params: Any,
    ) -> None:
        super().__init__(
            fast_window=fast_window,
            slow_window=slow_window,
            vol_window=vol_window,
            target_volatility=target_volatility,
            rebalance_sessions=rebalance_sessions,
            **params,
        )
        self.fast_window = fast_window
        self.slow_window = slow_window
        self.vol_window = vol_window
        self.target_volatility = target_volatility
        self.rebalance_sessions = rebalance_sessions

    def generate(self, context: StrategyContext) -> list[OrderIntent]:
        if context.session_index % self.rebalance_sessions != 0 and not context.contribution_due:
            return []
        raw: dict[str, float] = {}
        for symbol, history in context.history.items():
            if len(history) < self.slow_window:
                continue
            close = history["close"]
            trend_on = close.iloc[-self.fast_window :].mean() > close.iloc[-self.slow_window :].mean()
            vol = float(realized_volatility(close, self.vol_window).iloc[-1])
            if trend_on and np.isfinite(vol) and vol > 0:
                raw[symbol] = min(1.0, self.target_volatility / vol)
        if not raw:
            return self.rebalance(context, {}, "trend_risk_off")
        scale = min(1.0, 1 / sum(raw.values()))
        return self.rebalance(
            context, {symbol: weight * scale for symbol, weight in raw.items()}, "trend_vol_target"
        )


class MeanReversion(Strategy):
    name = "mean_reversion"

    def __init__(
        self,
        lookback: int = 20,
        entry_z: float = -1.5,
        exit_z: float = 0.0,
        max_weight: float = 0.5,
        **params: Any,
    ) -> None:
        super().__init__(
            lookback=lookback, entry_z=entry_z, exit_z=exit_z, max_weight=max_weight, **params
        )
        self.lookback = lookback
        self.entry_z = entry_z
        self.exit_z = exit_z
        self.max_weight = max_weight
        self.active: set[str] = set()

    def generate(self, context: StrategyContext) -> list[OrderIntent]:
        for symbol, history in context.history.items():
            if len(history) < self.lookback:
                continue
            close = history["close"].iloc[-self.lookback :]
            std = close.std(ddof=1)
            zscore = (close.iloc[-1] - close.mean()) / std if std > 0 else 0
            if zscore <= self.entry_z:
                self.active.add(symbol)
            elif zscore >= self.exit_z:
                self.active.discard(symbol)
        weights = {
            symbol: min(self.max_weight, 1 / len(self.active)) for symbol in self.active
        } if self.active else {}
        return self.rebalance(context, weights, "mean_reversion_zscore")


class AdaptiveEnsemble(Strategy):
    name = "adaptive_ensemble"

    def __init__(
        self,
        trend_window: int = 126,
        vol_window: int = 20,
        target_volatility: float = 0.12,
        rebalance_sessions: int = 21,
        **params: Any,
    ) -> None:
        super().__init__(
            trend_window=trend_window,
            vol_window=vol_window,
            target_volatility=target_volatility,
            rebalance_sessions=rebalance_sessions,
            **params,
        )
        self.trend_window = trend_window
        self.vol_window = vol_window
        self.target_volatility = target_volatility
        self.rebalance_sessions = rebalance_sessions

    def generate(self, context: StrategyContext) -> list[OrderIntent]:
        if context.session_index % self.rebalance_sessions != 0 and not context.contribution_due:
            return []
        scores: dict[str, float] = {}
        inverse_vol: dict[str, float] = {}
        for symbol, history in context.history.items():
            if len(history) < self.trend_window:
                continue
            close = history["close"]
            momentum = close.iloc[-1] / close.iloc[-self.trend_window] - 1
            short_reversal = -(close.iloc[-1] / close.iloc[-6] - 1)
            current_rsi = float(rsi(close).iloc[-1])
            quality = 1.0 if current_rsi < 70 else 0.4
            scores[symbol] = max(0.0, 0.7 * momentum + 0.3 * short_reversal) * quality
            vol = float(realized_volatility(close, self.vol_window).iloc[-1])
            inverse_vol[symbol] = 1 / max(vol, 0.05)
        positive = {symbol: score for symbol, score in scores.items() if score > 0}
        if not positive:
            return self.rebalance(context, {}, "ensemble_no_edge")
        raw = {symbol: positive[symbol] * inverse_vol[symbol] for symbol in positive}
        total = sum(raw.values())
        weights = {symbol: value / total for symbol, value in raw.items()}
        portfolio_vol_proxy = sum(
            weights[symbol] / inverse_vol[symbol] for symbol in weights
        )
        scale = min(1.0, self.target_volatility / max(portfolio_vol_proxy, 0.01))
        return self.rebalance(
            context,
            {symbol: weight * scale for symbol, weight in weights.items()},
            "regime_adaptive_ensemble",
        )


@dataclass
class _MLPrediction:
    probability: float
    confident_positive: bool


class ConformalML(Strategy):
    """Rolling gradient boosting with split-conformal classification sets."""

    name = "conformal_ml"

    def __init__(
        self,
        training_window: int = 756,
        min_training_rows: int = 252,
        calibration_fraction: float = 0.2,
        alpha: float = 0.15,
        rebalance_sessions: int = 21,
        random_seed: int = 7,
        **params: Any,
    ) -> None:
        super().__init__(
            training_window=training_window,
            min_training_rows=min_training_rows,
            calibration_fraction=calibration_fraction,
            alpha=alpha,
            rebalance_sessions=rebalance_sessions,
            random_seed=random_seed,
            **params,
        )
        self.training_window = training_window
        self.min_training_rows = min_training_rows
        self.calibration_fraction = calibration_fraction
        self.alpha = alpha
        self.rebalance_sessions = rebalance_sessions
        self.random_seed = random_seed
        self.last_weights: dict[str, float] = {}

    def _predict(self, history: pd.DataFrame) -> _MLPrediction | None:
        features = feature_frame(history)
        future_return = history["close"].pct_change().shift(-1)
        labeled = features.loc[future_return.notna()].dropna()
        if len(labeled) < self.min_training_rows:
            return None
        labeled = labeled.iloc[-self.training_window :]
        labels = (future_return.loc[labeled.index] > 0).astype(int)
        split = max(50, int(len(labeled) * (1 - self.calibration_fraction)))
        if split >= len(labeled) - 20 or labels.iloc[:split].nunique() < 2:
            return None
        model = HistGradientBoostingClassifier(
            max_iter=100,
            max_leaf_nodes=15,
            learning_rate=0.05,
            l2_regularization=1.0,
            random_state=self.random_seed,
        )
        model.fit(labeled.iloc[:split], labels.iloc[:split])
        cal_prob = model.predict_proba(labeled.iloc[split:])
        cal_y = labels.iloc[split:].to_numpy()
        nonconformity = 1 - cal_prob[np.arange(len(cal_y)), cal_y]
        rank = min(len(nonconformity) - 1, int(np.ceil((len(nonconformity) + 1) * (1 - self.alpha))) - 1)
        threshold = float(np.sort(nonconformity)[rank])
        latest = features.iloc[[-1]].dropna()
        if latest.empty:
            return None
        probability = float(model.predict_proba(latest)[0, 1])
        include_positive = 1 - probability <= threshold
        include_negative = probability <= threshold
        return _MLPrediction(probability, include_positive and not include_negative)

    def generate(self, context: StrategyContext) -> list[OrderIntent]:
        if context.session_index % self.rebalance_sessions != 0:
            if context.contribution_due and self.last_weights:
                return self.rebalance(context, self.last_weights, "conformal_allocation_refresh")
            return []
        predictions = {
            symbol: prediction
            for symbol, history in context.history.items()
            if (prediction := self._predict(history)) is not None
        }
        selected = {
            symbol: prediction.probability - 0.5
            for symbol, prediction in predictions.items()
            if prediction.confident_positive
        }
        total = sum(selected.values())
        weights = {symbol: score / total for symbol, score in selected.items()} if total > 0 else {}
        self.last_weights = weights
        return self.rebalance(context, self.last_weights, "rolling_conformal_ml")


STRATEGIES: dict[str, type[Strategy]] = {
    strategy.name: strategy
    for strategy in [PlainDCA, ValueTiltedDCA, TrendVolTarget, MeanReversion, AdaptiveEnsemble, ConformalML]
}


STRATEGY_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "plain_dca",
        "label": "Plain DCA",
        "description": "Unconditional contribution schedule; the control strategy.",
        "params": [],
    },
    {
        "name": "value_tilted_dca",
        "label": "Value-tilted DCA",
        "description": "Buys on drawdowns or low RSI, with a forced deadline to cap cash drag.",
        "params": [
            {"key": "drawdown_threshold", "label": "Drawdown threshold", "value": 0.03, "min": 0.01, "max": 0.2, "step": 0.01},
            {"key": "rsi_threshold", "label": "RSI threshold", "value": 40, "min": 20, "max": 60, "step": 1},
            {"key": "lookback", "label": "Drawdown lookback", "value": 63, "min": 20, "max": 252, "step": 1},
            {"key": "max_wait_sessions", "label": "Forced-buy sessions", "value": 5, "min": 1, "max": 63, "step": 1},
        ],
    },
    {
        "name": "trend_vol_target",
        "label": "Trend + volatility target",
        "description": "Time-series trend filter with inverse-volatility exposure scaling.",
        "params": [
            {"key": "fast_window", "label": "Fast window", "value": 50, "min": 5, "max": 150, "step": 1},
            {"key": "slow_window", "label": "Slow window", "value": 200, "min": 50, "max": 400, "step": 1},
            {"key": "target_volatility", "label": "Target volatility", "value": 0.12, "min": 0.04, "max": 0.3, "step": 0.01},
        ],
    },
    {
        "name": "mean_reversion",
        "label": "Mean reversion",
        "description": "Long-only rolling z-score entries with explicit exits and allocation caps.",
        "params": [
            {"key": "lookback", "label": "Lookback", "value": 20, "min": 5, "max": 100, "step": 1},
            {"key": "entry_z", "label": "Entry z-score", "value": -1.5, "min": -3, "max": -0.5, "step": 0.1},
            {"key": "exit_z", "label": "Exit z-score", "value": 0, "min": -0.5, "max": 1, "step": 0.1},
        ],
    },
    {
        "name": "adaptive_ensemble",
        "label": "Regime-adaptive ensemble",
        "description": "Combines momentum, short reversal, RSI gating, and inverse-volatility weighting.",
        "params": [
            {"key": "trend_window", "label": "Trend window", "value": 126, "min": 21, "max": 252, "step": 1},
            {"key": "target_volatility", "label": "Target volatility", "value": 0.12, "min": 0.04, "max": 0.3, "step": 0.01},
            {"key": "rebalance_sessions", "label": "Rebalance sessions", "value": 21, "min": 1, "max": 63, "step": 1},
        ],
    },
    {
        "name": "conformal_ml",
        "label": "Rolling conformal ML",
        "description": "Walk-forward gradient boosting; trades only when the split-conformal set excludes the negative class.",
        "params": [
            {"key": "training_window", "label": "Training window", "value": 756, "min": 252, "max": 1500, "step": 21},
            {"key": "alpha", "label": "Miscoverage alpha", "value": 0.15, "min": 0.05, "max": 0.4, "step": 0.05},
            {"key": "rebalance_sessions", "label": "Refit/rebalance sessions", "value": 21, "min": 5, "max": 63, "step": 1},
        ],
    },
]


def build_strategy(name: str, params: dict[str, Any] | None = None) -> Strategy:
    try:
        strategy_type = STRATEGIES[name]
    except KeyError as exc:
        raise ValueError(f"Unknown strategy: {name}") from exc
    return strategy_type(**(params or {}))
