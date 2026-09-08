"""B（策略模块）的稳定接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence

from quant_demo.models import Bar, Side


class Strategy(ABC):
    @abstractmethod
    def on_bar(self, bar: Bar, history: Mapping[str, Sequence[Bar]]) -> Side | None:
        """仅使用当前及历史 Bar，返回方向意图；数量由仓位模块决定。"""

