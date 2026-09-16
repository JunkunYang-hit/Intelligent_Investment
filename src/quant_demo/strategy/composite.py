"""多指标综合策略：趋势、动量、强弱三个维度投票打分。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import NamedTuple, Optional

from quant_demo.models import Bar, Side
from quant_demo.strategy.base import Strategy
from quant_demo.strategy.indicators import macd, rsi, sma


class CompositeScore(NamedTuple):
    """综合打分的分解结果，便于解释每一次信号的来源。"""

    trend: int
    momentum: int
    rsi: int
    total: int


class CompositeStrategy(Strategy):
    """综合三个低相关维度的投票打分，得分穿越阈值时发出一次信号。

    每个维度各投一票（-1 / 0 / +1），总分范围 [-3, 3]：

    - 趋势票：短 SMA > 长 SMA 为 +1，否则 -1；
    - 动量票：MACD 柱线 > 0 为 +1，否则 -1；
    - 强弱票：RSI >= ``rsi_bull`` 为 +1，RSI <= ``rsi_bear`` 为 -1，
      中间区域为 0（中性区不投票，避免与趋势票重复计票）。

    信号采用"总分穿越阈值"的事件方式，避免每天重复 BUY/SELL：

    - 总分从 < ``buy_threshold`` 上升为 >= ``buy_threshold``：BUY
    - 总分从 > ``sell_threshold`` 下降为 <= ``sell_threshold``：SELL
    - 其他情况：None

    设计说明：三个维度分别来自不同指标族（均线、MACD、RSI），其中均线与
    MACD 仍有一定正相关，因此默认要求至少 2 票同向才触发，而不是一票定音。
    预热期：至少需要 ``max(long_window + 1, rsi_period + 2,
    slow_period + signal_period)`` 根 Bar（含当前 Bar；默认 35）。
    """

    def __init__(
        self,
        short_window: int = 5,
        long_window: int = 20,
        rsi_period: int = 14,
        rsi_bull: float = 55.0,
        rsi_bear: float = 45.0,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
        buy_threshold: int = 2,
        sell_threshold: int = -2,
    ) -> None:
        if not 1 <= short_window < long_window:
            raise ValueError("窗口必须满足 1 <= short_window < long_window")
        if rsi_period < 1:
            raise ValueError("rsi_period 必须大于 0")
        if not 0 <= rsi_bear < rsi_bull <= 100:
            raise ValueError("RSI 阈值必须满足 0 <= rsi_bear < rsi_bull <= 100")
        if fast_period < 1 or slow_period < 1 or signal_period < 1:
            raise ValueError("fast_period、slow_period、signal_period 都必须大于 0")
        if fast_period >= slow_period:
            raise ValueError("fast_period 必须小于 slow_period")
        if isinstance(buy_threshold, bool) or not isinstance(buy_threshold, int):
            raise ValueError("buy_threshold 必须是正整数")
        if not 1 <= buy_threshold <= 3:
            raise ValueError("buy_threshold 必须在 1 到 3 之间")
        if isinstance(sell_threshold, bool) or not isinstance(sell_threshold, int):
            raise ValueError("sell_threshold 必须是负整数")
        if not -3 <= sell_threshold <= -1:
            raise ValueError("sell_threshold 必须在 -3 到 -1 之间")
        self.short_window = short_window
        self.long_window = long_window
        self.rsi_period = rsi_period
        self.rsi_bull = float(rsi_bull)
        self.rsi_bear = float(rsi_bear)
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold

    def score_components(self, closes: Sequence[float]) -> Optional[CompositeScore]:
        """对给定收盘价序列计算当前三个维度的票数与总分。

        数据不足以计算任一维度时返回 None；返回值是透明可解释的打分分解，
        可用于日志、调试或 Web 展示。
        """
        short_ma = sma(closes, self.short_window)[-1] if closes else None
        long_ma = sma(closes, self.long_window)[-1] if closes else None
        rsi_values = rsi(closes, self.rsi_period)
        macd_result = macd(closes, self.fast_period, self.slow_period, self.signal_period)
        rsi_now = rsi_values[-1] if closes else None
        histogram_now = macd_result.histogram[-1] if closes else None
        if None in (short_ma, long_ma, rsi_now, histogram_now):
            return None
        trend = 1 if short_ma > long_ma else -1
        momentum = 1 if histogram_now > 0 else -1
        if rsi_now >= self.rsi_bull:
            rsi_vote = 1
        elif rsi_now <= self.rsi_bear:
            rsi_vote = -1
        else:
            rsi_vote = 0
        return CompositeScore(
            trend=trend,
            momentum=momentum,
            rsi=rsi_vote,
            total=trend + momentum + rsi_vote,
        )

    def on_bar(self, bar: Bar, history: Mapping[str, Sequence[Bar]]) -> Side | None:
        closes = [item.close for item in history.get(bar.symbol, ())]
        if len(closes) < self.warmup_bars:
            return None
        current = self.score_components(closes)
        previous = self.score_components(closes[:-1])
        if current is None or previous is None:
            return None
        if previous.total < self.buy_threshold and current.total >= self.buy_threshold:
            return Side.BUY
        if previous.total > self.sell_threshold and current.total <= self.sell_threshold:
            return Side.SELL
        return None

    @property
    def warmup_bars(self) -> int:
        """所需最少 Bar 数（含当前 Bar，并多含一根用于比较上一日得分）。"""
        return max(
            self.long_window + 1,
            self.rsi_period + 2,
            self.slow_period + self.signal_period,
        )
