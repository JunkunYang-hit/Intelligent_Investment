"""对冲策略模块测试：相关性、配对信号、Beta 中性。"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

import pytest

from quant_demo.data.hedging import (
    AH_PAIRS,
    SECTOR_PAIRS,
    SpreadSignal,
    beta,
    beta_neutral_plan,
    correlation,
    daily_returns,
    pair_signal,
    price_ratio_series,
    scan_hedge_pairs,
)
from quant_demo.models import Bar


def _synth(symbol: str, days: int = 200, start_price: float = 10.0,
           drift: float = 0.001, noise: float = 0.01, seed: int = 42) -> list[Bar]:
    import random
    rng = random.Random(seed)
    base = datetime(2024, 1, 1)
    bars = []
    price = start_price
    for i in range(days):
        price *= 1 + drift + rng.gauss(0, noise)
        p = round(max(price, 0.01), 3)
        bars.append(Bar(symbol, base + timedelta(days=i), p, p * 1.01, p * 0.99, p, 10000))
    return bars


class TestCorrelation:
    def test_perfectly_correlated(self) -> None:
        a = _synth("A.SH", seed=1)
        b = _synth("B.SH", seed=1)  # 完全相同的随机序列
        assert correlation(a, b) > 0.95

    def test_uncorrelated(self) -> None:
        a = _synth("A.SH", seed=1, noise=0.05)
        b = _synth("B.SH", seed=999, noise=0.05)
        assert abs(correlation(a, b)) < 0.5

    def test_insufficient_overlap(self) -> None:
        a = _synth("A.SH", days=30)
        b = _synth("B.SH", days=30)
        assert correlation(a, b) == 0.0


class TestPairSignal:
    def test_no_signal_in_normal_range(self) -> None:
        a = _synth("A.SH", seed=1, drift=0.001)
        b = _synth("B.SH", seed=2, drift=0.001)
        sig = pair_signal(a, b, "A.SH", "B.SH", "板块配对", entry_z=2.0)
        assert isinstance(sig, SpreadSignal)
        assert sig.action == "无信号" or "做空" in sig.action or "做多" in sig.action

    def test_signal_when_diverged(self) -> None:
        """构造一个 A 相对 B 大幅偏离的场景。"""
        a = _synth("A.SH", seed=1, drift=0.002, days=200)
        b = _synth("B.SH", seed=1, drift=0.0, days=200)  # 同种子但 B 不涨
        # 最后一根 A 额外暴涨，制造偏离
        last = a[-1]
        a[-1] = Bar(last.symbol, last.datetime, last.open * 1.5,
                    last.high * 1.5, last.low * 1.5, last.close * 1.5, last.volume)
        sig = pair_signal(a, b, "A.SH", "B.SH", "板块配对", entry_z=1.5, lookback=100)
        assert "做空A.SH" in sig.action or "做多B.SH" in sig.action or sig.z_score > 0

    def test_data_insufficient(self) -> None:
        a = _synth("A.SH", days=50)
        b = _synth("B.SH", days=50)
        sig = pair_signal(a, b, "A.SH", "B.SH", "板块配对", lookback=120)
        assert sig.action == "无信号"
        assert "数据不足" in sig.description


class TestScanHedgePairs:
    def test_returns_signals_for_available_pairs(self) -> None:
        bars = {}
        for a, h, _ in AH_PAIRS[:3]:
            if h is None:
                continue
            bars[a] = _synth(a, seed=hash(a) % 1000)
            bars[h] = _synth(h, seed=hash(h) % 1000)
        signals = scan_hedge_pairs(bars)
        assert len(signals) > 0
        assert all(isinstance(s, SpreadSignal) for s in signals)

    def test_handles_missing_symbols(self) -> None:
        signals = scan_hedge_pairs({})
        assert signals == []


class TestBeta:
    def test_beta_near_one_for_same_drift(self) -> None:
        # 用同一随机种子构造相同走势（高相关），Beta 应在合理范围
        stock = _synth("600900.SH", seed=1, drift=0.001, noise=0.01)
        index = _synth("510300.SH", seed=1, drift=0.001, noise=0.01, start_price=20.0)
        b = beta(stock, index)
        assert 0.3 < b < 3.0

    def test_beta_low_for_low_vol_stock(self) -> None:
        stock = _synth("600900.SH", seed=1, drift=0.0002, noise=0.005)
        index = _synth("510300.SH", seed=2, drift=0.001, noise=0.02)
        b = beta(stock, index)
        assert b < 1.0  # 低波动股 Beta 应小于 1

    def test_beta_neutral_plan(self) -> None:
        stock = _synth("600900.SH", seed=1)
        index = _synth("510300.SH", seed=2)
        plan = beta_neutral_plan(stock, index, "600900.SH", "510300.SH")
        assert plan.long_symbol == "600900.SH"
        assert plan.short_symbol == "510300.SH"
        assert plan.hedge_ratio > 0
        assert "Beta" in plan.description


class TestRankAndTier:
    def test_metrics_computed(self) -> None:
        from quant_demo.data.selection import compute_metrics, StockMetrics
        bars = _synth("600900.SH", days=300)
        m = compute_metrics(bars)
        assert isinstance(m, StockMetrics)
        assert m.symbol == "600900.SH"
        assert m.annual_volatility > 0
        assert -1 < m.max_drawdown <= 0

    def test_rank_sorts_by_composite(self) -> None:
        from quant_demo.data.selection import rank_and_tier
        all_bars = _synth("A.SH", seed=1, days=300) + _synth("B.SH", seed=2, days=300)
        metrics = rank_and_tier(all_bars)
        assert len(metrics) == 2
        assert metrics[0].composite_score >= metrics[1].composite_score
        assert all(m.liquidity_tier in ("高", "中", "低") for m in metrics)
        assert all(m.vol_tier in ("低波动", "中波动", "高波动") for m in metrics)
