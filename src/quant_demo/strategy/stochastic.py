"""随机指标（Stochastic Oscillator）交叉策略：极端区域内的 %K/%D 交叉。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from quant_demo.models import Bar, Side
from quant_demo.strategy.base import Strategy
from quant_demo.strategy.indicators import stochastic


class StochasticStrategy(Strategy):
    """在超卖/超买区域内发生 %K 与 %D 交叉时发出一次信号。

    - %K 上穿 %D，且交叉前 %K 低于超卖线（低位金叉）：BUY
    - %K 下穿 %D，且交叉前 %K 高于超买线（高位死叉）：SELL
    - 其他情况：None

    使用"区域 + 交叉"双重条件，而不是 ``K < 20`` 就 BUY，避免指标停留在
    极端区域时每天重复发信号。预热期：至少需要 ``k_period + d_period``
    根 Bar（含当前 Bar）。
    """

    def __init__(
        self,
        k_period: int = 14,
        d_period: int = 3,
        oversold: float = 20.0,
        overbought: float = 80.0,
    ) -> None:
        if k_period < 1 or d_period < 1:
            raise ValueError("k_period、d_period 都必须大于 0")
        if not 0 <= oversold < overbought <= 100:
            raise ValueError("阈值必须满足 0 <= oversold < overbought <= 100")
        self.k_period = k_period
        self.d_period = d_period
        self.oversold = float(oversold)
        self.overbought = float(overbought)

    def on_bar(self, bar: Bar, history: Mapping[str, Sequence[Bar]]) -> Side | None:
        bars = history.get(bar.symbol, ())
        if len(bars) < self.k_period + self.d_period:
            return None
        closes = [item.close for item in bars]
        highs = [item.high for item in bars]
        lows = [item.low for item in bars]
        result = stochastic(highs, lows, closes, self.k_period, self.d_period)
        previous_k, current_k = result.k[-2], result.k[-1]
        previous_d, current_d = result.d[-2], result.d[-1]
        if None in (previous_k, current_k, previous_d, current_d):
            return None
        if (
            previous_k <= previous_d
            and current_k > current_d
            and previous_k < self.oversold
        ):
            return Side.BUY
        if (
            previous_k >= previous_d
            and current_k < current_d
            and previous_k > self.overbought
        ):
            return Side.SELL
        return None
