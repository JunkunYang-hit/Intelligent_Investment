"""BaoStock 真实行情数据适配器。

通过 BaoStock 拉取 A 股日 K，满足 README 要求：
  - 第一版默认用沪深 300 ETF（510300.SH）代表大盘资产；
  - 如需"从沪深 300 成分股中选股"，调用 ``get_hs300_symbols()`` 获取股票池，
    再用 ``get_bars()`` 拉取个股 Bar 数据，交易内核无需任何改动。

代码映射约定（对下游透明）：
  - 510300.SH / 510300  → 沪深300指数 sh.000300（BaoStock 不提供 ETF 行情）
  - 600000.SH  → sh.600000
  - 000001.SZ  → sz.000001

数据默认前复权（adjustflag="2"），并缓存到本地 CSV，避免重复联网。
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Iterable

from quant_demo.models import Bar

from .service import MarketDataService, clean_bars


# --------------------------------------------------------------------------- #
# 代码映射
# --------------------------------------------------------------------------- #
# 仓库 symbol → BaoStock code
_SPECIAL_MAP = {
    "510300.SH": "sh.000300",   # 沪深300ETF → 沪深300指数
    "510300": "sh.000300",
    "000300.SH": "sh.000300",
    "000300": "sh.000300",
}


def to_baostock_code(symbol: str) -> str:
    """仓库 symbol (如 600000.SH) 转为 BaoStock code (如 sh.600000)。"""
    if symbol in _SPECIAL_MAP:
        return _SPECIAL_MAP[symbol]
    if "." not in symbol:
        raise ValueError(f"无法识别的 symbol 格式（缺少交易所后缀）: {symbol}")
    num, suffix = symbol.rsplit(".", 1)
    suffix = suffix.upper()
    if suffix not in ("SH", "SZ"):
        raise ValueError(f"不支持的交易所后缀: {suffix}")
    return f"{suffix.lower()}.{num}"


def from_baostock_code(bs_code: str) -> str:
    """BaoStock code (如 sh.600000) 转回仓库 symbol (如 600000.SH)。"""
    market, num = bs_code.split(".")
    return f"{num}.{market.upper()}"


# --------------------------------------------------------------------------- #
# BaoStock 适配器
# --------------------------------------------------------------------------- #
class BaoStockDataService(MarketDataService):
    """通过 BaoStock 拉取真实 A 股日 K，带本地 CSV 缓存。

    Parameters
    ----------
    cache_dir : str | Path | None
        本地缓存目录。设为 None 则不缓存（每次联网拉取）。
    adjust : str
        复权方式："2"=前复权（默认），"1"=后复权，"3"=不复权。
    """

    def __init__(
        self,
        cache_dir: str | Path | None = None,
        adjust: str = "2",
    ) -> None:
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.adjust = adjust
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ---- 公开接口 --------------------------------------------------------- #
    def get_bars(
        self,
        symbols: list[str],
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Bar]:
        start = start or datetime(2020, 1, 1)
        end = end or datetime.today()
        start_str = start.strftime("%Y-%m-%d")
        end_str = end.strftime("%Y-%m-%d")
        bars: list[Bar] = []
        for symbol in symbols:
            bs_code = to_baostock_code(symbol)
            rows = self._fetch_with_cache(bs_code, symbol, start_str, end_str)
            for row in rows:
                dt = datetime.fromisoformat(row["date"])
                if dt < start or dt > end:
                    continue
                try:
                    bars.append(
                        Bar(
                            symbol=symbol,
                            datetime=dt,
                            open=float(row["open"]),
                            high=float(row["high"]),
                            low=float(row["low"]),
                            close=float(row["close"]),
                            volume=float(row["volume"]),
                        )
                    )
                except (ValueError, KeyError):
                    continue
        return clean_bars(bars)

    def get_hs300_symbols(self) -> list[str]:
        """获取当前沪深 300 成分股列表，返回仓库格式的 symbol。"""
        try:
            import baostock as bs
        except ImportError as exc:
            raise ImportError(
                "BaoStockDataService 需要 baostock，请运行: pip install baostock"
            ) from exc

        self._login(bs)
        try:
            rs = bs.query_hs300_stocks()
            if rs.error_code != "0":
                raise RuntimeError(f"获取沪深300成分股失败: {rs.error_msg}")
            symbols: list[str] = []
            while rs.next():
                symbols.append(from_baostock_code(rs.get_row_data()[1]))
            return symbols
        finally:
            self._logout(bs)

    # ---- 内部：带缓存的拉取 ------------------------------------------------- #
    def _fetch_with_cache(
        self,
        bs_code: str,
        symbol: str,
        start_str: str,
        end_str: str,
    ) -> list[dict[str, str]]:
        if self.cache_dir:
            cache_file = self.cache_dir / f"{symbol.replace('.', '_')}.csv"
            cached = self._read_cache(cache_file, start_str, end_str)
            if cached is not None:
                return cached
        rows = self._fetch_remote(bs_code, start_str, end_str)
        if self.cache_dir:
            cache_file = self.cache_dir / f"{symbol.replace('.', '_')}.csv"
            self._write_cache(cache_file, rows)
        return rows

    def _fetch_remote(self, bs_code: str, start_str: str, end_str: str) -> list[dict[str, str]]:
        try:
            import baostock as bs
        except ImportError as exc:
            raise ImportError(
                "BaoStockDataService 需要 baostock，请运行: pip install baostock"
            ) from exc

        self._login(bs)
        try:
            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,code,open,high,low,close,volume",
                start_date=start_str,
                end_date=end_str,
                frequency="d",
                adjustflag=self.adjust,
            )
            if rs.error_code != "0":
                raise RuntimeError(f"拉取 {bs_code} 失败: {rs.error_msg}")
            rows: list[dict[str, str]] = []
            while rs.next():
                data = rs.get_row_data()
                rows.append(
                    {
                        "date": data[0],
                        "code": data[1],
                        "open": data[2],
                        "high": data[3],
                        "low": data[4],
                        "close": data[5],
                        "volume": data[6],
                    }
                )
            return rows
        finally:
            self._logout(bs)

    # ---- 缓存读写 ---------------------------------------------------------- #
    @staticmethod
    def _read_cache(path: Path, start_str: str, end_str: str) -> list[dict[str, str]] | None:
        if not path.exists():
            return None
        rows: list[dict[str, str]] = []
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                rows.append(row)
        if not rows:
            return None
        # 检查缓存是否覆盖请求范围
        dates = [r["date"] for r in rows]
        if dates and dates[0] <= start_str and dates[-1] >= end_str:
            return [r for r in rows if start_str <= r["date"] <= end_str]
        # 缓存不够覆盖，仍然返回全部（上层会再按 datetime 过滤）
        return rows

    @staticmethod
    def _write_cache(path: Path, rows: list[dict[str, str]]) -> None:
        fields = ["date", "code", "open", "high", "low", "close", "volume"]
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    # ---- BaoStock 登录/登出 ------------------------------------------------- #
    @staticmethod
    def _login(bs) -> None:
        lg = bs.login()
        if lg.error_code != "0":
            raise RuntimeError(f"BaoStock 登录失败: {lg.error_msg}")

    @staticmethod
    def _logout(bs) -> None:
        bs.logout()
