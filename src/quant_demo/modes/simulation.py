"""持续模拟模式：外部每推送一根完成的日 K，就调用一次 on_bar。"""

from __future__ import annotations

from collections import defaultdict

from quant_demo.models import Bar, Order
from quant_demo.strategy import Strategy
from quant_demo.trading import Account, BrokerSimulator, OrderManagementSystem, RiskManager, TargetWeightSizer


class SimulationEngine:
    def __init__(
        self,
        strategy: Strategy,
        account: Account,
        sizer: TargetWeightSizer,
        risk: RiskManager,
        oms: OrderManagementSystem,
        broker: BrokerSimulator,
    ) -> None:
        self.strategy = strategy
        self.account = account
        self.sizer = sizer
        self.risk = risk
        self.oms = oms
        self.broker = broker
        self.history: dict[str, list[Bar]] = defaultdict(list)
        self.pending: dict[str, list[Order]] = defaultdict(list)
        self.last_prices: dict[str, float] = {}

    def on_bar(self, bar: Bar) -> dict[str, object]:
        """处理一根已完成 Bar，并返回适合 Web 序列化的账户快照。"""
        previous = self.history[bar.symbol][-1] if self.history[bar.symbol] else None
        if previous and bar.datetime <= previous.datetime:
            raise ValueError("模拟行情必须按时间严格递增")
        for order in self.pending.pop(bar.symbol, []):
            trade = self.broker.execute_at_open(order, bar)
            try:
                self.account.apply_trade(trade)
            except ValueError as exc:
                self.oms.reject(order, str(exc))
            else:
                self.oms.fill(order, trade.price)

        self.history[bar.symbol].append(bar)
        self.last_prices[bar.symbol] = bar.close
        self.account.mark_to_market(self.last_prices, bar.datetime)
        signal = self.strategy.on_bar(bar, self.history)
        if signal is not None:
            request = self.sizer.create_request(
                bar.symbol, signal, bar.close, self.account, bar.datetime, f"simulation {signal.value}"
            )
            if request:
                order = self.oms.create(request)
                decision = self.risk.check(request, bar.close, self.account)
                if decision.passed:
                    self.pending[bar.symbol].append(order)
                else:
                    self.oms.reject(order, decision.reason)
        return self.account.snapshot()

