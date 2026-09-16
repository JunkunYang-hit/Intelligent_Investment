"""策略模块对外公开的基类、技术指标和内置策略。"""

from .atr_trend import ATRTrendStrategy
from .base import Strategy
from .bollinger import BollingerBandsStrategy
from .composite import CompositeStrategy, CompositeScore
from .donchian import DonchianBreakoutStrategy
from .macd import MACDStrategy
from .mean_reversion import ZScoreMeanReversionStrategy
from .momentum import MomentumStrategy
from .moving_average import DualMovingAverageStrategy
from .registry import STRATEGY_REGISTRY, available_strategies, create_strategy
from .rsi import RSIStrategy
from .stochastic import StochasticStrategy

__all__ = [
    "Strategy",
    "DualMovingAverageStrategy",
    "RSIStrategy",
    "MACDStrategy",
    "BollingerBandsStrategy",
    "MomentumStrategy",
    "DonchianBreakoutStrategy",
    "StochasticStrategy",
    "ATRTrendStrategy",
    "ZScoreMeanReversionStrategy",
    "CompositeStrategy",
    "CompositeScore",
    "STRATEGY_REGISTRY",
    "available_strategies",
    "create_strategy",
]
