"""RSI 阈值穿越策略：超卖回升买入，超买回落卖出。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from quant_demo.models import Bar, Side
from quant_demo.strategy.base import Strategy
from quant_demo.strategy.indicators import rsi


class RSIStrategy(Strategy):
    """只在 RSI 穿越超卖/超买阈值时发出一次信号，不每天重复交易。

    - RSI 从 <= oversold 上穿 oversold：BUY
    - RSI 从 >= overbought 下穿 overbought：SELL
    - 其他情况：None

    预热期：至少需要 ``period + 2`` 根 Bar（含当前 Bar）。
    """

    def __init__(self, period: int = 14, oversold: float = 30.0, overbought: float = 70.0) -> None:
        if period < 1:
            raise ValueError("period 必须大于 0")
        if not 0 <= oversold < overbought <= 100:
            raise ValueError("阈值必须满足 0 <= oversold < overbought <= 100")
        self.period = period
        self.oversold = float(oversold)
        self.overbought = float(overbought)

    def on_bar(self, bar: Bar, history: Mapping[str, Sequence[Bar]]) -> Side | None:
        closes = [item.close for item in history.get(bar.symbol, ())]
        if len(closes) < self.period + 2:
            return None
        values = rsi(closes, self.period)
        previous, current = values[-2], values[-1]
        if previous is None or current is None:
            return None
        if previous <= self.oversold and current > self.oversold:
            return Side.BUY
        if previous >= self.overbought and current < self.overbought:
            return Side.SELL
        return None
