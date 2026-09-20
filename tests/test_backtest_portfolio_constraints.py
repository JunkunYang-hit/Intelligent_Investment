"""验证 C 模块可选的多标的组合约束。"""

from __future__ import annotations

from datetime import datetime, timedelta

from quant_demo.models import Bar, Side
from quant_demo.modes import BacktestEngine, build_backtest_engine
from quant_demo.strategy.base import Strategy
from quant_demo.trading import (
    Account,
    BrokerSimulator,
    OrderManagementSystem,
    RiskManager,
    TargetWeightSizer,
)


class BuyOnFirstBar(Strategy):
    def on_bar(self, bar, history):
        return Side.BUY if len(history[bar.symbol]) == 1 else None


def _bars() -> list[Bar]:
    start = datetime(2025, 1, 1)
    result = []
    for offset in range(2):
        for symbol in ("A", "B"):
            price = 10.0
            result.append(Bar(symbol, start + timedelta(days=offset), price, price, price, price, 1000))
    return list(reversed(result))


def _engine(**options: object) -> BacktestEngine:
    return BacktestEngine(
        strategy=BuyOnFirstBar(),
        account=Account(1_000),
        sizer=TargetWeightSizer(0.6, 1),
        risk=RiskManager(1.0, 1.0, 1),
        oms=OrderManagementSystem(),
        broker=BrokerSimulator(
            commission_rate=0,
            minimum_commission=0,
            sell_stamp_duty_rate=0,
            slippage_bps=0,
        ),
        **options,
    )


def test_cash_reservation_rejects_later_order_before_execution() -> None:
    result = _engine(reserve_cash=True).run(_bars())

    assert [order.symbol for order in result.orders] == ["A", "B"]
    assert result.orders[0].status.value == "FILLED"
    assert result.orders[1].status.value == "REJECTED"
    assert result.orders[1].reject_reason == "待成交订单预占后可用现金不足"
    assert len(result.trades) == 1


def test_max_total_weight_rejects_excess_portfolio_exposure() -> None:
    result = _engine(max_total_weight=0.8).run(_bars())

    assert result.orders[0].status.value == "FILLED"
    assert result.orders[1].status.value == "REJECTED"
    assert result.orders[1].reject_reason == "组合总仓位超过限制"
    assert len(result.trades) == 1


def test_default_constraints_preserve_legacy_multi_symbol_result() -> None:
    result = _engine().run(_bars())

    assert [order.symbol for order in result.orders] == ["A", "B"]
    assert [order.status.value for order in result.orders] == ["FILLED", "REJECTED"]
    assert result.orders[1].reject_reason == "账户现金不足，无法过账"


def test_factory_reads_constraints_without_changing_default_configuration() -> None:
    config = {
        "market": {"lot_size": 1},
        "backtest": {
            "initial_cash": 1_000,
            "commission_rate": 0,
            "minimum_commission": 0,
            "sell_stamp_duty_rate": 0,
            "slippage_bps": 0,
            "annual_trading_days": 252,
            "reserve_cash": True,
        },
        "strategy": {"name": "dual_moving_average", "target_weight": 0.6},
        "risk": {"max_order_value_ratio": 1.0, "max_symbol_weight": 1.0, "max_total_weight": 0.8},
    }
    engine = build_backtest_engine(config)

    assert engine.reserve_cash is True
    assert engine.max_total_weight == 0.8
