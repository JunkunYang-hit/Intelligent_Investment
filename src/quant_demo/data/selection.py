"""股票池选股标准（量化可计算部分）与动态选股排名。

老师的修改意见之一：选股要有清晰标准。本模块把标准落到可计算、可复现的规则上，
标准全文见 ``examples/SELECTION_CRITERIA.md``。

选股标准分两层：

第一层 准入筛选（本模块实现，纯行情数据可计算）：
  S1 数据完整性 —— 近 5 年交易日数 ≥ ``min_trading_days``（上市时长充足，剔除次新股）
  S2 流动性标准 —— 日均成交额 ≥ ``min_avg_turnover[市场]``（大盘股门槛，币种为市场本币）
  S3 数据质量 —— 全程无单日 |收盘涨跌幅| > ``max_day_change`` 的未解释跳变
                  （用于甄别拆股未复权、数据错误；并非交易风控阈值）
  S4 价格有效性 —— OHLC 合法且非负（由 ``Bar.__post_init__`` 在构造时保证）

第二层 定性标准（文档化，依据公开市场数据人工核对）：
  Q1 板块代表性 —— 每个目标板块选取市值最大的龙头
  Q2 高分红属性 —— 近三年平均股息率 ≥ 3% 的计入"高分红"标签
  Q3 对照价值 —— 部分板块保留两只龙头便于横向对照（如贵州茅台/五粮液）

动态选股（供策略层调用）：
  动量排名 —— 调仓日按过去 ``lookback`` 个交易日收益率降序，取前 ``top_k`` 名。

各市场成交量单位（影响成交额计算，实测校准）：
  A股主板/创业板（.SH 60x/600/601/603、.SZ 000/002/300）：volume 单位为手，
    成交额 = close × volume × 100（CNY）
  A股科创板（.SH 688xxx）：volume 单位为股，成交额 = close × volume（实测
    中芯国际按"股"计算得日均22.5亿，符合实际；按"手"则得2000亿+，荒谬）
  港股（.HK）：volume 单位为股，成交额 = close × volume（HKD）
  美股（.US）：volume 单位为股，成交额 = close × volume（USD）
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

from quant_demo.models import Bar


# --------------------------------------------------------------------------- #
# 市场工具
# --------------------------------------------------------------------------- #
def market_of(symbol: str) -> str:
    """从 symbol 后缀识别市场：.SH/.SZ -> A股，.HK -> 港股，.US -> 美股。"""
    suffix = symbol.rsplit(".", 1)[-1].upper()
    if suffix in ("SH", "SZ"):
        return suffix
    if suffix in ("HK", "US"):
        return suffix
    raise ValueError(f"无法识别的市场后缀: {symbol}")


def volume_multiplier(symbol: str) -> float:
    """成交量单位换算到股的乘数（手→×100）。"""
    num, suffix = symbol.rsplit(".", 1)
    suffix = suffix.upper()
    if suffix == "SH" and num.startswith("688"):
        return 1.0     # 科创板：腾讯接口 volume 单位为股
    if suffix in ("SH", "SZ"):
        return 100.0   # A股主板/创业板：单位为手
    if suffix in ("HK", "US"):
        return 1.0
    raise ValueError(f"无法识别的代码: {symbol}")


CURRENCY = {"SH": "CNY", "SZ": "CNY", "HK": "HKD", "US": "USD"}


# --------------------------------------------------------------------------- #
# 准入筛选
# --------------------------------------------------------------------------- #
@dataclass
class ScreenRules:
    """准入筛选阈值。

    校准依据（见 SELECTION_CRITERIA.md）：
      - A股 ±10%/±20% 涨跌停制度下单日 >25% 必为数据错误；
      - 港/美股无涨跌幅限制，真实极端行情可达 ~37%
        （例：2022-03-16 中概股维稳行情，BABA +36.8%、美团 +32.1%），
        阈值取 45% 以容纳真实行情；拆股未复权的假跳变为 -67% ~ -95%，
        远超阈值必然被捕获。
    """

    min_trading_days: int = 1190          # 5年约1209个交易日，容忍少量停牌
    min_avg_turnover: dict = field(default_factory=lambda: {
        "SH": 2.0e8, "SZ": 2.0e8,         # A股：日均成交额 ≥ 2亿元
        "HK": 2.0e8,                       # 港股：日均成交额 ≥ 2亿港元
        "US": 2.0e8,                       # 美股：日均成交额 ≥ 2亿美元
    })
    max_day_change: dict = field(default_factory=lambda: {
        "SH": 0.25, "SZ": 0.25,            # A股：涨跌停制度内不可能超25%
        "HK": 0.45, "US": 0.45,            # 港美：容纳真实极端行情，拦截拆股假跳变
    })


@dataclass
class ScreenResult:
    symbol: str
    market: str
    trading_days: int
    avg_turnover: float                    # 日均成交额（市场本币）
    max_abs_day_change: float              # 最大单日|涨跌幅|
    passed: bool
    failed_rules: list[str] = field(default_factory=list)


def avg_turnover(bars: list[Bar]) -> float:
    """日均成交额 = mean(close × volume × 单位乘数)。"""
    if not bars:
        return 0.0
    mult = volume_multiplier(bars[0].symbol)
    return sum(b.close * b.volume * mult for b in bars) / len(bars)


def max_abs_day_change(bars: list[Bar]) -> float:
    """最大单日|收盘涨跌幅|。bars 需已按时间升序。"""
    worst = 0.0
    prev: float | None = None
    for b in sorted(bars, key=lambda x: x.datetime):
        if prev is not None and prev > 0:
            worst = max(worst, abs(b.close / prev - 1))
        prev = b.close
    return worst


def screen_symbol(bars: list[Bar], rules: ScreenRules | None = None) -> ScreenResult:
    """对单一标的执行准入筛选 S1~S3（S4 由 Bar 构造保证）。"""
    rules = rules or ScreenRules()
    symbol = bars[0].symbol
    market = market_of(symbol)
    days = len(bars)
    turnover = avg_turnover(bars)
    change = max_abs_day_change(bars)

    failed: list[str] = []
    if days < rules.min_trading_days:
        failed.append(f"S1数据完整性(交易日{days}<{rules.min_trading_days})")
    if turnover < rules.min_avg_turnover[market]:
        failed.append(f"S2流动性(日均成交额{turnover/1e8:.2f}亿{CURRENCY[market]}"
                      f"<{rules.min_avg_turnover[market]/1e8:.0f}亿)")
    if change > rules.max_day_change[market]:
        failed.append(f"S3数据质量(单日跳变{change:.0%}>{rules.max_day_change[market]:.0%})")
    return ScreenResult(symbol, market, days, turnover, change, not failed, failed)


def screen_universe(bars: list[Bar], rules: ScreenRules | None = None) -> list[ScreenResult]:
    """对整个股票池执行准入筛选，按日均成交额降序返回。"""
    by_symbol: dict[str, list[Bar]] = {}
    for b in bars:
        by_symbol.setdefault(b.symbol, []).append(b)
    results = [screen_symbol(seq, rules) for seq in by_symbol.values()]
    return sorted(results, key=lambda r: -r.avg_turnover)


# --------------------------------------------------------------------------- #
# 动态选股：动量排名
# --------------------------------------------------------------------------- #
def momentum_score(bars: list[Bar], as_of: datetime, lookback: int = 60) -> float | None:
    """动量得分 = as_of 当日收盘 / lookback 个交易日前收盘 - 1。

    找不到 lookback 日前数据时返回 None（数据不足，不参与排名）。
    """
    seq = [b for b in sorted(bars, key=lambda x: x.datetime) if b.datetime <= as_of]
    if len(seq) <= lookback:
        return None
    return seq[-1].close / seq[-1 - lookback].close - 1


def momentum_rank(
    bars: list[Bar],
    as_of: datetime,
    lookback: int = 60,
    top_k: int = 5,
) -> list[tuple[str, float]]:
    """动量选股：全体标的按动量得分降序，返回前 top_k 的 (symbol, score)。

    得分为 None（数据不足）的标的不参与排名。
    """
    by_symbol: dict[str, list[Bar]] = {}
    for b in bars:
        by_symbol.setdefault(b.symbol, []).append(b)
    scored = []
    for symbol, seq in by_symbol.items():
        s = momentum_score(seq, as_of, lookback)
        if s is not None:
            scored.append((symbol, s))
    scored.sort(key=lambda x: -x[1])
    return scored[:top_k]


# --------------------------------------------------------------------------- #
# 量化选股指标：活跃度 / 波动率 / 流动性分级 / 综合排名
# --------------------------------------------------------------------------- #
# 固定绝对阈值（不依赖池子内其他股票，任何单只股票可独立判定）
# 校准依据：基于32只大盘股五年真实数据的分布范围 + 学术惯例
TURNOVER_TIERS: dict[str, tuple[float, float]] = {
    # (中线下限, 高线下限)，单位：市场本币
    "SH": (10e8, 30e8),    # A股：日均成交额 10亿=中线，30亿=高线
    "SZ": (10e8, 30e8),
    "HK": (10e8, 30e8),    # 港股：10亿港元=中线，30亿=高线
    "US": (10e8, 30e8),    # 美股：10亿美元=中线，30亿=高线
}
AMIHUD_TIERS: tuple[float, float] = (1e-11, 5e-12)   # (低活跃度线, 高活跃度线)，值越小越活跃
VOLATILITY_TIERS: tuple[float, float] = (0.30, 0.40)  # (低波动上限, 高波动下限)，中间为中波动
SHARPE_TIERS: tuple[float, float] = (0.0, 0.5)        # (合格线, 优秀线)
MAX_DRAWDOWN_REFERENCE = 0.80   # 回撤评分参考最大值（-80%对应0分）


@dataclass
class StockMetrics:
    """单只标的的全量化画像。所有指标均可由 OHLCV 日 K 计算，不依赖基本面数据。

    分级使用固定绝对阈值（TURNOVER_TIERS / AMIHUD_TIERS / VOLATILITY_TIERS），
    任何单只股票可独立判定——不依赖池子里有没有其他股票。
    """

    symbol: str
    market: str
    # ── 流动性 ──
    avg_turnover: float              # 日均成交额（市场本币）
    avg_volume: float                # 日均成交量（股）
    liquidity_tier: str              # "高" / "中" / "低"
    # ── 活跃度 ──
    avg_turnover_rate: float         # 日均换手率代理（成交量/价格波动额）
    amihud_illiquidity: float        # Amihud 非流动性指标（|收益率|/成交额）
    activity_tier: str               # "高" / "中" / "低"
    # ── 波动率与风险 ──
    annual_volatility: float         # 年化波动率
    max_drawdown: float              # 最大回撤
    vol_tier: str                    # "低波动" / "中波动" / "高波动"
    # ── 收益 ──
    total_return: float              # 区间总收益
    annual_return: float             # 年化收益
    sharpe_ratio: float              # 夏普比率（无风险利率取 2%）
    # ── 综合评分 ──
    composite_score: float = 0.0     # 综合排名得分（0~100）


def _safe_stat(values: list[float]) -> tuple[float, float]:
    """返回 (均值, 标准差)。"""
    n = len(values)
    if n == 0:
        return 0.0, 0.0
    mean = sum(values) / n
    var = sum((x - mean) ** 2 for x in values) / max(n - 1, 1)
    return mean, var ** 0.5


def _tier_by_value(value: float, low_line: float, high_line: float,
                   higher_is_better: bool = True) -> str:
    """按固定阈值三分位分级。"""
    if higher_is_better:
        if value >= high_line:
            return "高"
        elif value >= low_line:
            return "中"
        else:
            return "低"
    else:
        if value <= high_line:
            return "高"
        elif value <= low_line:
            return "中"
        else:
            return "低"


def _score_0_100(value: float, ref_low: float, ref_high: float,
                 higher_is_better: bool = True) -> float:
    """将指标值线性映射到 0~100 分。"""
    if higher_is_better:
        if value >= ref_high:
            return 100.0
        if value <= ref_low:
            return 0.0
        return (value - ref_low) / (ref_high - ref_low) * 100
    else:
        if value <= ref_high:
            return 100.0
        if value >= ref_low:
            return 0.0
        return (ref_low - value) / (ref_low - ref_high) * 100


def compute_metrics(bars: list[Bar]) -> StockMetrics:
    """从日 K 序列计算全量化画像，使用固定绝对阈值分级。

    不需要基本面数据——所有指标从 OHLCV 派生：
      - 活跃度用 Amihud 非流动性（学术标准）和换手率代理
      - 波动率用日对数收益标准差 × √244
      - 分级用固定阈值，任何单只股票可独立判定
    """
    seq = sorted(bars, key=lambda x: x.datetime)
    n = len(seq)
    closes = [b.close for b in seq]
    symbol = seq[0].symbol
    market = market_of(symbol)
    mult = volume_multiplier(symbol)
    turnover = avg_turnover(seq)

    # 日对数收益
    daily_rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, n) if closes[i - 1] > 0]
    mean_ret, std_ret = _safe_stat(daily_rets)
    ann_vol = std_ret * math.sqrt(244)

    # 最大回撤
    peak, mdd = closes[0], 0.0
    for c in closes:
        peak = max(peak, c)
        mdd = min(mdd, c / peak - 1)

    # 收益
    years = n / 244
    total_ret = closes[-1] / closes[0] - 1 if closes[0] > 0 else 0.0
    ann_ret = (closes[-1] / closes[0]) ** (1 / years) - 1 if closes[0] > 0 and years > 0 else 0.0
    rf = 0.02
    sharpe = (ann_ret - rf) / ann_vol if ann_vol > 0 else 0.0

    # Amihud 非流动性 = mean(|日收益| / 日成交额)，值越小越流动
    amihud_values = []
    for i in range(1, n):
        amt = closes[i] * seq[i].volume * mult
        if amt > 0 and closes[i - 1] > 0:
            amihud_values.append(abs(closes[i] / closes[i - 1] - 1) / amt)
    amihud = sum(amihud_values) / len(amihud_values) if amihud_values else float('inf')

    # 换手率代理 = 日均成交量 / 价格（近似；无流通股本数据，用 volume/price 作代理）
    avg_vol = sum(b.volume * mult for b in seq) / n
    avg_price = sum(closes) / n
    turnover_rate = avg_vol / avg_price if avg_price > 0 else 0.0

    # ---- 用固定绝对阈值分级（不依赖池内其他股票）---- #
    t_low, t_high = TURNOVER_TIERS[market]
    liq_tier = _tier_by_value(turnover, t_low, t_high, higher_is_better=True)

    a_low, a_high = AMIHUD_TIERS  # 1e-11, 5e-12
    act_tier = _tier_by_value(amihud, a_low, a_high, higher_is_better=False)

    v_low, v_high = VOLATILITY_TIERS  # 0.30, 0.40
    if ann_vol <= v_low:
        vol_tier = "低波动"
    elif ann_vol <= v_high:
        vol_tier = "中波动"
    else:
        vol_tier = "高波动"

    # ---- 综合评分（0~100，固定参照值）---- #
    liq_score = _score_0_100(turnover, 0.0, t_high, higher_is_better=True)
    act_score = _score_0_100(amihud, a_low * 4, a_high, higher_is_better=False) if amihud != float('inf') else 0.0
    risk_adj = max(min(sharpe / 2.0, 1.0), -1.0) * 0.5 + 0.5  # Sharpe -2~2 映射到 0~1
    risk_score = risk_adj * 100
    dd_score = (1.0 - abs(mdd) / MAX_DRAWDOWN_REFERENCE) * 100 if abs(mdd) < MAX_DRAWDOWN_REFERENCE else 0.0
    composite = (liq_score * 0.30 + act_score * 0.25 + risk_score * 0.30 + dd_score * 0.15)

    return StockMetrics(
        symbol=symbol, market=market,
        avg_turnover=turnover, avg_volume=avg_vol,
        liquidity_tier=liq_tier,
        avg_turnover_rate=turnover_rate,
        amihud_illiquidity=amihud,
        activity_tier=act_tier,
        annual_volatility=ann_vol, max_drawdown=mdd, vol_tier=vol_tier,
        total_return=total_ret, annual_return=ann_ret, sharpe_ratio=sharpe,
        composite_score=composite,
    )


def rank_and_tier(all_bars: list[Bar]) -> list[StockMetrics]:
    """对整个股票池计算指标并排名。返回按 composite_score 降序排列。

    注意：分级和评分在 compute_metrics 中用固定绝对阈值完成，
    本函数仅做批量计算和排序——单只股票用 compute_metrics 即可独立判定。
    """
    by_symbol: dict[str, list[Bar]] = {}
    for b in all_bars:
        by_symbol.setdefault(b.symbol, []).append(b)
    metrics = [compute_metrics(seq) for seq in by_symbol.values()]
    metrics.sort(key=lambda m: -m.composite_score)
    return metrics

    metrics.sort(key=lambda m: -m.composite_score)
    return metrics
