"""C 的订单管理：生成订单编号并维护订单状态。"""

from __future__ import annotations

from itertools import count

from quant_demo.models import Order, OrderRequest, OrderStatus


class OrderManagementSystem:
    def __init__(self) -> None:
        self._ids = count(1)
        self.orders: list[Order] = []

    def create(self, request: OrderRequest) -> Order:
        order = Order(
            order_id=f"ORDER_{next(self._ids):06d}",
            symbol=request.symbol,
            side=request.side,
            quantity=request.quantity,
            created_at=request.created_at,
        )
        self.orders.append(order)
        return order

    @staticmethod
    def reject(order: Order, reason: str) -> None:
        order.status = OrderStatus.REJECTED
        order.reject_reason = reason

    @staticmethod
    def fill(order: Order, price: float) -> None:
        order.status = OrderStatus.FILLED
        order.price = price
