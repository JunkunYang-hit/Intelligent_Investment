"""B 的双均线参考策略，展示统一策略接口的用法。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from quant_demo.models import Bar, Side
from quant_demo.strategy.base import Strategy


class DualMovingAverageStrategy(Strategy):
    """日线双均线：仅在发生交叉时发出一次方向信号。"""

    def __init__(self, short_window: int = 5, long_window: int = 20) -> None:
        if not 1 <= short_window < long_window:
            raise ValueError("窗口必须满足 1 <= short_window < long_window")
        self.short_window = short_window
        self.long_window = long_window

    def on_bar(self, bar: Bar, history: Mapping[str, Sequence[Bar]]) -> Side | None:
        closes = [item.close for item in history.get(bar.symbol, ())]
        if len(closes) < self.long_window + 1:
            return None
        previous = closes[:-1]
        short_now = sum(closes[-self.short_window :]) / self.short_window
        long_now = sum(closes[-self.long_window :]) / self.long_window
        short_previous = sum(previous[-self.short_window :]) / self.short_window
        long_previous = sum(previous[-self.long_window :]) / self.long_window
        if short_previous <= long_previous and short_now > long_now:
            return Side.BUY
        if short_previous >= long_previous and short_now < long_now:
            return Side.SELL
        return None
