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
    """计算第一版 Demo 使用的少量、常见绩效指标。

    Sharpe 默认无风险收益率为 0，使用日收益率样本标准差；胜率按一次持仓
    从建立到完全清仓的完整买卖周期计算，而不是按每次部分卖出计算。
    """
    if not equity_curve:
        return _empty_metrics()
    # 防御性处理：按时间排序，同一时刻只使用最后一个净值点。
    points_by_time = {point.datetime: point for point in equity_curve}
    points = [points_by_time[at] for at in sorted(points_by_time)]
    equities = [point.total_equity for point in points]
    if any(equity <= 0 for equity in equities):
        raise ValueError("账户净值必须大于 0")
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
    """统计完整买卖周期及其中的盈利周期，适用于第一版纯多头。"""
    # 每只股票保存：持仓数量、平均成本、本轮已实现盈亏。
    states: dict[str, tuple[int, float, float]] = defaultdict(lambda: (0, 0.0, 0.0))
    closed = wins = 0
    for trade in trades:
        quantity, average_cost, cycle_pnl = states[trade.symbol]
        if trade.side is Side.BUY:
            new_quantity = quantity + trade.quantity
            average_cost = (quantity * average_cost + trade.gross_amount + trade.total_fee) / new_quantity
            quantity = new_quantity
        else:
            if trade.quantity > quantity:
                raise ValueError("成交记录中存在卖出数量超过持仓的情况")
            pnl = (trade.price - average_cost) * trade.quantity - trade.total_fee
            cycle_pnl += pnl
            quantity -= trade.quantity
            if quantity == 0:
                closed += 1
                wins += int(cycle_pnl > 0)
                average_cost = 0.0
                cycle_pnl = 0.0
        states[trade.symbol] = quantity, average_cost, cycle_pnl
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
