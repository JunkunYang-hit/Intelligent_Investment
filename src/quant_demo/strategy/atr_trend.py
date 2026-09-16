"""ATR 波动率感知趋势策略：价格显著偏离趋势均线时发出一次信号。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from quant_demo.models import Bar, Side
from quant_demo.strategy.base import Strategy
from quant_demo.strategy.indicators import atr, sma


class ATRTrendStrategy(Strategy):
    """以均线为趋势中枢、ATR 为波动尺度：偏离超过正常波动才交易。

    轨道定义：

    - 上轨 ``upper = MA(ma_window) + atr_multiplier * ATR(atr_period)``
    - 下轨 ``lower = MA(ma_window) - atr_multiplier * ATR(atr_period)``

    信号采用穿越方式，避免偏离持续时每天重复：

    - 收盘价上穿上轨（向上突破显著超过正常波动）：BUY
    - 收盘价下穿下轨（向下跌破显著超过正常波动）：SELL
    - 其他情况：None

    ATR 在这里只用于衡量"波动是否显著"，不用于仓位管理
    （仓位由 sizing 模块负责）。低波动、价格贴近均线时不发信号。
    预热期：至少需要 ``max(ma_window, atr_period) + 1`` 根 Bar
    （含当前 Bar）。
    """

    def __init__(
        self,
        ma_window: int = 20,
        atr_period: int = 14,
        atr_multiplier: float = 2.0,
    ) -> None:
        if ma_window < 1:
            raise ValueError("ma_window 必须大于 0")
        if atr_period < 1:
            raise ValueError("atr_period 必须大于 0")
        if atr_multiplier <= 0:
            raise ValueError("atr_multiplier 必须大于 0")
        self.ma_window = ma_window
        self.atr_period = atr_period
        self.atr_multiplier = float(atr_multiplier)

    def on_bar(self, bar: Bar, history: Mapping[str, Sequence[Bar]]) -> Side | None:
        bars = history.get(bar.symbol, ())
        if len(bars) < max(self.ma_window, self.atr_period) + 1:
            return None
        closes = [item.close for item in bars]
        highs = [item.high for item in bars]
        lows = [item.low for item in bars]
        trend = sma(closes, self.ma_window)
        volatility = atr(highs, lows, closes, self.atr_period)
        previous_trend, current_trend = trend[-2], trend[-1]
        previous_atr, current_atr = volatility[-2], volatility[-1]
        if None in (previous_trend, current_trend, previous_atr, current_atr):
            return None
        previous_close, current_close = closes[-2], closes[-1]
        previous_upper = previous_trend + self.atr_multiplier * previous_atr
        current_upper = current_trend + self.atr_multiplier * current_atr
        previous_lower = previous_trend - self.atr_multiplier * previous_atr
        current_lower = current_trend - self.atr_multiplier * current_atr
        if previous_close <= previous_upper and current_close > current_upper:
            return Side.BUY
        if previous_close >= previous_lower and current_close < current_lower:
            return Side.SELL
        return None
