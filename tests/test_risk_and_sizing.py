"""验证风控和仓位查询不会在账户中制造无意义的空持仓。"""

from datetime import datetime

from quant_demo.models import OrderRequest, Side
from quant_demo.trading import Account, RiskManager, TargetWeightSizer


def test_rejected_sell_does_not_create_empty_position() -> None:
    account = Account(100_000)
    request = OrderRequest("510300.SH", Side.SELL, 100, datetime(2025, 1, 1))
    decision = RiskManager().check(request, 10.0, account)
    assert decision.passed is False
    assert account.positions == {}


def test_sell_sizing_without_position_returns_none_without_creating_position() -> None:
    account = Account(100_000)
    request = TargetWeightSizer().create_request(
        "510300.SH", Side.SELL, 10.0, account, datetime(2025, 1, 1), "test"
    )
    assert request is None
    assert account.positions == {}
