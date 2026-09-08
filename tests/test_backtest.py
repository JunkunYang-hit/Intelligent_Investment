"""验证信号在下一根 Bar 开盘成交，避免使用未来价格。"""

from datetime import datetime, timedelta

from quant_demo.models import Bar, Side
from quant_demo.modes import BacktestEngine
from quant_demo.strategy.base import Strategy
from quant_demo.trading import Account, BrokerSimulator, OrderManagementSystem, RiskManager, TargetWeightSizer


class BuyThenSell(Strategy):
    def on_bar(self, bar, history):
        size = len(history[bar.symbol])
        return Side.BUY if size == 1 else Side.SELL if size == 3 else None


def test_signal_is_filled_on_next_bar_open() -> None:
    start = datetime(2025, 1, 1)
    opens = [10.0, 11.0, 12.0, 13.0]
    bars = [Bar("510300.SH", start + timedelta(days=i), p, p, p, p, 1000) for i, p in enumerate(opens)]
    engine = BacktestEngine(
        BuyThenSell(),
        Account(100_000),
        TargetWeightSizer(0.2, 100),
        RiskManager(0.3, 0.3, 100),
        OrderManagementSystem(),
        BrokerSimulator(slippage_bps=0),
    )
    result = engine.run(bars)
    assert [item.price for item in result.trades] == [11.0, 13.0]
    assert result.trades[0].datetime == bars[1].datetime
    assert result.metrics["trade_count"] == 2
