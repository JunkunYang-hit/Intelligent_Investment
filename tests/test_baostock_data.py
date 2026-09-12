"""BaoStockDataService 的测试。

纯逻辑部分（代码映射、缓存读写）始终运行；
联网部分标记为 ``network``，默认跳过，加 ``--run-network`` 参数才运行：
    python -m pytest tests/test_baostock_data.py -v --run-network
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

import pytest

from quant_demo.data import (
    BaoStockDataService,
    to_baostock_code,
    from_baostock_code,
)
from quant_demo.models import Bar


# --------------------------------------------------------------------------- #
# 代码映射（纯逻辑，始终运行）
# --------------------------------------------------------------------------- #
class TestCodeMapping:
    def test_etf_510300_maps_to_hs300_index(self) -> None:
        assert to_baostock_code("510300.SH") == "sh.000300"

    def test_plain_510300_maps_to_index(self) -> None:
        assert to_baostock_code("510300") == "sh.000300"

    def test_sh_stock(self) -> None:
        assert to_baostock_code("600000.SH") == "sh.600000"

    def test_sz_stock(self) -> None:
        assert to_baostock_code("000001.SZ") == "sz.000001"

    def test_reverse_mapping_sh(self) -> None:
        assert from_baostock_code("sh.600000") == "600000.SH"

    def test_reverse_mapping_sz(self) -> None:
        assert from_baostock_code("sz.000001") == "000001.SZ"

    def test_invalid_suffix_raises(self) -> None:
        with pytest.raises(ValueError, match="不支持的交易所后缀"):
            to_baostock_code("600000.HK")

    def test_missing_suffix_raises(self) -> None:
        with pytest.raises(ValueError, match="缺少交易所后缀"):
            to_baostock_code("600000")


# --------------------------------------------------------------------------- #
# 缓存读写（纯逻辑，始终运行）
# --------------------------------------------------------------------------- #
class TestCache:
    def _sample_rows(self) -> list[dict[str, str]]:
        return [
            {"date": "2024-01-02", "code": "sh.000300", "open": "3426.0",
             "high": "3426.0", "low": "3386.0", "close": "3386.0", "volume": "11618072600"},
            {"date": "2024-01-03", "code": "sh.000300", "open": "3379.0",
             "high": "3392.0", "low": "3362.0", "close": "3378.0", "volume": "10561385100"},
        ]

    def test_write_and_read_cache(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "510300_SH.csv"
        BaoStockDataService._write_cache(cache_file, self._sample_rows())
        assert cache_file.exists()

        rows = BaoStockDataService._read_cache(cache_file, "2024-01-01", "2024-01-10")
        assert rows is not None
        assert len(rows) == 2
        assert rows[0]["date"] == "2024-01-02"

    def test_read_cache_returns_none_if_file_missing(self, tmp_path: Path) -> None:
        assert BaoStockDataService._read_cache(tmp_path / "nope.csv", "2024-01-01", "2024-01-10") is None


# --------------------------------------------------------------------------- #
# 联网测试（默认跳过，由 conftest.py 中 network marker 控制）
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def baostock_svc(tmp_path_factory):
    cache_dir = tmp_path_factory.mktemp("baostock_cache")
    return BaoStockDataService(cache_dir=cache_dir)


@pytest.mark.network
class TestNetwork:
    def test_fetch_hs300_index_bars(self, request, baostock_svc) -> None:
        bars = baostock_svc.get_bars(
            ["510300.SH"],
            datetime(2024, 1, 2),
            datetime(2024, 1, 10),
        )
        assert len(bars) > 0
        assert all(b.symbol == "510300.SH" for b in bars)
        assert bars == sorted(bars, key=lambda b: (b.datetime, b.symbol))
        # 验证 Bar 合法性（__post_init__ 已校验，这里再确认）
        for b in bars:
            assert b.high >= max(b.open, b.close)
            assert b.low <= min(b.open, b.close)

    def test_get_hs300_symbols(self, request, baostock_svc) -> None:
        symbols = baostock_svc.get_hs300_symbols()
        assert len(symbols) == 300
        assert all(s.endswith(".SH") or s.endswith(".SZ") for s in symbols)

    def test_fetch_constituent_stock(self, request, baostock_svc) -> None:
        bars = baostock_svc.get_bars(
            ["600000.SH"],
            datetime(2024, 1, 2),
            datetime(2024, 1, 10),
        )
        assert len(bars) > 0
        assert all(b.symbol == "600000.SH" for b in bars)

    def test_cache_hit_avoids_network(self, request, tmp_path: Path) -> None:
        """第二次查询相同范围应命中缓存（不报错即通过）。"""
        svc = BaoStockDataService(cache_dir=tmp_path / "cache")
        first = svc.get_bars(["510300.SH"], datetime(2024, 1, 2), datetime(2024, 1, 10))
        second = svc.get_bars(["510300.SH"], datetime(2024, 1, 2), datetime(2024, 1, 10))
        assert len(first) == len(second)
