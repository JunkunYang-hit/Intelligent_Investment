"""C 的订单管理：生成订单编号并维护订单状态。"""

from __future__ import annotations

from itertools import count

from quant_demo.models import Order, OrderRequest, OrderStatus


class OrderManagementSystem:
    def __init__(self) -> None:
        self._ids = count(1)
        self.orders: list[Order] = []

    def create(self, request: OrderRequest) -> Order:
        if request.quantity <= 0:
            raise ValueError("订单数量必须大于 0")
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
        if order.status is not OrderStatus.CREATED:
            raise ValueError(f"订单 {order.order_id} 无法从 {order.status.value} 转为 REJECTED")
        order.status = OrderStatus.REJECTED
        order.reject_reason = reason
        order.price = None

    @staticmethod
    def fill(order: Order, price: float) -> None:
        if order.status is not OrderStatus.CREATED:
            raise ValueError(f"订单 {order.order_id} 无法从 {order.status.value} 转为 FILLED")
        if price <= 0:
            raise ValueError("成交价格必须大于 0")
        order.status = OrderStatus.FILLED
        order.price = price
        order.reject_reason = None

    @staticmethod
    def cancel(order: Order, reason: str = "") -> None:
        if order.status is not OrderStatus.CREATED:
            raise ValueError(f"订单 {order.order_id} 无法从 {order.status.value} 转为 CANCELLED")
        order.status = OrderStatus.CANCELLED
        order.reject_reason = reason or None
        order.price = None
