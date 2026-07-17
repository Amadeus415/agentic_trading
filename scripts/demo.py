from __future__ import annotations

import json

from edgecraft.data import synthetic_market_data
from edgecraft.models import BacktestRequest, StrategySpec, ValidationConfig
from edgecraft.research import run_research


def main() -> None:
    request = BacktestRequest(
        symbols=["SPY", "QQQ"],
        initial_capital=10_000,
        contribution_amount=250,
        contribution_frequency="weekly",
        strategies=[
            StrategySpec(name="plain_dca"),
            StrategySpec(name="value_tilted_dca"),
            StrategySpec(name="trend_vol_target"),
            StrategySpec(name="adaptive_ensemble"),
        ],
        validation=ValidationConfig(bootstrap_samples=100, bootstrap_block_size=20, cscv_slices=8),
    )
    result = run_research(synthetic_market_data(request.symbols, periods=1_500), request)
    summary = {
        item["strategy"]: {
            key: item["metrics"].get(key)
            for key in ["ending_equity", "annual_return", "sharpe", "max_drawdown", "deflated_sharpe_probability"]
        }
        for item in result["results"]
    }
    print(json.dumps({"meta": result["meta"], "validation": result["validation"], "results": summary}, indent=2))


if __name__ == "__main__":
    main()
