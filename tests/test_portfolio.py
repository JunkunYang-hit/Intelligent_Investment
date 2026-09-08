"""验证 D 模块最关键的买入、估值、卖出和异常记账。"""

from datetime import datetime

import pytest

from quant_demo.models import Side, Trade
from quant_demo.trading.portfolio import Account


NOW = datetime(2025, 1, 2)


def trade(side: Side, quantity: int, price: float, fee: float) -> Trade:
    return Trade("T1", "O1", "510300.SH", side, quantity, price, NOW, fee)


def test_buy_mark_and_sell_updates_account_and_pnl() -> None:
    account = Account(100_000)
    account.apply_trade(trade(Side.BUY, 1_000, 10.0, 5.0))
    position = account.get_position("510300.SH")
    assert account.cash == pytest.approx(89_995)
    assert position.average_cost == pytest.approx(10.005)

    account.mark_to_market({"510300.SH": 11.0}, NOW)
    assert account.total_equity == pytest.approx(100_995)
    assert account.unrealized_pnl == pytest.approx(995)

    account.apply_trade(trade(Side.SELL, 1_000, 11.0, 8.0))
    assert account.cash == pytest.approx(100_987)
    assert position.quantity == 0
    assert position.realized_pnl == pytest.approx(987)


def test_reject_oversell() -> None:
    account = Account(100_000)
    with pytest.raises(ValueError, match="持仓不足"):
        account.apply_trade(trade(Side.SELL, 100, 10.0, 5.0))
