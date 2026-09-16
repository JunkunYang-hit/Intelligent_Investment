"""本地模拟网关：不依赖任何外部环境即可演示完整下单闭环。

用于课程演示、单元测试与策略联调。撮合规则（简化）：
  - limit 单：报单价即刻全额成交（不模拟排队与部分成交）；
  - market 单：按 ``set_last_close`` 设置的最新收盘价成交，
    未设置过收盘价时拒单；
  - 不计佣金与滑点（回测成本由 trading/broker.py 的
    BrokerSimulator 负责，二者职责不同：本网关只验证通道语义）。
"""

from __future__ import annotations

import itertools

from quant_demo.models import Order, OrderRequest, OrderStatus, Position, Side

from .base import BrokerGateway


class PaperBrokerGateway(BrokerGateway):
    name = "paper"

    def __init__(self, initial_cash: float = 1_000_000.0) -> None:
        self._cash = initial_cash
        self._orders: dict[str, Order] = {}
        self._positions: dict[str, Position] = {}
        self._last_close: dict[str, float] = {}
        self._seq = itertools.count(1)
        self._connected = False

    # ---- 连接管理 ---------------------------------------------------------- #
    def connect(self) -> bool:
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False

    def _ensure_connected(self) -> None:
        if not self._connected:
            raise ConnectionError("paper 网关未连接，请先调用 connect()")

    # ---- 行情注入（market 单成交价来源） ------------------------------------ #
    def set_last_close(self, symbol: str, price: float) -> None:
        """由引擎在每根 Bar 推进时注入最新收盘价。"""
        self._last_close[symbol] = price

    # ---- 交易接口 ---------------------------------------------------------- #
    def place_order(
        self,
        req: OrderRequest,
        order_type: str = "limit",
        price: float | None = None,
    ) -> str:
        self._ensure_connected()
        broker_id = f"paper-{next(self._seq):06d}"

        fill_price: float | None
        if order_type == "limit":
            fill_price = price
            if fill_price is None or fill_price <= 0:
                raise ValueError("limit 单必须提供正数价格")
        elif order_type == "market":
            fill_price = self._last_close.get(req.symbol)
        else:
            raise ValueError(f"不支持的订单类型: {order_type}")

        order = Order(
            order_id=broker_id,
            symbol=req.symbol,
            side=req.side,
            quantity=req.quantity,
            created_at=req.created_at,
        )

        if fill_price is None:
            order.status = OrderStatus.REJECTED
            order.reject_reason = "market单无最新价可成交"
            self._orders[broker_id] = order
            return broker_id

        amount = req.quantity * fill_price
        if req.side == Side.BUY and amount > self._cash:
            order.status = OrderStatus.REJECTED
            order.reject_reason = f"资金不足(需{amount:.0f}, 可用{self._cash:.0f})"
            self._orders[broker_id] = order
            return broker_id
        if req.side == Side.SELL:
            pos = self._positions.get(req.symbol)
            if pos is None or pos.quantity < req.quantity:
                order.status = OrderStatus.REJECTED
                order.reject_reason = "持仓不足"
                self._orders[broker_id] = order
                return broker_id

        # 撮合成交（简化：全额即时成交）
        self._apply_fill(req.symbol, req.side, req.quantity, fill_price)
        order.status = OrderStatus.FILLED
        order.price = fill_price
        self._orders[broker_id] = order
        return broker_id

    def cancel_order(self, broker_order_id: str) -> bool:
        self._ensure_connected()
        order = self._orders.get(broker_order_id)
        if order is None or order.status is not OrderStatus.CREATED:
            return False
        order.status = OrderStatus.CANCELLED
        return True

    def query_order(self, broker_order_id: str) -> Order | None:
        return self._orders.get(broker_order_id)

    def query_positions(self) -> list[Position]:
        return [p for p in self._positions.values() if p.quantity > 0]

    def query_cash(self) -> float:
        return self._cash

    # ---- 内部：成交入账 ---------------------------------------------------- #
    def _apply_fill(self, symbol: str, side: Side, quantity: int, price: float) -> None:
        pos = self._positions.setdefault(symbol, Position(symbol=symbol))
        if side == Side.BUY:
            total_cost = pos.average_cost * pos.quantity + price * quantity
            pos.quantity += quantity
            pos.average_cost = total_cost / pos.quantity if pos.quantity else 0.0
            self._cash -= price * quantity
        else:
            proceeds = (price - pos.average_cost) * quantity
            pos.realized_pnl += proceeds
            pos.quantity -= quantity
            self._cash += price * quantity
        pos.last_price = price
