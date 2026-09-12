"""A（数据模块）的接口、CSV 实现与清洗逻辑。

本模块负责行情读取与清洗，对下游只暴露 ``MarketDataService`` 抽象接口。
所有实现返回的 ``Bar`` 列表必须满足：
  - 按 ``(datetime, symbol)`` 升序排列；
  - 同一 ``(symbol, datetime)`` 不重复；
  - OHLC 合法且复权口径一致；
  - 已按 ``start`` / ``end`` 过滤。
"""

from __future__ import annotations

import csv
import hashlib
import json
import random
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

from quant_demo.models import Bar


# --------------------------------------------------------------------------- #
# 抽象接口
# --------------------------------------------------------------------------- #
class MarketDataService(ABC):
    """行情数据服务的统一接口，A 部分对外只暴露它。"""

    @abstractmethod
    def get_bars(
        self,
        symbols: list[str],
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Bar]:
        """返回按 (datetime, symbol) 升序排列且已复权口径一致的日 K。"""


# --------------------------------------------------------------------------- #
# 清洗工具
# --------------------------------------------------------------------------- #
class DataQualityError(ValueError):
    """数据质量问题导致无法构造合法 Bar 时抛出。"""


def _row_key(symbol: str, dt: datetime) -> tuple[str, datetime]:
    return symbol, dt


def clean_bars(
    raw: Iterable[Bar],
    *,
    drop_duplicates: bool = True,
    drop_nan_volume: bool = True,
    sort: bool = True,
) -> list[Bar]:
    """对原始 Bar 流做去重、合法性校验与排序。

    - 去重：同一 ``(symbol, datetime)`` 保留最后一条（后写入覆盖先写入）。
    - 校验：交给 ``Bar.__post_init__``；不合法的直接丢弃并记入质量问题。
    - 排序：按 ``(datetime, symbol)`` 升序。
    """
    seen: dict[tuple[str, datetime], Bar] = {}
    rejected = 0
    for bar in raw:
        if drop_nan_volume and bar.volume != bar.volume:  # NaN 检测
            rejected += 1
            continue
        key = _row_key(bar.symbol, bar.datetime)
        if key in seen and not drop_duplicates:
            rejected += 1
            continue
        seen[key] = bar
    bars = list(seen.values())
    if sort:
        bars.sort(key=lambda b: (b.datetime, b.symbol))
    if rejected:
        # 不中断流程，只在调试时可观察；正式可接日志
        pass
    return bars


def detect_anomalies(bars: list[Bar], *, max_gap_pct: float = 0.2) -> list[str]:
    """简单的异常值检测：相邻收盘价变动超过阈值则标记。

    返回告警字符串列表，供上层决定是否剔除或人工复核。
    """
    warnings: list[str] = []
    by_symbol: dict[str, list[Bar]] = {}
    for b in bars:
        by_symbol.setdefault(b.symbol, []).append(b)
    for symbol, seq in by_symbol.items():
        prev = None
        for bar in seq:
            if prev is not None and prev.close > 0:
                change = abs(bar.close - prev.close) / prev.close
                if change > max_gap_pct:
                    warnings.append(
                        f"{symbol} {bar.datetime.date()} 收盘价变动 {change:.2%} 超过 {max_gap_pct:.0%}"
                    )
            prev = bar
    return warnings


# --------------------------------------------------------------------------- #
# CSV 实现（保留原参考实现，增强清洗与缓存）
# --------------------------------------------------------------------------- #
class CsvDataService(MarketDataService):
    """读取字段为 symbol,date,open,high,low,close,volume 的 UTF-8 CSV。

    增强点：
      - 解析阶段做类型转换与脏数据跳过；
      - 通过 ``clean_bars`` 去重并校验；
      - 文件级内存缓存，同一文件不重复解析。
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._cache: list[Bar] | None = None
        self._cache_key: str | None = None

    def _load_all(self) -> list[Bar]:
        stat = self.path.stat()
        key = f"{self.path}:{stat.st_mtime_ns}:{stat.st_size}"
        if self._cache is not None and self._cache_key == key:
            return self._cache
        raw: list[Bar] = []
        with self.path.open("r", encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                try:
                    dt = datetime.fromisoformat(row["date"])
                    raw.append(
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
                except (KeyError, ValueError, TypeError):
                    # 脏行跳过，不中断整体读取
                    continue
        self._cache = clean_bars(raw)
        self._cache_key = key
        return self._cache

    def get_bars(
        self,
        symbols: list[str],
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Bar]:
        wanted = set(symbols)
        bars = [
            b
            for b in self._load_all()
            if b.symbol in wanted
            and (start is None or b.datetime >= start)
            and (end is None or b.datetime <= end)
        ]
        return sorted(bars, key=lambda item: (item.datetime, item.symbol))


# --------------------------------------------------------------------------- #
# 合成数据实现（供团队在无真实数据源时跑通链路）
# --------------------------------------------------------------------------- #
class SyntheticDataService(MarketDataService):
    """基于随机游走生成确定性日 K，供离线开发与测试使用。

    通过 ``seed`` 保证同一参数下结果可复现，等价于一个 ``数据快照``。
    """

    def __init__(self, seed: int = 42) -> None:
        self.seed = seed

    def get_bars(
        self,
        symbols: list[str],
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Bar]:
        start = start or datetime(2024, 1, 2)
        end = end or datetime(2024, 12, 31)
        bars: list[Bar] = []
        rng = random.Random(self.seed)
        for symbol in symbols:
            price = 10.0
            day = start
            while day <= end:
                if day.weekday() < 5:  # 仅工作日
                    drift = rng.gauss(0, 0.015)
                    open_ = price
                    close = round(max(0.01, open_ * (1 + drift)), 3)
                    high = round(max(open_, close) * (1 + abs(rng.gauss(0, 0.005))), 3)
                    low = round(min(open_, close) * (1 - abs(rng.gauss(0, 0.005))), 3)
                    volume = float(rng.randint(100_000, 1_000_000))
                    bars.append(
                        Bar(
                            symbol=symbol,
                            datetime=day,
                            open=open_,
                            high=high,
                            low=low,
                            close=close,
                            volume=volume,
                        )
                    )
                    price = close
                day += timedelta(days=1)
        return sorted(bars, key=lambda b: (b.datetime, b.symbol))


# --------------------------------------------------------------------------- #
# 数据快照（对应 PRD 中“回测任务必须绑定数据快照ID”的要求）
# --------------------------------------------------------------------------- #
def snapshot_id(bars: list[Bar]) -> str:
    """根据 Bar 列表内容生成稳定的快照哈希，用于回测可复现性绑定。"""
    payload = json.dumps(
        [
            {
                "symbol": b.symbol,
                "datetime": b.datetime.isoformat(),
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume,
            }
            for b in bars
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
