"""策略模块对外公开的基类和示例策略。"""

from .base import Strategy
from .moving_average import DualMovingAverageStrategy

__all__ = ["Strategy", "DualMovingAverageStrategy"]
