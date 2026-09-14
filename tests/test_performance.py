"""验证收益率和最大回撤等基础绩效计算。"""

from datetime import datetime, timedelta

import pytest

from quant_demo.analytics import calculate_performance
from quant_demo.models import EquityPoint, Side, Trade


def test_performance_drawdown_and_return() -> None:
    start = datetime(2025, 1, 1)
    curve = [
        EquityPoint(start + timedelta(days=i), 0, value, value)
        for i, value in enumerate([100.0, 110.0, 88.0, 121.0])
    ]
    metrics = calculate_performance(curve, [])
    assert metrics["total_return"] == pytest.approx(0.21)
    assert metrics["max_drawdown"] == pytest.approx(0.20)
    assert metrics["trade_count"] == 0


def _trade(trade_id: str, side: Side, quantity: int, price: float) -> Trade:
    return Trade(trade_id, f"O-{trade_id}", "510300.SH", side, quantity, price, datetime(2025, 1, 1), 0)


def test_win_rate_counts_complete_position_cycles() -> None:
    curve = [EquityPoint(datetime(2025, 1, 1), 100, 0, 100)]
    trades = [
        _trade("T1", Side.BUY, 100, 10),
        _trade("T2", Side.SELL, 50, 12),  # 部分卖出，还不算一个完整周期
        _trade("T3", Side.SELL, 50, 11),  # 第一个周期整体盈利
        _trade("T4", Side.BUY, 100, 10),
        _trade("T5", Side.SELL, 100, 9),  # 第二个周期亏损
    ]
    metrics = calculate_performance(curve, trades)
    assert metrics["closed_trade_count"] == 2
    assert metrics["win_rate"] == pytest.approx(0.5)


def test_performance_rejects_non_positive_equity() -> None:
    curve = [EquityPoint(datetime(2025, 1, 1), 0, 0, 0)]
    with pytest.raises(ValueError, match="净值必须大于 0"):
        calculate_performance(curve, [])
