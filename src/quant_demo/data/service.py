"""A（数据模块）的接口与 CSV 参考实现。"""

from __future__ import annotations

import csv
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

from quant_demo.models import Bar


class MarketDataService(ABC):
    @abstractmethod
    def get_bars(
        self,
        symbols: list[str],
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Bar]:
        """返回按 (datetime, symbol) 升序排列且已复权口径一致的日 K。"""


class CsvDataService(MarketDataService):
    """读取字段为 symbol,date,open,high,low,close,volume 的 UTF-8 CSV。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def get_bars(
        self,
        symbols: list[str],
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Bar]:
        wanted = set(symbols)
        bars: list[Bar] = []
        with self.path.open("r", encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                dt = datetime.fromisoformat(row["date"])
                if row["symbol"] not in wanted:
                    continue
                if start and dt < start:
                    continue
                if end and dt > end:
                    continue
                bars.append(
                    Bar(
                        symbol=row["symbol"],
                        datetime=dt,
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row["volume"]),
                    )
                )
        return sorted(bars, key=lambda item: (item.datetime, item.symbol))

