"""B 的双均线参考策略，展示统一策略接口的用法。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from quant_demo.models import Bar, Side
from quant_demo.strategy.base import Strategy
from quant_demo.strategy.indicators import sma


class DualMovingAverageStrategy(Strategy):
    """日线双均线：仅在发生交叉时发出一次方向信号。

    - 短均线上穿长均线（金叉）：BUY
    - 短均线下穿长均线（死叉）：SELL
    - 其他情况：None

    预热期：至少需要 ``long_window + 1`` 根 Bar（含当前 Bar）。
    """

    def __init__(self, short_window: int = 5, long_window: int = 20) -> None:
        if not 1 <= short_window < long_window:
            raise ValueError("窗口必须满足 1 <= short_window < long_window")
        self.short_window = short_window
        self.long_window = long_window

    def on_bar(self, bar: Bar, history: Mapping[str, Sequence[Bar]]) -> Side | None:
        closes = [item.close for item in history.get(bar.symbol, ())]
        if len(closes) < self.long_window + 1:
            return None
        short_ma = sma(closes, self.short_window)
        long_ma = sma(closes, self.long_window)
        short_previous, short_now = short_ma[-2], short_ma[-1]
        long_previous, long_now = long_ma[-2], long_ma[-1]
        # 长度检查已保证这四个值不为 None。
        if short_previous <= long_previous and short_now > long_now:
            return Side.BUY
        if short_previous >= long_previous and short_now < long_now:
            return Side.SELL
        return None
