"""重新生成 examples/demo_daily.csv（510300.SH 最近5年日K，前复权）。

数据来源：腾讯行情接口（免费、无需注册、支持 ETF 与指定日期范围）。
用法：
    python scripts/fetch_etf_data.py            # 默认拉最近5年
    python scripts/fetch_etf_data.py --start 2023-01-01 --end 2025-12-31

腾讯单次请求上限约 640 根，脚本自动按年分段拉取后拼接去重。
输出格式与 README 约定一致：symbol,date,open,high,low,close,volume
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from quant_demo.models import Bar  # noqa: E402

API = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
SEGMENT_LIMIT = 640


def fetch_segment(symbol: str, start: str, end: str) -> list[list]:
    """拉取一段日期范围的日K。返回腾讯原始行 [date, open, close, high, low, volume, ...]。"""
    url = f"{API}?param={symbol},day,{start},{end},{SEGMENT_LIMIT},qfq"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    data = json.loads(urllib.request.urlopen(req, timeout=20).read().decode("utf-8"))
    days = data["data"][symbol]
    key = "qfqday" if "qfqday" in days else "day"
    return days[key]


def fetch_history(symbol: str, start: date, end: date) -> list[Bar]:
    """按年分段拉取并拼接，去重后转为 Bar 列表。"""
    by_date: dict[str, list] = {}
    seg_start = start
    while seg_start <= end:
        seg_end = min(date(seg_start.year, 12, 31), end)
        rows = fetch_segment(symbol, seg_start.isoformat(), seg_end.isoformat())
        print(f"  {seg_start} ~ {seg_end}: {len(rows)} 根")
        for r in rows:
            by_date[r[0]] = r
        seg_start = date(seg_end.year + 1, 1, 1)

    bars: list[Bar] = []
    for d in sorted(by_date):
        r = by_date[d]
        bars.append(
            Bar(
                symbol="510300.SH",
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
    parser = argparse.ArgumentParser(description="拉取 510300 日K并写入 examples/demo_daily.csv")
    parser.add_argument("--start", default=(date.today() - timedelta(days=365 * 5)).isoformat())
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--output", default=str(REPO_ROOT / "examples" / "demo_daily.csv"))
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    print(f"拉取 sh510300 {start} ~ {end} ...")
    bars = fetch_history("sh510300", start, end)
    print(f"共 {len(bars)} 个交易日: {bars[0].datetime.date()} ~ {bars[-1].datetime.date()}")

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["symbol", "date", "open", "high", "low", "close", "volume"])
        for b in bars:
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
    print(f"已写入 {out}")


if __name__ == "__main__":
    main()
