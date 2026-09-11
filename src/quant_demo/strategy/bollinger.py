"""布林带均值回归策略：价格重新穿回轨道内时发出反向信号。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from quant_demo.models import Bar, Side
from quant_demo.strategy.base import Strategy
from quant_demo.strategy.indicators import bollinger_bands


class BollingerBandsStrategy(Strategy):
    """价格越出布林带后重新穿回轨道内时交易，只在穿越时发出一次信号。

    - 收盘价从下轨下方重新向上穿回下轨：BUY
    - 收盘价从上轨上方重新向下穿回上轨：SELL
    - 其他情况：None

    每根 Bar 与当根 Bar 自己的轨道比较（上一根收盘对上一根下轨，
    当前收盘对当前下轨），不使用未来数据。
    预热期：至少需要 ``period + 1`` 根 Bar（含当前 Bar）。
    """

    def __init__(self, period: int = 20, std_multiplier: float = 2.0) -> None:
        if period < 2:
            raise ValueError("period 必须大于 1")
        if std_multiplier <= 0:
            raise ValueError("std_multiplier 必须大于 0")
        self.period = period
        self.std_multiplier = float(std_multiplier)

    def on_bar(self, bar: Bar, history: Mapping[str, Sequence[Bar]]) -> Side | None:
        closes = [item.close for item in history.get(bar.symbol, ())]
        if len(closes) < self.period + 1:
            return None
        bands = bollinger_bands(closes, self.period, self.std_multiplier)
        previous_lower, current_lower = bands.lower[-2], bands.lower[-1]
        previous_upper, current_upper = bands.upper[-2], bands.upper[-1]
        if None in (previous_lower, current_lower, previous_upper, current_upper):
            return None
        previous_close, current_close = closes[-2], closes[-1]
        if previous_close < previous_lower and current_close >= current_lower:
            return Side.BUY
        if previous_close > previous_upper and current_close <= current_upper:
            return Side.SELL
        return None
