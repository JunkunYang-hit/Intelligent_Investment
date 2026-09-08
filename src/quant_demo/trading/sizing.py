"""仓位计算：把策略方向转换为符合 A 股手数的订单数量。"""

from __future__ import annotations

from datetime import datetime

from quant_demo.models import OrderRequest, Side
from quant_demo.trading.portfolio import Account


class TargetWeightSizer:
    def __init__(self, target_weight: float = 0.2, lot_size: int = 100) -> None:
        if not 0 < target_weight <= 1:
            raise ValueError("目标仓位必须在 (0, 1] 内")
        self.target_weight = target_weight
        self.lot_size = lot_size

    def create_request(
        self, symbol: str, side: Side, price: float, account: Account, at: datetime, reason: str
    ) -> OrderRequest | None:
        position = account.get_position(symbol)
        if side is Side.BUY:
            target_value = account.total_equity * self.target_weight
            missing_value = max(0.0, target_value - position.market_value)
            quantity = int(missing_value / price / self.lot_size) * self.lot_size
        else:
            quantity = position.quantity
        if quantity <= 0:
            return None
        return OrderRequest(symbol, side, quantity, at, reason)
