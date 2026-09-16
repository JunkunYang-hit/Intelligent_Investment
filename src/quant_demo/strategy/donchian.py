"""唐奇安通道突破策略：价格突破前 N 日最高/最低价时发出一次信号。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from quant_demo.models import Bar, Side
from quant_demo.strategy.base import Strategy
from quant_demo.strategy.indicators import highest, lowest


class DonchianBreakoutStrategy(Strategy):
    """经典趋势突破：当前收盘价突破**不含当天**的前 N 日通道时发出一次信号。

    通道定义（第 T 日判断时）：

    - 上轨 ``upper = max(high[T-lookback .. T-1])``（不含第 T 日自身）
    - 下轨 ``lower = min(low[T-lookback .. T-1])``（不含第 T 日自身）

    信号采用穿越方式，避免突破后每天重复：

    - 上一根收盘 <= 上一根上轨，且当前收盘 > 当前上轨：BUY
    - 上一根收盘 >= 上一根下轨，且当前收盘 < 当前下轨：SELL
    - 其他情况：None

    每根 Bar 与"截至上一根 Bar"的通道比较，当前 Bar 的 high/low 不参与
    通道计算，因此不存在"用自己突破自己"的未来数据问题。
    预热期：至少需要 ``lookback + 2`` 根 Bar（含当前 Bar）。
    """

    def __init__(self, lookback: int = 20) -> None:
        if lookback < 1:
            raise ValueError("lookback 必须大于 0")
        self.lookback = lookback

    def on_bar(self, bar: Bar, history: Mapping[str, Sequence[Bar]]) -> Side | None:
        bars = history.get(bar.symbol, ())
        if len(bars) < self.lookback + 2:
            return None
        closes = [item.close for item in bars]
        highs = [item.high for item in bars]
        lows = [item.low for item in bars]
        upper_channel = highest(highs, self.lookback)
        lower_channel = lowest(lows, self.lookback)
        # 第 T 日的参考通道 = 截至第 T-1 日的滚动极值，即序列倒数第 2 个值。
        previous_upper, current_upper = upper_channel[-3], upper_channel[-2]
        previous_lower, current_lower = lower_channel[-3], lower_channel[-2]
        if None in (previous_upper, current_upper, previous_lower, current_lower):
            return None
        previous_close, current_close = closes[-2], closes[-1]
        if previous_close <= previous_upper and current_close > current_upper:
            return Side.BUY
        if previous_close >= previous_lower and current_close < current_lower:
            return Side.SELL
        return None
