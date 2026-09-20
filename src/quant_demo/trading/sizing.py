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
        # 只查询已有持仓，不因一次无效信号创建数量为 0 的 Position。
        position = account.positions.get(symbol)
        position_value = position.market_value if position else 0.0
        position_quantity = position.quantity if position else 0
        if side is Side.BUY:
            target_value = account.total_equity * self.target_weight
            missing_value = max(0.0, target_value - position_value)
            # 满仓目标仍需预留下一交易日跳空、滑点和手续费空间，否则按信号日
            # 收盘价算出的 100% 订单很容易在次日开盘因现金差几百元而整单拒绝。
            missing_value = min(missing_value, account.cash * 0.99)
            quantity = int(missing_value / price / self.lot_size) * self.lot_size
        else:
            quantity = position_quantity
        if quantity <= 0:
            return None
        return OrderRequest(symbol, side, quantity, at, reason)
