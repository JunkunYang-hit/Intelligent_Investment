"""动量阈值穿越策略：N 日收益率穿越阈值时发出一次方向信号。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from quant_demo.models import Bar, Side
from quant_demo.strategy.base import Strategy
from quant_demo.strategy.indicators import momentum


class MomentumStrategy(Strategy):
    """中短期价格动量：用阈值穿越产生事件型信号，不每天重复交易。

    动量定义：``momentum = close_t / close_(t-lookback) - 1``。

    - 动量从 <= positive_threshold 上穿 positive_threshold：BUY
    - 动量从 >= negative_threshold 下穿 negative_threshold：SELL
    - 其他情况：None

    默认两个阈值都为 0，即"动量由负转正 / 由正转负"的过零穿越；
    调大（调小）阈值可以过滤弱趋势。预热期：至少需要
    ``lookback + 2`` 根 Bar（含当前 Bar）。
    """

    def __init__(
        self,
        lookback: int = 20,
        positive_threshold: float = 0.0,
        negative_threshold: float = 0.0,
    ) -> None:
        if lookback < 1:
            raise ValueError("lookback 必须大于 0")
        if negative_threshold > positive_threshold:
            raise ValueError("阈值必须满足 negative_threshold <= positive_threshold")
        self.lookback = lookback
        self.positive_threshold = float(positive_threshold)
        self.negative_threshold = float(negative_threshold)

    def on_bar(self, bar: Bar, history: Mapping[str, Sequence[Bar]]) -> Side | None:
        closes = [item.close for item in history.get(bar.symbol, ())]
        if len(closes) < self.lookback + 2:
            return None
        values = momentum(closes, self.lookback)
        previous, current = values[-2], values[-1]
        if previous is None or current is None:
            return None
        if previous <= self.positive_threshold and current > self.positive_threshold:
            return Side.BUY
        if previous >= self.negative_threshold and current < self.negative_threshold:
            return Side.SELL
        return None
