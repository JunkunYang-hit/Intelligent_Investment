"""拉取港股/美股股票池最近5年日K，写入 examples/global_stocks_5y.csv。

数据来源：腾讯行情接口（qfq 前复权）。
美股代码格式：us<代码>.OQ（纳斯达克）/ us<代码>.N（纽交所）。

⚠️ 数据源限制（已甄别，见 examples/GLOBAL_UNIVERSE.md）：
  该接口对美股「拆股」不做复权处理（例：英伟达2024-06 1拆10 会在数据中
  呈现为单日-90%假跳变）。因此美股池只收录 2021-09~2026-09 窗口内无拆股
  的标的；脚本对每只标的执行「单日跳变>35%」检查，命中即报错退出。

港股/美股的日期均为当地交易所交易日历（美东/港），跨市场对齐由使用方处理。
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
from quant_demo.data.selection import max_abs_day_change  # noqa: E402

API = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
SEGMENT_LIMIT = 640
SEGMENT_SLEEP = 0.4
# 单日|涨跌幅|超过此值 => 疑似拆股未复权/脏数据，拒绝写入。
# 校准：2022-03-16 中概股维稳行情 BABA +36.8%、美团 +32.1% 为真实数据，
# 故阈值取 0.45 容纳真实极端行情；拆股假跳变（NVDA -90%、GOOG -95%、
# TSLA -67%，实测）远超阈值必然被拦截。
SPLIT_JUMP_LIMIT = 0.45

# 腾讯代码 -> 仓库 symbol（标注见 examples/GLOBAL_UNIVERSE.md）
UNIVERSE: list[tuple[str, str]] = [
    # 港股
    ("hk00700", "0700.HK"),   # 腾讯控股
    ("hk03690", "3690.HK"),   # 美团-W
    ("hk09988", "9988.HK"),   # 阿里巴巴-W
    ("hk01810", "1810.HK"),   # 小米集团-W
    ("hk00005", "0005.HK"),   # 汇丰控股
    # 美股（仅窗口内无拆股标的；NVDA/GOOG/TSLA 因拆股未复权被剔除）
    ("usAAPL.OQ", "AAPL.US"),  # 苹果
    ("usMSFT.OQ", "MSFT.US"),  # 微软
    ("usBABA.N", "BABA.US"),   # 阿里巴巴
    ("usJPM.N", "JPM.US"),     # 摩根大通
    ("usKO.N", "KO.US"),       # 可口可乐
    ("usXOM.N", "XOM.US"),     # 埃克森美孚
]


def fetch_segment(tx_code: str, start: str, end: str) -> list[list]:
    url = f"{API}?param={tx_code},day,{start},{end},{SEGMENT_LIMIT},qfq"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    data = json.loads(urllib.request.urlopen(req, timeout=20).read().decode("utf-8"))
    days = data["data"][tx_code]
    key = "qfqday" if "qfqday" in days else "day"
    return days[key]


def fetch_one(tx_code: str, symbol: str, start: date, end: date) -> list[Bar]:
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
    jump = max_abs_day_change(bars)
    if jump > SPLIT_JUMP_LIMIT:
        raise RuntimeError(
            f"{symbol} 检测到单日|涨跌幅| {jump:.0%} > {SPLIT_JUMP_LIMIT:.0%}，"
            f"疑似拆股未复权或脏数据，拒绝写入。"
        )
    return bars


def main() -> None:
    parser = argparse.ArgumentParser(description="拉取港美股5年日K写入 examples/global_stocks_5y.csv")
    parser.add_argument("--start", default=(date.today() - timedelta(days=365 * 5)).isoformat())
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--output", default=str(REPO_ROOT / "examples" / "global_stocks_5y.csv"))
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    all_bars: list[Bar] = []
    for tx_code, symbol in UNIVERSE:
        print(f"拉取 {symbol} ...")
        bars = fetch_one(tx_code, symbol, start, end)
        print(f"  -> {len(bars)} 个交易日，单日最大跳变 "
              f"{max_abs_day_change(bars):.1%}（校验通过）")
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
