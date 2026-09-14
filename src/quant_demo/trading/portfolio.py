"""D（账户与持仓模块）：唯一有权改变现金和持仓的账本。"""

from __future__ import annotations

from datetime import datetime

from quant_demo.models import EquityPoint, Position, Side, Trade


class Account:
    """维护现金、持仓、成交和净值的内存账户。

    回测引擎只能通过 ``apply_trade`` 改变现金和持仓，避免同一笔成交在
    多个模块中被重复扣款或加仓。
    """

    def __init__(self, initial_cash: float) -> None:
        if initial_cash <= 0:
            raise ValueError("初始资金必须大于 0")
        self.initial_cash = float(initial_cash)
        self.cash = float(initial_cash)
        self.positions: dict[str, Position] = {}
        self.trades: list[Trade] = []
        self.equity_curve: list[EquityPoint] = []
        # trade_id 用于防止撮合或重试时把同一笔成交重复记账。
        self._processed_trades: dict[str, Trade] = {}

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

    @property
    def total_pnl(self) -> float:
        """账户累计盈亏；在没有出入金时等于总资产减初始资金。"""
        return self.realized_pnl + self.unrealized_pnl

    @property
    def total_fees(self) -> float:
        return sum(trade.total_fee for trade in self.trades)

    def get_position(self, symbol: str) -> Position:
        return self.positions.setdefault(symbol, Position(symbol=symbol))

    def apply_trade(self, trade: Trade) -> bool:
        """过账一笔完整成交。

        首次过账返回 ``True``；完全相同的成交被重复传入时返回 ``False``，
        不会再次改账。同一 trade_id 对应不同内容通常意味着上游数据错误。
        """
        processed = self._processed_trades.get(trade.trade_id)
        if processed is not None:
            if processed == trade:
                return False
            raise ValueError(f"成交编号 {trade.trade_id} 对应了不同成交内容")
        if trade.side is Side.BUY:
            required_cash = trade.gross_amount + trade.total_fee
            if required_cash > self.cash + 1e-8:
                raise ValueError("账户现金不足，无法过账")
            position = self.positions.get(trade.symbol)
            if position is None:
                position = Position(symbol=trade.symbol)
                self.positions[trade.symbol] = position
            old_cost = position.quantity * position.average_cost
            position.quantity += trade.quantity
            # 手续费计入持仓成本，卖出税费则直接影响现金和已实现盈亏。
            position.average_cost = (old_cost + trade.gross_amount + trade.total_fee) / position.quantity
            self.cash -= required_cash
        else:
            position = self.positions.get(trade.symbol)
            if position is None or trade.quantity > position.quantity:
                raise ValueError("可用持仓不足，无法过账")
            pnl = (trade.price - position.average_cost) * trade.quantity - trade.total_fee
            position.realized_pnl += pnl
            position.quantity -= trade.quantity
            self.cash += trade.gross_amount - trade.total_fee
            if position.quantity == 0:
                position.average_cost = 0.0
        position.last_price = trade.price
        self.trades.append(trade)
        self._processed_trades[trade.trade_id] = trade
        return True

    def mark_to_market(self, prices: dict[str, float], at: datetime) -> EquityPoint:
        """用最新价格估值，并为该时刻保存一个账户净值点。"""
        if self.equity_curve and at < self.equity_curve[-1].datetime:
            raise ValueError("账户估值时间不能倒退")
        if any(price <= 0 for price in prices.values()):
            raise ValueError("估值价格必须大于 0")
        for symbol, price in prices.items():
            if symbol in self.positions:
                self.positions[symbol].last_price = price
        point = EquityPoint(
            datetime=at,
            cash=self.cash,
            market_value=self.market_value,
            total_equity=self.total_equity,
        )
        # 多标的行情可能在同一时刻分批到达，同一时间只保留最终组合净值。
        if self.equity_curve and self.equity_curve[-1].datetime == at:
            self.equity_curve[-1] = point
        else:
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
            "total_pnl": self.total_pnl,
            "total_fees": self.total_fees,
            "positions": [
                {
                    "symbol": p.symbol,
                    "quantity": p.quantity,
                    "average_cost": p.average_cost,
                    "cost_value": p.cost_value,
                    "last_price": p.last_price,
                    "market_value": p.market_value,
                    "realized_pnl": p.realized_pnl,
                    "unrealized_pnl": p.unrealized_pnl,
                    "total_pnl": p.total_pnl,
                }
                for p in self.positions.values()
                if p.quantity > 0
            ],
        }
