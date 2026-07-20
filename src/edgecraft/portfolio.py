from __future__ import annotations

from typing import Any

from edgecraft.execution_models import PortfolioSnapshot


def analyze_portfolio(snapshot: PortfolioSnapshot) -> dict[str, Any]:
    positions = []
    total_positions = sum(position.market_value for position in snapshot.positions)
    denominator = snapshot.portfolio_value
    for position in sorted(snapshot.positions, key=lambda item: item.market_value, reverse=True):
        unrealized = (
            position.market_value - position.quantity * position.average_cost
            if position.average_cost is not None
            else None
        )
        positions.append(
            {
                "symbol": position.symbol,
                "quantity": position.quantity,
                "market_price": position.market_price,
                "market_value": round(position.market_value, 2),
                "weight": position.market_value / denominator,
                "average_cost": position.average_cost,
                "unrealized_pnl": round(unrealized, 2) if unrealized is not None else None,
            }
        )
    weights = [item["weight"] for item in positions]
    return {
        "account_id": snapshot.account_id,
        "nickname": snapshot.nickname,
        "agentic_allowed": snapshot.agentic_allowed,
        "as_of": snapshot.as_of.isoformat(),
        "portfolio_value": snapshot.portfolio_value,
        "buying_power": snapshot.buying_power,
        "cash_weight": snapshot.buying_power / denominator,
        "invested_value": round(total_positions, 2),
        "position_count": len(positions),
        "largest_position_weight": max(weights, default=0.0),
        "concentration_hhi": sum(weight**2 for weight in weights),
        "unaccounted_value": round(
            snapshot.portfolio_value - snapshot.buying_power - total_positions, 2
        ),
        "positions": positions,
    }
