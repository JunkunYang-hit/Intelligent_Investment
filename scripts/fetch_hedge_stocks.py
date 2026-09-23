# -*- coding: utf-8 -*-
"""拉取扩展股票池：增加 A/H 配对标的 + 更多美股/港股，含对冲配对。"""
import sys, io, csv, json, time, urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from quant_demo.models import Bar
from quant_demo.data.selection import max_abs_day_change

API = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
SPLIT_JUMP = 0.45

# 新增标的（已有的不重复拉）
NEW_SYMBOLS = [
    # A/H 配对的港股端（港股代码4位补零）
    ("hk02318", "2318.HK"),   # 中国平安 H
    ("hk00857", "0857.HK"),   # 中国石油 H
    ("hk02899", "2899.HK"),   # 紫金矿业 H
    ("hk03968", "3968.HK"),   # 招商银行 H
    ("hk02628", "2628.HK"),   # 中国人寿 H
    # 更多美股（剔除 WMT 因 2024-01 拆股；选无拆股标的）
    ("usBAC.N",   "BAC.US"),  # 美国银行
    ("usPG.N",    "PG.US"),   # 宝洁
    ("usDIS.N",   "DIS.US"),  # 迪士尼
]

def fetch_segment(code, d1, d2):
    url = f"{API}?param={code},day,{d1},{d2},640,qfq"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    data = json.loads(urllib.request.urlopen(req, timeout=20).read().decode("utf-8"))
    days = data["data"][code]
    key = "qfqday" if "qfqday" in days else "day"
    return days[key]

def fetch_one(code, symbol, start, end):
    by_date = {}
    seg = start
    while seg <= end:
        seg_end = min(date(seg.year, 12, 31), end)
        for r in fetch_segment(code, seg.isoformat(), seg_end.isoformat()):
            by_date[r[0]] = r
        seg = date(seg_end.year + 1, 1, 1)
        time.sleep(0.4)
    bars = []
    for d in sorted(by_date):
        r = by_date[d]
        bars.append(Bar(symbol, datetime.fromisoformat(d),
                        float(r[1]), float(r[3]), float(r[4]), float(r[2]), float(r[5])))
    jump = max_abs_day_change(bars)
    if jump > SPLIT_JUMP:
        raise RuntimeError(f"{symbol} 跳变 {jump:.0%} > {SPLIT_JUMP:.0%}，拒绝")
    return bars

start = date(2021, 9, 17)
end = date(2026, 9, 17)
out = Path(__file__).resolve().parent.parent / "examples" / "hedge_stocks_5y.csv"

all_bars = []
for code, symbol in NEW_SYMBOLS:
    print(f"拉取 {symbol}...")
    bars = fetch_one(code, symbol, start, end)
    print(f"  -> {len(bars)} 根, 跳变 {max_abs_day_change(bars):.1%}")
    all_bars.extend(bars)

all_bars.sort(key=lambda b: (b.datetime, b.symbol))
with out.open("w", encoding="utf-8", newline="") as f:
    w = csv.writer(f)
    w.writerow(["symbol", "date", "open", "high", "low", "close", "volume"])
    for b in all_bars:
        w.writerow([b.symbol, b.datetime.strftime("%Y-%m-%d"),
                    round(b.open, 3), round(b.high, 3), round(b.low, 3),
                    round(b.close, 3), int(b.volume)])
print(f"\n已写入 {out}: {len(all_bars)} 行, {len(NEW_SYMBOLS)} 只")
