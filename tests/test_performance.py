"""验证收益率和最大回撤等基础绩效计算。"""

from datetime import datetime, timedelta

import pytest

from quant_demo.analytics import calculate_performance
from quant_demo.models import EquityPoint


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
