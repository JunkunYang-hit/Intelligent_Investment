"""团队共享的数据格式。

任何模块之间只交换本文件中的对象，避免五个人各自定义同名结构。
金额和价格在 Demo 中用 float；若连接真实券商，应改用 Decimal 或券商整数单位。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    CREATED = "CREATED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class Bar:
    symbol: str
    datetime: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self) -> None:
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("OHLC 价格必须大于 0")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("OHLC 价格关系不合法")
        if self.volume < 0:
            raise ValueError("成交量不能为负")


@dataclass(frozen=True)
class OrderRequest:
    symbol: str
    side: Side
    quantity: int
    created_at: datetime
    reason: str = ""


@dataclass
class Order:
    order_id: str
    symbol: str
    side: Side
    quantity: int
    created_at: datetime
    status: OrderStatus = OrderStatus.CREATED
    price: float | None = None
    reject_reason: str | None = None


@dataclass(frozen=True)
class Trade:
    trade_id: str
    order_id: str
    symbol: str
    side: Side
    quantity: int
    price: float
    datetime: datetime
    commission: float
    stamp_duty: float = 0.0

    @property
    def gross_amount(self) -> float:
        return self.quantity * self.price

    @property
    def total_fee(self) -> float:
        return self.commission + self.stamp_duty


@dataclass
class Position:
    symbol: str
    quantity: int = 0
    average_cost: float = 0.0
    last_price: float = 0.0
    realized_pnl: float = 0.0

    @property
    def market_value(self) -> float:
        return self.quantity * self.last_price

    @property
    def unrealized_pnl(self) -> float:
        return self.quantity * (self.last_price - self.average_cost)


@dataclass(frozen=True)
class EquityPoint:
    datetime: datetime
    cash: float
    market_value: float
    total_equity: float


@dataclass(frozen=True)
class BacktestResult:
    metrics: dict[str, float | int]
    equity_curve: list[EquityPoint]
    trades: list[Trade]
    orders: list[Order]
    metadata: dict[str, Any] = field(default_factory=dict)
