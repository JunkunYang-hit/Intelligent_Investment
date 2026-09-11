"""MACD 金叉/死叉策略：MACD 线与信号线交叉时发出方向信号。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from quant_demo.models import Bar, Side
from quant_demo.strategy.base import Strategy
from quant_demo.strategy.indicators import macd


class MACDStrategy(Strategy):
    """只在 MACD 线与信号线发生交叉时发出一次信号。

    - MACD 线上穿信号线（金叉）：BUY
    - MACD 线下穿信号线（死叉）：SELL
    - 其他情况：None

    预热期：至少需要 ``slow_period + signal_period`` 根 Bar（含当前 Bar）。
    """

    def __init__(self, fast_period: int = 12, slow_period: int = 26, signal_period: int = 9) -> None:
        if fast_period < 1 or slow_period < 1 or signal_period < 1:
            raise ValueError("fast_period、slow_period、signal_period 都必须大于 0")
        if fast_period >= slow_period:
            raise ValueError("fast_period 必须小于 slow_period")
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period

    def on_bar(self, bar: Bar, history: Mapping[str, Sequence[Bar]]) -> Side | None:
        closes = [item.close for item in history.get(bar.symbol, ())]
        if len(closes) < self.slow_period + self.signal_period:
            return None
        result = macd(closes, self.fast_period, self.slow_period, self.signal_period)
        previous_macd, current_macd = result.macd[-2], result.macd[-1]
        previous_signal, current_signal = result.signal[-2], result.signal[-1]
        if None in (previous_macd, current_macd, previous_signal, current_signal):
            return None
        if previous_macd <= previous_signal and current_macd > current_signal:
            return Side.BUY
        if previous_macd >= previous_signal and current_macd < current_signal:
            return Side.SELL
        return None
