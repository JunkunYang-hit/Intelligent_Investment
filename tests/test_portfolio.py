"""验证 D 模块最关键的买入、估值、卖出和异常记账。"""

from datetime import datetime, timedelta

import pytest

from quant_demo.models import Side, Trade
from quant_demo.trading.portfolio import Account


NOW = datetime(2025, 1, 2)


def trade(
    side: Side,
    quantity: int,
    price: float,
    fee: float,
    trade_id: str = "T1",
    symbol: str = "510300.SH",
) -> Trade:
    return Trade(trade_id, f"O-{trade_id}", symbol, side, quantity, price, NOW, fee)


def test_buy_mark_and_sell_updates_account_and_pnl() -> None:
    account = Account(100_000)
    account.apply_trade(trade(Side.BUY, 1_000, 10.0, 5.0))
    position = account.get_position("510300.SH")
    assert account.cash == pytest.approx(89_995)
    assert position.average_cost == pytest.approx(10.005)

    account.mark_to_market({"510300.SH": 11.0}, NOW)
    assert account.total_equity == pytest.approx(100_995)
    assert account.unrealized_pnl == pytest.approx(995)

    account.apply_trade(trade(Side.SELL, 1_000, 11.0, 8.0, "T2"))
    assert account.cash == pytest.approx(100_987)
    assert position.quantity == 0
    assert position.realized_pnl == pytest.approx(987)


def test_reject_oversell() -> None:
    account = Account(100_000)
    with pytest.raises(ValueError, match="持仓不足"):
        account.apply_trade(trade(Side.SELL, 100, 10.0, 5.0))
    assert account.positions == {}


def test_multiple_buys_and_partial_sell_keep_correct_average_cost() -> None:
    account = Account(100_000)
    account.apply_trade(trade(Side.BUY, 1_000, 10.0, 5.0, "T1"))
    account.apply_trade(trade(Side.BUY, 1_000, 12.0, 5.0, "T2"))
    position = account.get_position("510300.SH")
    assert position.quantity == 2_000
    assert position.average_cost == pytest.approx(11.005)

    account.apply_trade(trade(Side.SELL, 500, 13.0, 5.0, "T3"))
    assert position.quantity == 1_500
    assert position.average_cost == pytest.approx(11.005)
    assert position.realized_pnl == pytest.approx(992.5)


def test_same_trade_is_only_booked_once() -> None:
    account = Account(100_000)
    item = trade(Side.BUY, 1_000, 10.0, 5.0)
    assert account.apply_trade(item) is True
    assert account.apply_trade(item) is False
    assert account.cash == pytest.approx(89_995)
    assert account.get_position("510300.SH").quantity == 1_000
    assert len(account.trades) == 1


def test_conflicting_trade_with_same_id_is_rejected() -> None:
    account = Account(100_000)
    account.apply_trade(trade(Side.BUY, 100, 10.0, 5.0, "SAME"))
    with pytest.raises(ValueError, match="对应了不同成交内容"):
        account.apply_trade(trade(Side.BUY, 200, 10.0, 5.0, "SAME"))


def test_multiple_symbols_and_snapshot_are_reconciled() -> None:
    account = Account(100_000)
    account.apply_trade(trade(Side.BUY, 1_000, 10.0, 5.0, "T1"))
    account.apply_trade(trade(Side.BUY, 500, 20.0, 5.0, "T2", "600000.SH"))
    account.mark_to_market({"510300.SH": 11.0, "600000.SH": 19.0}, NOW)
    snapshot = account.snapshot()
    assert account.market_value == pytest.approx(20_500)
    assert account.total_pnl == pytest.approx(account.total_equity - account.initial_cash)
    assert snapshot["total_fees"] == pytest.approx(10.0)
    assert len(snapshot["positions"]) == 2


def test_same_time_valuation_is_replaced_and_time_cannot_go_back() -> None:
    account = Account(100_000)
    account.mark_to_market({}, NOW)
    account.mark_to_market({}, NOW)
    assert len(account.equity_curve) == 1
    with pytest.raises(ValueError, match="时间不能倒退"):
        account.mark_to_market({}, NOW - timedelta(days=1))


def test_invalid_trade_fee_is_rejected() -> None:
    with pytest.raises(ValueError, match="不能为负"):
        trade(Side.BUY, 100, 10.0, -1.0)


def test_failed_valuation_does_not_partially_update_prices() -> None:
    account = Account(100_000)
    account.apply_trade(trade(Side.BUY, 100, 10.0, 5.0, "T1"))
    account.apply_trade(trade(Side.BUY, 100, 20.0, 5.0, "T2", "600000.SH"))
    with pytest.raises(ValueError, match="估值价格必须大于 0"):
        account.mark_to_market({"510300.SH": 11.0, "600000.SH": -1.0}, NOW)
    assert account.get_position("510300.SH").last_price == pytest.approx(10.0)
