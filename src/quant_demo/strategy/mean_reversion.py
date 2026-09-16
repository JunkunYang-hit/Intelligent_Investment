"""Z 分数均值回归策略：标准化偏离从极端区域回落时发出一次信号。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from quant_demo.models import Bar, Side
from quant_demo.strategy.base import Strategy
from quant_demo.strategy.indicators import zscore


class ZScoreMeanReversionStrategy(Strategy):
    """用 Z 分数度量价格偏离滚动均值的标准差倍数，偏离收敛时交易。

    ``z = (close - 窗口均值) / 窗口总体标准差``。

    - z 从 <= buy_z 向上穿回 buy_z（深度超卖后开始收敛）：BUY
    - z 从 >= sell_z 向下穿回 sell_z（深度超买后开始收敛）：SELL
    - 其他情况：None

    与 BollingerBandsStrategy 的关系：默认参数（window=20、阈值 ±2）
    下二者数学上等价（z = 2 恰为 2 倍标准差轨道）。本策略的价值在于
    支持**非对称阈值**（如 buy_z=-2.5、sell_z=1.5，适应 A 股下跌更深、
    反弹更慢的特征），并以标准化偏离的形式便于与其他因子比较。
    预热期：至少需要 ``window + 1`` 根 Bar（含当前 Bar）。
    """

    def __init__(self, window: int = 20, buy_z: float = -2.0, sell_z: float = 2.0) -> None:
        if window < 2:
            raise ValueError("window 必须大于 1")
        if buy_z >= sell_z:
            raise ValueError("阈值必须满足 buy_z < sell_z")
        self.window = window
        self.buy_z = float(buy_z)
        self.sell_z = float(sell_z)

    def on_bar(self, bar: Bar, history: Mapping[str, Sequence[Bar]]) -> Side | None:
        closes = [item.close for item in history.get(bar.symbol, ())]
        if len(closes) < self.window + 1:
            return None
        values = zscore(closes, self.window)
        previous, current = values[-2], values[-1]
        if previous is None or current is None:
            return None
        if previous <= self.buy_z and current > self.buy_z:
            return Side.BUY
        if previous >= self.sell_z and current < self.sell_z:
            return Side.SELL
        return None
