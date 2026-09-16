"""内置策略的轻量注册表：按名字统一查询和构造策略。

这是策略模块内部的便捷入口，不改变 C 模块 ``modes/factory.py`` 的配置
白名单；它为未来"按市场状态选择不同策略"提供统一的名字 -> 策略类映射，
避免上层硬编码 import 每一个策略类。
"""

from __future__ import annotations

from quant_demo.strategy.atr_trend import ATRTrendStrategy
from quant_demo.strategy.base import Strategy
from quant_demo.strategy.bollinger import BollingerBandsStrategy
from quant_demo.strategy.composite import CompositeStrategy
from quant_demo.strategy.donchian import DonchianBreakoutStrategy
from quant_demo.strategy.macd import MACDStrategy
from quant_demo.strategy.mean_reversion import ZScoreMeanReversionStrategy
from quant_demo.strategy.momentum import MomentumStrategy
from quant_demo.strategy.moving_average import DualMovingAverageStrategy
from quant_demo.strategy.rsi import RSIStrategy
from quant_demo.strategy.stochastic import StochasticStrategy

STRATEGY_REGISTRY: dict[str, type[Strategy]] = {
    "dual_ma": DualMovingAverageStrategy,
    "rsi": RSIStrategy,
    "macd": MACDStrategy,
    "bollinger": BollingerBandsStrategy,
    "momentum": MomentumStrategy,
    "donchian": DonchianBreakoutStrategy,
    "stochastic": StochasticStrategy,
    "atr_trend": ATRTrendStrategy,
    "zscore_mean_reversion": ZScoreMeanReversionStrategy,
    "composite": CompositeStrategy,
}


def available_strategies() -> tuple[str, ...]:
    """返回全部已注册策略的名字（按字母序）。"""
    return tuple(sorted(STRATEGY_REGISTRY))


def create_strategy(name: str, **parameters: object) -> Strategy:
    """按注册名构造策略实例，未知名字抛 ``ValueError``。

    ``parameters`` 原样传给策略构造函数，非法参数由策略自身校验。
    """
    if not isinstance(name, str):
        raise ValueError("strategy name must be a string")
    key = name.strip().lower()
    strategy_class = STRATEGY_REGISTRY.get(key)
    if strategy_class is None:
        raise ValueError(f"未注册的策略 {name!r}；可选值: {', '.join(available_strategies())}")
    return strategy_class(**parameters)  # type: ignore[arg-type]
