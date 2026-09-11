"""验证信号在下一根 Bar 开盘成交，避免使用未来价格。"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from quant_demo.models import Bar, OrderRequest, OrderStatus, Side
from quant_demo.modes import BacktestEngine
from quant_demo.strategy.base import Strategy
from quant_demo.trading import (
    Account,
    BrokerSimulator,
    OrderManagementSystem,
    RiskManager,
    TargetWeightSizer,
)


class BuyThenSell(Strategy):
    def on_bar(self, bar, history):
        size = len(history[bar.symbol])
        return Side.BUY if size == 1 else Side.SELL if size == 3 else None


def test_signal_is_filled_on_next_bar_open() -> None:
    start = datetime(2025, 1, 1)
    opens = [10.0, 11.0, 12.0, 13.0]
    bars = [Bar("510300.SH", start + timedelta(days=i), p, p, p, p, 1000) for i, p in enumerate(opens)]
    engine = BacktestEngine(
        BuyThenSell(),
        Account(100_000),
        TargetWeightSizer(0.2, 100),
        RiskManager(0.3, 0.3, 100),
        OrderManagementSystem(),
        BrokerSimulator(slippage_bps=0),
    )
    result = engine.run(bars)
    assert [item.price for item in result.trades] == [11.0, 13.0]
    assert result.trades[0].datetime == bars[1].datetime
    assert result.metrics["trade_count"] == 2
    assert result.metadata["bar_count"] == 4
    assert result.metadata["filled_order_count"] == 2


def _engine(strategy: Strategy | None = None) -> BacktestEngine:
    return BacktestEngine(
        strategy or BuyThenSell(),
        Account(100_000),
        TargetWeightSizer(0.2, 100),
        RiskManager(0.3, 0.3, 100),
        OrderManagementSystem(),
        BrokerSimulator(slippage_bps=0),
    )


def _bars(prices: list[float], start: datetime | None = None) -> list[Bar]:
    at = start or datetime(2025, 1, 1)
    return [Bar("510300.SH", at + timedelta(days=i), price, price, price, price, 1000) for i, price in enumerate(prices)]


def test_rejects_empty_and_duplicate_bars() -> None:
    with pytest.raises(ValueError, match="不能为空"):
        _engine().run([])

    duplicate = _bars([10]) * 2
    with pytest.raises(ValueError, match="重复 Bar"):
        _engine().run(duplicate)


def test_rejects_inconsistent_timestamps_on_same_day() -> None:
    start = datetime(2025, 1, 1)
    bars = [
        Bar("A", start, 10, 10, 10, 10, 1000),
        Bar("B", start.replace(hour=1), 10, 10, 10, 10, 1000),
    ]
    with pytest.raises(ValueError, match="时间戳不一致"):
        _engine().run(bars)


def test_engine_cannot_be_reused_after_run() -> None:
    engine = _engine()
    engine.run(_bars([10, 11, 12, 13]))
    with pytest.raises(RuntimeError, match="只能运行一次"):
        engine.run(_bars([10, 11, 12, 13]))


def test_oms_rejects_illegal_transitions_and_supports_cancel() -> None:
    oms = OrderManagementSystem()
    created_at = datetime(2025, 1, 1)
    with pytest.raises(ValueError, match="数量必须大于 0"):
        oms.create(OrderRequest("A", Side.BUY, 0, created_at))

    order = oms.create(OrderRequest("A", Side.BUY, 100, created_at))
    oms.fill(order, 10)
    assert order.status is OrderStatus.FILLED
    with pytest.raises(ValueError, match="无法从 FILLED"):
        oms.reject(order, "late rejection")

    cancellable = oms.create(OrderRequest("A", Side.BUY, 100, created_at))
    oms.cancel(cancellable, "backtest ended")
    assert cancellable.status is OrderStatus.CANCELLED
    with pytest.raises(ValueError, match="无法从 CANCELLED"):
        oms.fill(cancellable, 10)


def test_broker_validates_order_state_and_execution_time() -> None:
    with pytest.raises(ValueError, match="不能为负"):
        BrokerSimulator(commission_rate=-0.01)

    broker = BrokerSimulator(slippage_bps=0)
    created_at = datetime(2025, 1, 1)
    order = OrderManagementSystem().create(OrderRequest("A", Side.BUY, 100, created_at))
    bar = Bar("A", created_at, 10, 10, 10, 10, 1000)
    with pytest.raises(ValueError, match="晚于订单创建时间"):
        broker.execute_at_open(order, bar)

    order.status = OrderStatus.FILLED
    with pytest.raises(ValueError, match="CREATED"):
        broker.execute_at_open(order, Bar("A", created_at + timedelta(days=1), 10, 10, 10, 10, 1000))
