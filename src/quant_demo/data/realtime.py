"""实时行情接口（腾讯免费通道，无需任何账户）。

用于实盘/演示场景的“当下价格”获取：
  - 回测用历史日K（CsvDataService 等），实盘撮合需要实时价；
  - 本模块提供 ``get_realtime_quotes``，一次请求多只标的的现价/今开/最高/最低；
  - 是演示链路“真实行情 → 下单”的价格来源，也是券商网关切换前的行情兜底。

字段口径（腾讯 qt.gtimg.cn，~分隔）：
  1=名称 3=现价 4=昨收 5=今开 6=成交量(手/股) 33=最高 34=最低 30=时间
  A股成交量单位为手；港股为股。价格币种为市场本币。
"""

from __future__ import annotations

import urllib.request
from dataclasses import dataclass

from .selection import market_of


@dataclass(frozen=True)
class RealtimeQuote:
    symbol: str
    name: str
    price: float          # 现价（市场本币）
    pre_close: float      # 昨收
    open: float           # 今开
    high: float
    low: float
    volume: float         # 成交量（A股为手，港美股为股）
    time: str             # 行情时间戳（交易所当地）


def _to_tencent_code(symbol: str) -> str:
    """内部代码 -> 腾讯实时接口代码：600000.SH -> sh600000，0700.HK -> hk00700（5位补零）。"""
    num, suffix = symbol.rsplit(".", 1)
    suffix = suffix.upper()
    if suffix in ("SH", "SZ"):
        return f"{suffix.lower()}{num}"
    if suffix == "HK":
        return f"hk{num.zfill(5)}"          # 港股代码在腾讯接口中为5位补零
    if suffix == "US":
        return f"us{num}.OQ"
    raise ValueError(f"不支持的市场: {symbol}")


def _from_tencent_code(code: str) -> str:
    if code.startswith(("sh", "sz")):
        return f"{code[2:]}.{code[:2].upper()}"
    if code.startswith("hk"):
        return f"{code[2:].lstrip('0').zfill(4)}.HK"   # 00700 -> 0700.HK（内部4位约定）
    return code


def get_realtime_quotes(symbols: list[str]) -> dict[str, RealtimeQuote]:
    """批量获取实时行情。返回 {内部symbol: RealtimeQuote}；失败或停牌的标的不出现在结果里。"""
    if not symbols:
        return {}
    codes = [_to_tencent_code(s) for s in symbols]
    url = "https://qt.gtimg.cn/q=" + ",".join(codes)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    raw = urllib.request.urlopen(req, timeout=10).read().decode("gbk", errors="replace")

    result: dict[str, RealtimeQuote] = {}
    for line in raw.strip().split(";"):
        line = line.strip()
        if not line or "=" not in line or '"' not in line:
            continue
        code = line.split("=", 1)[0].replace("v_", "")
        fields = line.split('"')[1].split("~")
        if len(fields) < 35:
            continue
        symbol = _from_tencent_code(code)
        try:
            price = float(fields[3])
            if price <= 0:      # 停牌/无行情
                continue
            result[symbol] = RealtimeQuote(
                symbol=symbol,
                name=fields[1],
                price=price,
                pre_close=float(fields[4]),
                open=float(fields[5]),
                high=float(fields[33]),
                low=float(fields[34]),
                volume=float(fields[6]),
                time=fields[30],
            )
        except (ValueError, IndexError):
            continue
    return result


def get_last_price(symbol: str) -> float:
    """单只标的的最新价（演示与网关 market 单参考价的便捷入口）。"""
    quotes = get_realtime_quotes([symbol])
    if symbol not in quotes:
        raise ConnectionError(f"获取 {symbol} 实时行情失败")
    return quotes[symbol].price
