"""拉取股票池全部标的最近5年日K，合并写入 examples/stocks_5y.csv。

数据来源：腾讯行情接口（前复权 qfq）。
股票池清单与板块标注见 examples/UNIVERSE.md。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from quant_demo.models import Bar  # noqa: E402

API = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
SEGMENT_LIMIT = 640
SEGMENT_SLEEP = 0.4  # 每段请求间隔，避免触发限流

# 股票池：腾讯代码 -> 仓库 symbol（板块标注见 UNIVERSE.md）
UNIVERSE: list[tuple[str, str]] = [
    ("sh510300", "510300.SH"),   # 沪深300ETF（大盘基准）
    ("sh600519", "600519.SH"),   # 贵州茅台
    ("sz000858", "000858.SZ"),   # 五粮液
    ("sh600036", "600036.SH"),   # 招商银行
    ("sh601318", "601318.SH"),   # 中国平安
    ("sz300750", "300750.SZ"),   # 宁德时代
    ("sz002594", "002594.SZ"),   # 比亚迪
    ("sh600276", "600276.SH"),   # 恒瑞医药
    ("sh688981", "688981.SH"),   # 中芯国际
    ("sh600900", "600900.SH"),   # 长江电力
    ("sh601857", "601857.SH"),   # 中国石油
    ("sh601899", "601899.SH"),   # 紫金矿业
    ("sz000651", "000651.SZ"),   # 格力电器
]


def fetch_segment(tx_code: str, start: str, end: str) -> list[list]:
    url = f"{API}?param={tx_code},day,{start},{end},{SEGMENT_LIMIT},qfq"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    data = json.loads(urllib.request.urlopen(req, timeout=20).read().decode("utf-8"))
    days = data["data"][tx_code]
    key = "qfqday" if "qfqday" in days else "day"
    return days[key]


def fetch_one(tx_code: str, symbol: str, start: date, end: date) -> list[Bar]:
    """按年分段拉取单只标的，去重后转 Bar。"""
    by_date: dict[str, list] = {}
    seg_start = start
    while seg_start <= end:
        seg_end = min(date(seg_start.year, 12, 31), end)
        rows = fetch_segment(tx_code, seg_start.isoformat(), seg_end.isoformat())
        print(f"  {symbol} {seg_start}~{seg_end}: {len(rows)} 根")
        for r in rows:
            by_date[r[0]] = r
        seg_start = date(seg_end.year + 1, 1, 1)
        time.sleep(SEGMENT_SLEEP)

    bars: list[Bar] = []
    for d in sorted(by_date):
        r = by_date[d]
        bars.append(
            Bar(
                symbol=symbol,
                datetime=datetime.fromisoformat(r[0]),
                open=float(r[1]),
                high=float(r[3]),
                low=float(r[4]),
                close=float(r[2]),
                volume=float(r[5]),
            )
        )
    return bars


def main() -> None:
    parser = argparse.ArgumentParser(description="拉取股票池5年日K写入 examples/stocks_5y.csv")
    parser.add_argument("--start", default=(date.today() - timedelta(days=365 * 5)).isoformat())
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--output", default=str(REPO_ROOT / "examples" / "stocks_5y.csv"))
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    all_bars: list[Bar] = []
    for tx_code, symbol in UNIVERSE:
        print(f"拉取 {symbol} ...")
        bars = fetch_one(tx_code, symbol, start, end)
        print(f"  -> {len(bars)} 个交易日: "
              f"{bars[0].datetime.date()} ~ {bars[-1].datetime.date()}")
        all_bars.extend(bars)
        time.sleep(SEGMENT_SLEEP)

    all_bars.sort(key=lambda b: (b.datetime, b.symbol))
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["symbol", "date", "open", "high", "low", "close", "volume"])
        for b in all_bars:
            writer.writerow(
                [
                    b.symbol,
                    b.datetime.strftime("%Y-%m-%d"),
                    round(b.open, 3),
                    round(b.high, 3),
                    round(b.low, 3),
                    round(b.close, 3),
                    int(b.volume),
                ]
            )
    symbols = sorted({b.symbol for b in all_bars})
    print(f"\n已写入 {out}: {len(all_bars)} 行, {len(symbols)} 只标的")
    print(f"标的: {symbols}")


if __name__ == "__main__":
    main()
