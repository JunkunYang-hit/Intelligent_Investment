"""验证订单只能从 CREATED 进入一次最终状态，避免重复成交。"""

from datetime import datetime

import pytest

from quant_demo.models import Bar, OrderRequest, Side
from quant_demo.trading import BrokerSimulator, OrderManagementSystem


def test_filled_order_cannot_be_executed_or_filled_twice() -> None:
    at = datetime(2025, 1, 2)
    oms = OrderManagementSystem()
    order = oms.create(OrderRequest("510300.SH", Side.BUY, 100, at))
    broker = BrokerSimulator(slippage_bps=0)
    bar = Bar("510300.SH", at, 10.0, 10.0, 10.0, 10.0, 1_000)

    trade = broker.execute_at_open(order, bar)
    oms.fill(order, trade.price)

    with pytest.raises(ValueError, match="只有 CREATED 订单可以成交"):
        broker.execute_at_open(order, bar)
    with pytest.raises(ValueError, match="只有 CREATED 订单可以完成"):
        oms.fill(order, trade.price)


def test_rejected_order_cannot_be_filled() -> None:
    at = datetime(2025, 1, 2)
    oms = OrderManagementSystem()
    order = oms.create(OrderRequest("510300.SH", Side.BUY, 100, at))
    oms.reject(order, "test")
    with pytest.raises(ValueError, match="只有 CREATED 订单可以完成"):
        oms.fill(order, 10.0)
