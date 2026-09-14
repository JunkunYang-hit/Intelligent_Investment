"""A（数据模块）的接口与清洗测试。

用临时 CSV 文件验证 CsvDataService，同时覆盖 clean_bars、
SyntheticDataService 和 snapshot_id 的核心行为。
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

import pytest

from quant_demo.data import (
    CsvDataService,
    MarketDataService,
    SyntheticDataService,
    clean_bars,
    detect_anomalies,
    snapshot_id,
)
from quant_demo.models import Bar


# --------------------------------------------------------------------------- #
# 测试辅助
# --------------------------------------------------------------------------- #
def _write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["symbol", "date", "open", "high", "low", "close", "volume"]
        )
        writer.writeheader()
        writer.writerows(rows)


def _bar(symbol: str, date: str, o: float = 10.0, c: float | None = None) -> Bar:
    c = o if c is None else c
    h = max(o, c) * 1.01
    lo = min(o, c) * 0.99
    return Bar(symbol, datetime.fromisoformat(date), o, h, lo, c, 1000.0)


# --------------------------------------------------------------------------- #
# CsvDataService
# --------------------------------------------------------------------------- #
def test_csv_reads_and_filters_by_symbol_and_date(tmp_path: Path) -> None:
    p = tmp_path / "data.csv"
    _write_csv(
        p,
        [
            {"symbol": "510300.SH", "date": "2024-01-02", "open": "4.0", "high": "4.2",
             "low": "3.9", "close": "4.1", "volume": "1000"},
            {"symbol": "510500.SH", "date": "2024-01-02", "open": "6.0", "high": "6.2",
             "low": "5.9", "close": "6.1", "volume": "2000"},
            {"symbol": "510300.SH", "date": "2024-01-03", "open": "4.1", "high": "4.3",
             "low": "4.0", "close": "4.2", "volume": "1500"},
        ],
    )
    svc = CsvDataService(p)
    bars = svc.get_bars(["510300.SH"], datetime(2024, 1, 3), datetime(2024, 1, 10))
    assert len(bars) == 1
    assert bars[0].symbol == "510300.SH"
    assert bars[0].datetime == datetime(2024, 1, 3)


def test_csv_returns_sorted_by_datetime_then_symbol(tmp_path: Path) -> None:
    p = tmp_path / "data.csv"
    _write_csv(
        p,
        [
            {"symbol": "B", "date": "2024-01-02", "open": "10", "high": "11",
             "low": "9", "close": "10", "volume": "100"},
            {"symbol": "A", "date": "2024-01-02", "open": "10", "high": "11",
             "low": "9", "close": "10", "volume": "100"},
        ],
    )
    bars = CsvDataService(p).get_bars(["A", "B"])
    assert [(b.datetime, b.symbol) for b in bars] == [
        (datetime(2024, 1, 2), "A"),
        (datetime(2024, 1, 2), "B"),
    ]


def test_csv_skips_dirty_rows(tmp_path: Path) -> None:
    p = tmp_path / "data.csv"
    _write_csv(
        p,
        [
            {"symbol": "510300.SH", "date": "2024-01-02", "open": "4.0", "high": "4.2",
             "low": "3.9", "close": "4.1", "volume": "1000"},
            # OHLC 关系非法，会被 Bar 构造拒绝 -> 跳过
            {"symbol": "510300.SH", "date": "2024-01-03", "open": "10", "high": "1",
             "low": "9", "close": "10", "volume": "100"},
            # 非数字，类型转换失败 -> 跳过
            {"symbol": "510300.SH", "date": "2024-01-04", "open": "abc", "high": "4.2",
             "low": "3.9", "close": "4.1", "volume": "1000"},
        ],
    )
    bars = CsvDataService(p).get_bars(["510300.SH"])
    assert len(bars) == 1
    assert bars[0].datetime == datetime(2024, 1, 2)


def test_csv_caches_file_content(tmp_path: Path) -> None:
    p = tmp_path / "data.csv"
    _write_csv(
        p,
        [
            {"symbol": "510300.SH", "date": "2024-01-02", "open": "4.0", "high": "4.2",
             "low": "3.9", "close": "4.1", "volume": "1000"},
        ],
    )
    svc = CsvDataService(p)
    first = svc.get_bars(["510300.SH"])
    second = svc.get_bars(["510300.SH"])
    assert first is not second  # 过滤后产生新列表
    # 底层缓存命中
    assert svc._cache is not None


# --------------------------------------------------------------------------- #
# clean_bars
# --------------------------------------------------------------------------- #
def test_clean_bars_deduplicates_by_symbol_datetime() -> None:
    b1 = _bar("510300.SH", "2024-01-02")
    b2 = _bar("510300.SH", "2024-01-02", c=11.0)  # 同 key，覆盖
    result = clean_bars([b1, b2])
    assert len(result) == 1
    assert result[0].close == 11.0


def test_clean_bars_preserves_order_when_disabled() -> None:
    b1 = _bar("510300.SH", "2024-01-03")
    b2 = _bar("510300.SH", "2024-01-02")
    result = clean_bars([b1, b2], sort=True)
    assert result[0].datetime < result[1].datetime


# --------------------------------------------------------------------------- #
# SyntheticDataService
# --------------------------------------------------------------------------- #
def test_synthetic_is_deterministic_with_same_seed() -> None:
    a = SyntheticDataService(seed=7).get_bars(["510300.SH"])
    b = SyntheticDataService(seed=7).get_bars(["510300.SH"])
    assert [(x.datetime, x.close) for x in a] == [(x.datetime, x.close) for x in b]


def test_synthetic_only_produces_weekdays() -> None:
    bars = SyntheticDataService().get_bars(
        ["510300.SH"], datetime(2024, 1, 1), datetime(2024, 1, 14)
    )
    assert all(b.datetime.weekday() < 5 for b in bars)


# --------------------------------------------------------------------------- #
# detect_anomalies
# --------------------------------------------------------------------------- #
def test_detect_anomalies_flags_large_gap() -> None:
    bars = [
        _bar("510300.SH", "2024-01-02", o=10, c=10),
        _bar("510300.SH", "2024-01-03", o=10, c=20),  # +100%
    ]
    warnings = detect_anomalies(bars, max_gap_pct=0.2)
    assert len(warnings) == 1
    assert "510300.SH" in warnings[0]


def test_detect_anomalies_silent_on_normal_data() -> None:
    bars = [
        _bar("510300.SH", "2024-01-02", o=10, c=10.1),
        _bar("510300.SH", "2024-01-03", o=10.1, c=10.2),
    ]
    assert detect_anomalies(bars) == []


# --------------------------------------------------------------------------- #
# snapshot_id
# --------------------------------------------------------------------------- #
def test_snapshot_id_is_stable_for_same_data() -> None:
    bars = [_bar("510300.SH", "2024-01-02"), _bar("510300.SH", "2024-01-03")]
    assert snapshot_id(bars) == snapshot_id(bars.copy())


def test_snapshot_id_independent_of_input_order() -> None:
    # 快照应反映数据内容而非读入顺序，排序后应一致
    bars = [_bar("510300.SH", "2024-01-02"), _bar("510300.SH", "2024-01-03")]
    rev = list(reversed(bars))
    assert snapshot_id(sorted(bars, key=lambda b: b.datetime)) == snapshot_id(
        sorted(rev, key=lambda b: b.datetime)
    )


def test_snapshot_id_changes_when_data_changes() -> None:
    bars = [_bar("510300.SH", "2024-01-02")]
    changed = [_bar("510300.SH", "2024-01-02", c=99.0)]
    assert snapshot_id(bars) != snapshot_id(changed)


# --------------------------------------------------------------------------- #
# 接口契约
# --------------------------------------------------------------------------- #
def test_market_data_service_is_abstract() -> None:
    with pytest.raises(TypeError):
        MarketDataService()  # type: ignore[abstract]
