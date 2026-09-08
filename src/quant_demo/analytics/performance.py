"""D（绩效模块）：从净值曲线与成交记录纯计算指标。"""

from __future__ import annotations

import math
from collections import defaultdict

from quant_demo.models import EquityPoint, Side, Trade


def calculate_performance(
    equity_curve: list[EquityPoint],
    trades: list[Trade],
    annual_trading_days: int = 252,
) -> dict[str, float | int]:
    if not equity_curve:
        return _empty_metrics()
    equities = [point.total_equity for point in equity_curve]
    returns = [current / previous - 1 for previous, current in zip(equities, equities[1:]) if previous]
    total_return = equities[-1] / equities[0] - 1 if equities[0] else 0.0
    periods = max(1, len(equities) - 1)
    annualized_return = (1 + total_return) ** (annual_trading_days / periods) - 1 if total_return > -1 else -1.0

    peak = equities[0]
    max_drawdown = 0.0
    for equity in equities:
        peak = max(peak, equity)
        drawdown = equity / peak - 1 if peak else 0.0
        max_drawdown = min(max_drawdown, drawdown)

    sharpe = 0.0
    if len(returns) > 1:
        mean = sum(returns) / len(returns)
        variance = sum((item - mean) ** 2 for item in returns) / (len(returns) - 1)
        if variance > 0:
            sharpe = mean / math.sqrt(variance) * math.sqrt(annual_trading_days)

    round_trips, wins = _closed_trade_stats(trades)
    return {
        "initial_equity": equities[0],
        "final_equity": equities[-1],
        "total_return": total_return,
        "annualized_return": annualized_return,
        "max_drawdown": abs(max_drawdown),
        "sharpe_ratio": sharpe,
        "trade_count": len(trades),
        "closed_trade_count": round_trips,
        "win_rate": wins / round_trips if round_trips else 0.0,
        "total_fees": sum(trade.total_fee for trade in trades),
    }


def _closed_trade_stats(trades: list[Trade]) -> tuple[int, int]:
    """按移动平均成本统计每次卖出是否盈利，适用于第一版纯多头。"""
    states: dict[str, tuple[int, float]] = defaultdict(lambda: (0, 0.0))
    closed = wins = 0
    for trade in trades:
        quantity, average_cost = states[trade.symbol]
        if trade.side is Side.BUY:
            new_quantity = quantity + trade.quantity
            average_cost = (quantity * average_cost + trade.gross_amount + trade.total_fee) / new_quantity
            quantity = new_quantity
        else:
            pnl = (trade.price - average_cost) * trade.quantity - trade.total_fee
            closed += 1
            wins += int(pnl > 0)
            quantity -= trade.quantity
            if quantity == 0:
                average_cost = 0.0
        states[trade.symbol] = quantity, average_cost
    return closed, wins


def _empty_metrics() -> dict[str, float | int]:
    return {
        "initial_equity": 0.0,
        "final_equity": 0.0,
        "total_return": 0.0,
        "annualized_return": 0.0,
        "max_drawdown": 0.0,
        "sharpe_ratio": 0.0,
        "trade_count": 0,
        "closed_trade_count": 0,
        "win_rate": 0.0,
        "total_fees": 0.0,
    }

