"""事前风险检查：校验手数、资金、单笔金额和单标的仓位。"""

from __future__ import annotations

from dataclasses import dataclass

from quant_demo.models import OrderRequest, Side
from quant_demo.trading.portfolio import Account


@dataclass(frozen=True)
class RiskDecision:
    passed: bool
    reason: str = "PASS"


class RiskManager:
    def __init__(
        self,
        max_order_value_ratio: float = 0.25,
        max_symbol_weight: float = 0.3,
        lot_size: int = 100,
    ) -> None:
        self.max_order_value_ratio = max_order_value_ratio
        self.max_symbol_weight = max_symbol_weight
        self.lot_size = lot_size

    def check(self, request: OrderRequest, estimated_price: float, account: Account) -> RiskDecision:
        if request.quantity <= 0 or request.quantity % self.lot_size:
            return RiskDecision(False, f"数量必须是 {self.lot_size} 的正整数倍")
        value = request.quantity * estimated_price
        position = account.get_position(request.symbol)
        if request.side is Side.BUY:
            if value > account.total_equity * self.max_order_value_ratio + 1e-8:
                return RiskDecision(False, "单笔金额超过账户比例限制")
            if position.market_value + value > account.total_equity * self.max_symbol_weight + 1e-8:
                return RiskDecision(False, "单标的仓位超过限制")
            if value > account.cash:
                return RiskDecision(False, "可用现金不足")
        elif request.quantity > position.quantity:
            return RiskDecision(False, "可用持仓不足")
        return RiskDecision(True)
