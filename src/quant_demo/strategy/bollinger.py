"""布林带均值回归策略：价格重新穿回轨道内时发出反向信号。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from statistics import pstdev

from quant_demo.models import Bar, Side
from quant_demo.strategy.base import Strategy


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
        # 只计算用于本次穿越判断的两个窗口。原实现每根 Bar 都重算整段
        # 布林带，五年数据会退化为非常慢的重复计算。
        previous_window = closes[-self.period - 1 : -1]
        current_window = closes[-self.period :]
        previous_middle = sum(previous_window) / self.period
        current_middle = sum(current_window) / self.period
        previous_deviation = pstdev(previous_window)
        current_deviation = pstdev(current_window)
        previous_lower = previous_middle - self.std_multiplier * previous_deviation
        current_lower = current_middle - self.std_multiplier * current_deviation
        previous_upper = previous_middle + self.std_multiplier * previous_deviation
        current_upper = current_middle + self.std_multiplier * current_deviation
        previous_close, current_close = closes[-2], closes[-1]
        if previous_close < previous_lower and current_close >= current_lower:
            return Side.BUY
        if previous_close > previous_upper and current_close <= current_upper:
            return Side.SELL
        return None
