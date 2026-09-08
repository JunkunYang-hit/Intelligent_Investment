"""C 的模拟券商：把通过风控的订单转换为成交记录。"""

from __future__ import annotations

from itertools import count

from quant_demo.models import Bar, Order, Side, Trade


class BrokerSimulator:
    """以下一根 Bar 开盘价成交，并加入固定滑点、佣金和卖出印花税。"""

    def __init__(
        self,
        commission_rate: float = 0.0003,
        minimum_commission: float = 5.0,
        sell_stamp_duty_rate: float = 0.0005,
        slippage_bps: float = 2.0,
    ) -> None:
        self.commission_rate = commission_rate
        self.minimum_commission = minimum_commission
        self.sell_stamp_duty_rate = sell_stamp_duty_rate
        self.slippage_bps = slippage_bps
        self._ids = count(1)

    def execute_at_open(self, order: Order, bar: Bar) -> Trade:
        if order.symbol != bar.symbol:
            raise ValueError("订单标的与行情标的不一致")
        direction = 1 if order.side is Side.BUY else -1
        price = bar.open * (1 + direction * self.slippage_bps / 10_000)
        amount = price * order.quantity
        commission = max(self.minimum_commission, amount * self.commission_rate)
        stamp_duty = amount * self.sell_stamp_duty_rate if order.side is Side.SELL else 0.0
        return Trade(
            trade_id=f"TRADE_{next(self._ids):06d}",
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=price,
            datetime=bar.datetime,
            commission=commission,
            stamp_duty=stamp_duty,
        )
