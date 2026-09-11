"""C（回测模块）：时间推进和模块编排，不直接修改账户内部状态。"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from itertools import groupby

from quant_demo.analytics import calculate_performance
from quant_demo.models import BacktestResult, Bar, Order, OrderStatus
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
        self._has_run = False

    def run(self, bars: list[Bar]) -> BacktestResult:
        if self._has_run:
            raise RuntimeError("BacktestEngine 只能运行一次；请为新的回测任务创建新的 Engine")
        self._validate_bars(bars)
        self._has_run = True

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
            metadata=self._build_metadata(ordered_bars),
        )

    @staticmethod
    def _validate_bars(bars: list[Bar]) -> None:
        if not bars:
            raise ValueError("回测行情不能为空")

        seen: set[tuple[datetime, str]] = set()
        day_timestamps: dict[object, datetime] = {}
        timezone_awareness: bool | None = None
        for bar in bars:
            if not isinstance(bar.datetime, datetime):
                raise ValueError("Bar datetime 必须是 datetime")
            if not bar.symbol:
                raise ValueError("Bar symbol 不能为空")
            aware = bar.datetime.tzinfo is not None
            if timezone_awareness is None:
                timezone_awareness = aware
            elif aware != timezone_awareness:
                raise ValueError("Bar datetime 不能混用带时区和不带时区的时间")

            key = (bar.datetime, bar.symbol)
            if key in seen:
                raise ValueError(f"存在重复 Bar: {bar.datetime.isoformat()} {bar.symbol}")
            seen.add(key)

            day = bar.datetime.date()
            previous = day_timestamps.get(day)
            if previous is not None and previous != bar.datetime:
                raise ValueError(f"同一交易日的 Bar 时间戳不一致: {day}")
            day_timestamps[day] = bar.datetime

    def _build_metadata(self, ordered_bars: list[Bar]) -> dict[str, object]:
        symbols = sorted({bar.symbol for bar in ordered_bars})
        statuses = [order.status for order in self.oms.orders]
        return {
            "execution_rule": "signal close -> next bar open",
            "bar_count": len(ordered_bars),
            "symbol_count": len(symbols),
            "symbols": symbols,
            "start": ordered_bars[0].datetime.isoformat(),
            "end": ordered_bars[-1].datetime.isoformat(),
            "initial_cash": self.account.initial_cash,
            "annual_trading_days": self.annual_trading_days,
            "strategy": type(self.strategy).__name__,
            "order_count": len(self.oms.orders),
            "filled_order_count": statuses.count(OrderStatus.FILLED),
            "rejected_order_count": statuses.count(OrderStatus.REJECTED),
            "created_order_count": statuses.count(OrderStatus.CREATED),
        }
