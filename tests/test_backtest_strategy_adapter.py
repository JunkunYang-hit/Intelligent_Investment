"""验证 C 模块对内置策略配置的低侵入适配。"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from quant_demo.models import Bar
from quant_demo.modes import build_backtest_engine, build_strategy
from quant_demo.strategy import (
    BollingerBandsStrategy,
    DualMovingAverageStrategy,
    MACDStrategy,
    RSIStrategy,
)


@pytest.mark.parametrize(
    ("name", "expected_type", "expected_parameters"),
    [
        (
            "dual_moving_average",
            DualMovingAverageStrategy,
            {"short_window": 5, "long_window": 20},
        ),
        (
            "rsi",
            RSIStrategy,
            {"period": 14, "oversold": 30.0, "overbought": 70.0},
        ),
        (
            "macd",
            MACDStrategy,
            {"fast_period": 12, "slow_period": 26, "signal_period": 9},
        ),
        (
            "bollinger_bands",
            BollingerBandsStrategy,
            {"period": 20, "std_multiplier": 2.0},
        ),
    ],
)
def test_build_strategy_supports_all_builtin_strategies(
    name: str,
    expected_type: type,
    expected_parameters: dict[str, int | float],
) -> None:
    selection = build_strategy({"name": name, "target_weight": 0.2})

    assert isinstance(selection.strategy, expected_type)
    assert selection.name == name
    assert selection.parameters == expected_parameters


def test_build_strategy_rejects_unknown_name_and_parameter() -> None:
    with pytest.raises(ValueError, match="不支持的策略"):
        build_strategy({"name": "unknown", "target_weight": 0.2})

    with pytest.raises(ValueError, match="未知字段"):
        build_strategy({"name": "rsi", "target_weight": 0.2, "peroid": 14})


def test_configured_engine_records_resolved_strategy_and_preserves_execution_rule() -> None:
    config = _config(
        {
            "name": "dual_moving_average",
            "short_window": 2,
            "long_window": 3,
            "target_weight": 0.2,
        }
    )
    engine = build_backtest_engine(config)
    bars = _bars([3, 2, 1, 2, 3, 4])

    result = engine.run(bars)

    assert len(result.trades) == 1
    assert result.trades[0].datetime == bars[-1].datetime
    assert result.metadata["execution_rule"] == "signal close -> next bar open"
    assert result.metadata["strategy"] == "DualMovingAverageStrategy"
    assert result.metadata["strategy_name"] == "dual_moving_average"
    assert result.metadata["strategy_parameters"] == {
        "short_window": 2,
        "long_window": 3,
    }


def test_factory_creates_isolated_engines() -> None:
    config = _config({"name": "rsi", "period": 3, "target_weight": 0.2})

    first = build_backtest_engine(config)
    second = build_backtest_engine(config)

    assert first is not second
    assert first.strategy is not second.strategy
    assert first.account is not second.account
    assert first.oms is not second.oms
    assert first.broker is not second.broker


def _config(strategy: dict[str, object]) -> dict[str, object]:
    return {
        "market": {"lot_size": 100},
        "backtest": {
            "initial_cash": 100_000,
            "commission_rate": 0.0003,
            "minimum_commission": 5,
            "sell_stamp_duty_rate": 0.0005,
            "slippage_bps": 0,
            "annual_trading_days": 252,
        },
        "strategy": strategy,
        "risk": {
            "max_order_value_ratio": 0.3,
            "max_symbol_weight": 0.3,
        },
    }


def _bars(prices: list[float]) -> list[Bar]:
    start = datetime(2025, 1, 1)
    return [
        Bar(
            "510300.SH",
            start + timedelta(days=index),
            price,
            price,
            price,
            price,
            1000,
        )
        for index, price in enumerate(prices)
    ]
