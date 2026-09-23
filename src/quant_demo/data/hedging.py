"""跨市场对冲策略模块。

回应课程要求：考虑股票对冲情况。本模块提供三类对冲工具：

1. A/H 股溢价对冲：同一家公司在 A 股和港股同时上市时，两个市场定价
   存在系统性偏差（A 股通常溢价）。当溢价偏离历史均值时，做多低估端、
   做空高估端，待均值回归获利。

2. 板块配对对冲：同一板块的龙头股走势高度相关，当价差偏离历史均值
   时，做多相对低估的、做空相对高估的（配对交易）。

3. 指数对冲：做多个股、做空 ETF/指数对冲系统性风险（Beta 中性）。

对冲可行性说明（诚实边界）：
  - A 股个股不能直接做空（融券限制多），但可以通过股指期货（IF/IC）
    或 ETF 融券实现对冲；
  - 港股和美股可以做空（需券商支持卖空）；
  - 本模块输出对冲信号（多哪只、空哪只、目标权重），实际做空能力
    取决于 broker 网关和券商权限。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import NamedTuple

from quant_demo.models import Bar


# --------------------------------------------------------------------------- #
# A/H 股配对表（同一公司在两地上市的代码对照）
# --------------------------------------------------------------------------- #
# 格式: (A股代码, 港股代码, 公司名)
# 仅列示池内已有的 + 常见的 A/H 股对
AH_PAIRS: list[tuple[str, str, str]] = [
    ("601318.SH", "2318.HK", "中国平安"),
    ("601857.SH", "0857.HK", "中国石油"),
    ("601899.SH", "2899.HK", "紫金矿业"),
    ("600036.SH", "3968.HK", "招商银行"),
    ("601628.SH", "2628.HK", "中国人寿"),
    ("600519.SH", None,      "贵州茅台"),   # 仅A上市，无H股，列示供参考
]

# 板块配对（同板块跨市场龙头，用于配对交易）
SECTOR_PAIRS: list[tuple[str, str, str]] = [
    # (标的A, 标的B, 板块)
    ("600036.SH", "JPM.US",   "银行"),
    ("601857.SH", "XOM.US",   "能源"),
    ("600519.SH", "KO.US",    "消费饮料"),
    ("600276.SH", "JPM.US",   "医药×金融（对照组）"),  # 跨板块对照，预期低相关
    ("0700.HK",   "MSFT.US",  "科技"),
    ("9988.HK",   "BABA.US",  "同公司两地上市"),
]


# --------------------------------------------------------------------------- #
# 相关性计算
# --------------------------------------------------------------------------- #
def daily_returns(bars: list[Bar]) -> list[float]:
    """日对数收益率序列。"""
    seq = sorted(bars, key=lambda x: x.datetime)
    return [math.log(seq[i].close / seq[i - 1].close)
            for i in range(1, len(seq)) if seq[i - 1].close > 0]


def correlation(bars_a: list[Bar], bars_b: list[Bar]) -> float:
    """两只标的的日收益率皮尔逊相关系数。

    按日期对齐后计算；重叠交易日不足 60 天返回 0（视为不相关）。
    """
    by_date_a = {b.datetime.date(): b.close for b in bars_a}
    by_date_b = {b.datetime.date(): b.close for b in bars_b}
    common = sorted(set(by_date_a) & set(by_date_b))
    if len(common) < 60:
        return 0.0

    rets_a, rets_b = [], []
    for i in range(1, len(common)):
        d, d_prev = common[i], common[i - 1]
        pa, pb = by_date_a[d_prev], by_date_b[d_prev]
        if pa > 0 and pb > 0:
            rets_a.append(math.log(by_date_a[d] / pa))
            rets_b.append(math.log(by_date_b[d] / pb))

    n = len(rets_a)
    if n < 30:
        return 0.0
    mean_a = sum(rets_a) / n
    mean_b = sum(rets_b) / n
    cov = sum((rets_a[i] - mean_a) * (rets_b[i] - mean_b) for i in range(n)) / (n - 1)
    std_a = math.sqrt(sum((x - mean_a) ** 2 for x in rets_a) / (n - 1))
    std_b = math.sqrt(sum((x - mean_b) ** 2 for x in rets_b) / (n - 1))
    if std_a == 0 or std_b == 0:
        return 0.0
    return cov / (std_a * std_b)


# --------------------------------------------------------------------------- #
# 价差 / Z-Score
# --------------------------------------------------------------------------- #
def price_ratio_series(bars_a: list[Bar], bars_b: list[Bar]) -> list[tuple[datetime, float]]:
    """两只标的的价比序列 A/B（按日期对齐）。"""
    by_date_b = {b.datetime.date(): b.close for b in bars_b}
    result = []
    for b in sorted(bars_a, key=lambda x: x.datetime):
        d = b.datetime.date()
        if d in by_date_b and by_date_b[d] > 0:
            result.append((b.datetime, b.close / by_date_b[d]))
    return result


@dataclass
class SpreadSignal:
    """配对交易信号。"""
    long_symbol: str            # 做多端
    short_symbol: str           # 做空端
    pair_type: str              # "A/H溢价" / "板块配对" / "指数对冲"
    correlation: float          # 相关系数
    z_score: float              # 当前价比 Z-Score（>0 表示 A 相对 B 偏高）
    description: str            # 人类可读说明
    action: str                 # "做多A做空B" / "做多B做空A" / "无信号"


def pair_signal(
    bars_a: list[Bar],
    bars_b: list[Bar],
    symbol_a: str,
    symbol_b: str,
    pair_type: str,
    entry_z: float = 2.0,
    lookback: int = 120,
) -> SpreadSignal:
    """计算配对交易信号。

    当价比 Z-Score 超过 ``entry_z`` 时产生信号：
      Z > +entry_z → A 相对 B 高估 → 做空 A、做多 B
      Z < -entry_z → A 相对 B 低估 → 做多 A、做空 B
      |Z| < entry_z → 无信号（价差在正常范围内）
    """
    corr = correlation(bars_a, bars_b)
    ratios = price_ratio_series(bars_a, bars_b)
    if len(ratios) < lookback:
        return SpreadSignal(symbol_a, symbol_b, pair_type, corr, 0.0,
                            f"数据不足({len(ratios)}<{lookback})，无法计算", "无信号")

    window = [r for _, r in ratios[-lookback:]]
    current = window[-1]
    mean = sum(window) / len(window)
    std = math.sqrt(sum((x - mean) ** 2 for x in window) / (len(window) - 1))
    z = (current - mean) / std if std > 0 else 0.0

    if z > entry_z:
        action = f"做空{symbol_a}+做多{symbol_b}"
        desc = f"价比 Z={z:.2f}，{symbol_a}相对{symbol_b}偏高，等待均值回归"
    elif z < -entry_z:
        action = f"做多{symbol_a}+做空{symbol_b}"
        desc = f"价比 Z={z:.2f}，{symbol_a}相对{symbol_b}偏低，等待均值回归"
    else:
        action = "无信号"
        desc = f"价比 Z={z:.2f}，在正常范围(±{entry_z})内"

    return SpreadSignal(symbol_a, symbol_b, pair_type, corr, z, desc, action)


# --------------------------------------------------------------------------- #
# 批量扫描：全池配对信号
# --------------------------------------------------------------------------- #
def scan_hedge_pairs(
    bars_by_symbol: dict[str, list[Bar]],
    entry_z: float = 2.0,
) -> list[SpreadSignal]:
    """扫描所有预定义配对，返回当前有信号或高相关的配对列表。

    ``bars_by_symbol``: {symbol: [Bar, ...]}，通常由 ``CsvDataService.get_bars`` 结果分组。
    """
    signals: list[SpreadSignal] = []

    # A/H 股配对
    for a_code, h_code, name in AH_PAIRS:
        if h_code is None:
            continue
        if a_code in bars_by_symbol and h_code in bars_by_symbol:
            sig = pair_signal(
                bars_by_symbol[a_code], bars_by_symbol[h_code],
                a_code, h_code, "A/H溢价", entry_z,
            )
            sig.description = f"[{name}] " + sig.description
            signals.append(sig)

    # 板块配对
    for sym_a, sym_b, sector in SECTOR_PAIRS:
        if sym_a in bars_by_symbol and sym_b in bars_by_symbol:
            sig = pair_signal(
                bars_by_symbol[sym_a], bars_by_symbol[sym_b],
                sym_a, sym_b, "板块配对", entry_z,
            )
            sig.description = f"[{sector}] " + sig.description
            signals.append(sig)

    # 按相关系数绝对值降序排列
    signals.sort(key=lambda s: -abs(s.correlation))
    return signals


# --------------------------------------------------------------------------- #
# Beta 中性对冲
# --------------------------------------------------------------------------- #
def beta(stock_bars: list[Bar], index_bars: list[Bar]) -> float:
    """计算个股相对于基准的 Beta 系数。"""
    by_date_idx = {b.datetime.date(): b.close for b in index_bars}
    seq = sorted(stock_bars, key=lambda x: x.datetime)
    stock_rets, idx_rets = [], []
    prev_s, prev_i = None, None
    for b in seq:
        d = b.datetime.date()
        if d not in by_date_idx:
            continue
        s_close, i_close = b.close, by_date_idx[d]
        if prev_s is not None and prev_i is not None and prev_s > 0 and prev_i > 0:
            stock_rets.append(math.log(s_close / prev_s))
            idx_rets.append(math.log(i_close / prev_i))
        prev_s, prev_i = s_close, i_close

    n = len(stock_rets)
    if n < 30:
        return 1.0
    mean_s = sum(stock_rets) / n
    mean_i = sum(idx_rets) / n
    cov = sum((stock_rets[i] - mean_s) * (idx_rets[i] - mean_i) for i in range(n)) / (n - 1)
    var_i = sum((x - mean_i) ** 2 for x in idx_rets) / (n - 1)
    return cov / var_i if var_i > 0 else 1.0


@dataclass
class HedgePlan:
    """Beta 中性对冲方案。"""
    long_symbol: str
    short_symbol: str           # 对冲标的（通常是 ETF/指数）
    beta_value: float
    hedge_ratio: float          # 对冲比例 = 1 / beta（做空多少份对冲标的）
    description: str


def beta_neutral_plan(
    stock_bars: list[Bar],
    index_bars: list[Bar],
    stock_symbol: str,
    index_symbol: str,
) -> HedgePlan:
    """生成 Beta 中性对冲方案：做多个股，做空指数/ETF 对冲系统性风险。

    对冲比例 = 1 / Beta，即每持有 1 元个股，做空 1/Beta 元指数。
    """
    b = beta(stock_bars, index_bars)
    if b <= 0:
        b = 1.0  # 防御性处理
    ratio = 1.0 / b
    return HedgePlan(
        long_symbol=stock_symbol,
        short_symbol=index_symbol,
        beta_value=b,
        hedge_ratio=ratio,
        description=f"做多{stock_symbol}（Beta={b:.2f}），做空{ratio:.2f}份{index_symbol}实现Beta中性",
    )
