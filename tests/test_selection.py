"""选股标准模块测试：准入筛选 S1~S3 与动量排名。"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from quant_demo.data.selection import (
    ScreenRules,
    market_of,
    momentum_rank,
    momentum_score,
    screen_symbol,
    screen_universe,
    volume_multiplier,
)
from quant_demo.models import Bar


def _mk_bars(symbol: str, days: int = 1209, start_price: float = 10.0,
             volume: float = 300_000.0, start: str = "2021-09-16",
             growth: float = 0.001) -> list[Bar]:
    """构造平稳的日K序列（每日按growth增长，无跳变）。默认成交额约5亿(A股口径)。"""
    base = datetime.fromisoformat(start)
    bars = []
    price = start_price
    for i in range(days):
        price *= 1 + growth
        p = round(price, 3)
        bars.append(Bar(symbol, base + timedelta(days=i), p, p * 1.01, p * 0.99, p, volume))
    return bars


# --------------------------------------------------------------------------- #
# 市场识别与单位换算
# --------------------------------------------------------------------------- #
class TestMarket:
    def test_market_of(self) -> None:
        assert market_of("600000.SH") == "SH"
        assert market_of("000001.SZ") == "SZ"
        assert market_of("0700.HK") == "HK"
        assert market_of("AAPL.US") == "US"

    def test_market_of_invalid(self) -> None:
        with pytest.raises(ValueError):
            market_of("600000.HKEX")

    def test_volume_multiplier(self) -> None:
        assert volume_multiplier("600000.SH") == 100.0   # 沪主板：手
        assert volume_multiplier("688981.SH") == 1.0     # 科创板：股
        assert volume_multiplier("300750.SZ") == 100.0   # 创业板：手
        assert volume_multiplier("0700.HK") == 1.0       # 港股：股
        assert volume_multiplier("AAPL.US") == 1.0       # 美股：股


# --------------------------------------------------------------------------- #
# 准入筛选
# --------------------------------------------------------------------------- #
class TestScreen:
    def test_normal_stock_passes_all_rules(self) -> None:
        # 10元 × 100,000手 × 100 = 10亿/日 > 2亿 ✓
        bars = _mk_bars("600000.SH")
        result = screen_symbol(bars)
        assert result.passed, result.failed_rules
        assert result.trading_days == 1209
        assert result.avg_turnover > 2e8

    def test_s1_insufficient_trading_days(self) -> None:
        bars = _mk_bars("600000.SH", days=1000)
        result = screen_symbol(bars)
        assert not result.passed
        assert any("S1" in f for f in result.failed_rules)

    def test_s2_low_turnover(self) -> None:
        # 10元 × 1000手 × 100 = 1000万/日 < 2亿 ✗
        bars = _mk_bars("600000.SH", volume=1_000.0)
        result = screen_symbol(bars)
        assert not result.passed
        assert any("S2" in f for f in result.failed_rules)

    def test_s3_split_like_jump_detected(self) -> None:
        bars = _mk_bars("AAPL.US")
        # 人为制造 -90% 假跳变（模拟拆股未复权）
        victim = bars[600]
        bars[600] = Bar(victim.symbol, victim.datetime, victim.open * 0.1,
                        victim.high * 0.1, victim.low * 0.1, victim.close * 0.1, victim.volume)
        result = screen_symbol(bars)
        assert not result.passed
        assert any("S3" in f for f in result.failed_rules)

    def test_s3_real_extreme_move_allowed_for_hk_us(self) -> None:
        """港美市场 +36.8%（真实2022-03-16级行情）不应触发 S3。"""
        bars = _mk_bars("BABA.US", volume=20_000_000.0)
        victim = bars[600]
        new_close = round(victim.close * 1.368, 3)
        new_open = round(victim.close * 1.2, 3)
        bars[600] = Bar(victim.symbol, victim.datetime, new_open,
                        round(new_close * 1.01, 3), round(new_open * 0.99, 3),
                        new_close, victim.volume)
        result = screen_symbol(bars)
        assert result.passed, result.failed_rules

    def test_screen_universe_sorted_by_turnover(self) -> None:
        big = _mk_bars("600000.SH", volume=200_000.0)
        small = _mk_bars("000001.SZ", volume=50_000.0)
        results = screen_universe(big + small)
        assert [r.symbol for r in results] == ["600000.SH", "000001.SZ"]


# --------------------------------------------------------------------------- #
# 动量排名
# --------------------------------------------------------------------------- #
class TestMomentum:
    def test_score_basic(self) -> None:
        bars = _mk_bars("600000.SH", days=100)
        as_of = bars[-1].datetime
        score = momentum_score(bars, as_of, lookback=60)
        # 每日+0.1% → 60日 ≈ 1.001^60 - 1
        assert score == pytest.approx(1.001**60 - 1, rel=0.01)

    def test_score_none_when_insufficient_data(self) -> None:
        bars = _mk_bars("600000.SH", days=50)
        assert momentum_score(bars, bars[-1].datetime, lookback=60) is None

    def test_rank_orders_by_momentum(self) -> None:
        slow = _mk_bars("600900.SH", days=100, start_price=10.0, growth=0.001)
        rocket = _mk_bars("601899.SH", days=100, start_price=10.0, growth=0.01)
        ranked = momentum_rank(slow + rocket, as_of=slow[-1].datetime, lookback=60, top_k=2)
        assert ranked[0][0] == "601899.SH"
        assert len(ranked) == 2

    def test_rank_excludes_insufficient(self) -> None:
        long_bars = _mk_bars("600000.SH", days=100)
        short_bars = _mk_bars("000001.SZ", days=30)
        ranked = momentum_rank(long_bars + short_bars, as_of=long_bars[-1].datetime,
                               lookback=60, top_k=5)
        assert [s for s, _ in ranked] == ["600000.SH"]
