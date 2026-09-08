"""回测和持续模拟两种运行方式。"""

from .backtest import BacktestEngine
from .simulation import SimulationEngine

__all__ = ["BacktestEngine", "SimulationEngine"]
