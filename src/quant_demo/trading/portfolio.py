"""D（账户与持仓模块）：唯一有权改变现金和持仓的账本。"""

from __future__ import annotations

from datetime import datetime

from quant_demo.models import EquityPoint, Position, Side, Trade


class Account:
    def __init__(self, initial_cash: float) -> None:
        if initial_cash <= 0:
            raise ValueError("初始资金必须大于 0")
        self.initial_cash = float(initial_cash)
        self.cash = float(initial_cash)
        self.positions: dict[str, Position] = {}
        self.trades: list[Trade] = []
        self.equity_curve: list[EquityPoint] = []

    @property
    def market_value(self) -> float:
        return sum(position.market_value for position in self.positions.values())

    @property
    def total_equity(self) -> float:
        return self.cash + self.market_value

    @property
    def realized_pnl(self) -> float:
        return sum(position.realized_pnl for position in self.positions.values())

    @property
    def unrealized_pnl(self) -> float:
        return sum(position.unrealized_pnl for position in self.positions.values())

    def get_position(self, symbol: str) -> Position:
        return self.positions.setdefault(symbol, Position(symbol=symbol))

    def apply_trade(self, trade: Trade) -> None:
        """原子地过账一笔完整成交；调用前应先经过风控。"""
        if trade.quantity <= 0 or trade.price <= 0:
            raise ValueError("成交数量和价格必须大于 0")
        position = self.get_position(trade.symbol)
        if trade.side is Side.BUY:
            required_cash = trade.gross_amount + trade.total_fee
            if required_cash > self.cash + 1e-8:
                raise ValueError("账户现金不足，无法过账")
            old_cost = position.quantity * position.average_cost
            position.quantity += trade.quantity
            # 手续费计入持仓成本，卖出税费则直接影响现金和已实现盈亏。
            position.average_cost = (old_cost + trade.gross_amount + trade.total_fee) / position.quantity
            self.cash -= required_cash
        else:
            if trade.quantity > position.quantity:
                raise ValueError("可用持仓不足，无法过账")
            pnl = (trade.price - position.average_cost) * trade.quantity - trade.total_fee
            position.realized_pnl += pnl
            position.quantity -= trade.quantity
            self.cash += trade.gross_amount - trade.total_fee
            if position.quantity == 0:
                position.average_cost = 0.0
        position.last_price = trade.price
        self.trades.append(trade)

    def mark_to_market(self, prices: dict[str, float], at: datetime) -> EquityPoint:
        for symbol, price in prices.items():
            if price <= 0:
                raise ValueError("估值价格必须大于 0")
            if symbol in self.positions:
                self.positions[symbol].last_price = price
        point = EquityPoint(
            datetime=at,
            cash=self.cash,
            market_value=self.market_value,
            total_equity=self.total_equity,
        )
        self.equity_curve.append(point)
        return point

    def snapshot(self) -> dict[str, object]:
        return {
            "initial_cash": self.initial_cash,
            "cash": self.cash,
            "market_value": self.market_value,
            "total_equity": self.total_equity,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "positions": [
                {
                    "symbol": p.symbol,
                    "quantity": p.quantity,
                    "average_cost": p.average_cost,
                    "last_price": p.last_price,
                    "market_value": p.market_value,
                    "unrealized_pnl": p.unrealized_pnl,
                }
                for p in self.positions.values()
                if p.quantity > 0
            ],
        }

