"""C（回测模块）：时间推进和模块编排，不直接修改账户内部状态。"""

from __future__ import annotations

from collections import defaultdict
from itertools import groupby

from quant_demo.analytics import calculate_performance
from quant_demo.models import BacktestResult, Bar, Order
from quant_demo.strategy import Strategy
from quant_demo.trading import (
    Account,
    BrokerSimulator,
    OrderManagementSystem,
    RiskManager,
    TargetWeightSizer,
)


class BacktestEngine:
    def __init__(
        self,
        strategy: Strategy,
        account: Account,
        sizer: TargetWeightSizer,
        risk: RiskManager,
        oms: OrderManagementSystem,
        broker: BrokerSimulator,
        annual_trading_days: int = 252,
    ) -> None:
        self.strategy = strategy
        self.account = account
        self.sizer = sizer
        self.risk = risk
        self.oms = oms
        self.broker = broker
        self.annual_trading_days = annual_trading_days

    def run(self, bars: list[Bar]) -> BacktestResult:
        history: dict[str, list[Bar]] = defaultdict(list)
        pending: dict[str, list[Order]] = defaultdict(list)
        last_prices: dict[str, float] = {}

        ordered_bars = sorted(bars, key=lambda item: (item.datetime, item.symbol))
        for at, day_group in groupby(ordered_bars, key=lambda item: item.datetime):
            day_bars = list(day_group)
            # 先执行上一交易日产生的订单，杜绝当日收盘信号按当日成交。
            for bar in day_bars:
                for order in pending.pop(bar.symbol, []):
                    trade = self.broker.execute_at_open(order, bar)
                    try:
                        self.account.apply_trade(trade)
                    except ValueError as exc:
                        self.oms.reject(order, str(exc))
                    else:
                        self.oms.fill(order, trade.price)

            # 所有标的收盘价齐备后每天只记录一个组合净值点。
            for bar in day_bars:
                history[bar.symbol].append(bar)
                last_prices[bar.symbol] = bar.close
            self.account.mark_to_market(last_prices, at)

            for bar in day_bars:
                signal = self.strategy.on_bar(bar, history)
                if signal is None:
                    continue
                request = self.sizer.create_request(
                    bar.symbol,
                    signal,
                    bar.close,
                    self.account,
                    bar.datetime,
                    reason=f"{type(self.strategy).__name__} {signal.value}",
                )
                if request is None:
                    continue
                order = self.oms.create(request)
                decision = self.risk.check(request, bar.close, self.account)
                if not decision.passed:
                    self.oms.reject(order, decision.reason)
                else:
                    pending[bar.symbol].append(order)

        metrics = calculate_performance(
            self.account.equity_curve, self.account.trades, self.annual_trading_days
        )
        return BacktestResult(
            metrics=metrics,
            equity_curve=list(self.account.equity_curve),
            trades=list(self.account.trades),
            orders=list(self.oms.orders),
            metadata={"execution_rule": "signal close -> next bar open"},
        )
