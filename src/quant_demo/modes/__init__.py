"""回测和持续模拟两种运行方式。"""

from .backtest import BacktestEngine
from .factory import StrategySelection, build_backtest_engine, build_strategy
from .simulation import SimulationEngine

__all__ = [
    "BacktestEngine",
    "SimulationEngine",
    "StrategySelection",
    "build_backtest_engine",
    "build_strategy",
]
