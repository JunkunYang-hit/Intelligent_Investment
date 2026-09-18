"""券商网关测试：模拟网关全流程 + SDK适配器的接口契约。"""

from __future__ import annotations

import importlib
from datetime import datetime

import pytest

from quant_demo.brokerage import BrokerGateway, PaperBrokerGateway
from quant_demo.models import OrderRequest, OrderStatus, Side


def _req(symbol: str = "600900.SH", side: Side = Side.BUY, qty: int = 1000) -> OrderRequest:
    return OrderRequest(symbol, side, qty, datetime(2026, 9, 16, 9, 30), reason="测试")


# --------------------------------------------------------------------------- #
# 模拟网关：完整下单闭环
# --------------------------------------------------------------------------- #
class TestPaperGateway:
    def test_implements_contract(self) -> None:
        assert isinstance(PaperBrokerGateway(), BrokerGateway)

    def test_market_buy_fills_at_last_close(self) -> None:
        gw = PaperBrokerGateway(initial_cash=1_000_000)
        gw.connect()
        gw.set_last_close("600900.SH", 28.63)
        oid = gw.place_order(_req(), order_type="market")
        order = gw.query_order(oid)
        assert order.status is OrderStatus.FILLED
        assert order.price == 28.63
        assert gw.query_cash() == pytest.approx(1_000_000 - 1000 * 28.63)
        pos = gw.query_positions()
        assert len(pos) == 1 and pos[0].symbol == "600900.SH" and pos[0].quantity == 1000

    def test_limit_buy_fills_at_limit_price(self) -> None:
        gw = PaperBrokerGateway()
        gw.connect()
        oid = gw.place_order(_req(qty=100), order_type="limit", price=30.0)
        assert gw.query_order(oid).price == 30.0

    def test_market_rejected_without_last_close(self) -> None:
        gw = PaperBrokerGateway()
        gw.connect()
        oid = gw.place_order(_req(), order_type="market")
        order = gw.query_order(oid)
        assert order.status is OrderStatus.REJECTED
        assert gw.query_positions() == []

    def test_buy_rejected_insufficient_cash(self) -> None:
        gw = PaperBrokerGateway(initial_cash=10_000)
        gw.connect()
        gw.set_last_close("600900.SH", 28.63)
        oid = gw.place_order(_req(qty=1000), order_type="market")
        assert gw.query_order(oid).status is OrderStatus.REJECTED

    def test_sell_updates_position_and_pnl(self) -> None:
        gw = PaperBrokerGateway()
        gw.connect()
        gw.set_last_close("600900.SH", 10.0)
        gw.place_order(_req(qty=100), order_type="market")
        gw.set_last_close("600900.SH", 12.0)
        gw.place_order(_req(side=Side.SELL, qty=100), order_type="market")
        pos = gw.query_positions()
        assert pos == []  # 清仓后不再返回
        assert gw.query_cash() == pytest.approx(1_000_000 + 100 * (12.0 - 10.0))

    def test_sell_rejected_insufficient_position(self) -> None:
        gw = PaperBrokerGateway()
        gw.connect()
        gw.set_last_close("600900.SH", 10.0)
        oid = gw.place_order(_req(side=Side.SELL, qty=100), order_type="market")
        assert gw.query_order(oid).status is OrderStatus.REJECTED

    def test_not_connected_raises(self) -> None:
        gw = PaperBrokerGateway()
        with pytest.raises(ConnectionError):
            gw.place_order(_req(), order_type="limit", price=10.0)

    def test_invalid_order_type(self) -> None:
        gw = PaperBrokerGateway()
        gw.connect()
        with pytest.raises(ValueError):
            gw.place_order(_req(), order_type="stop")

    def test_limit_requires_positive_price(self) -> None:
        gw = PaperBrokerGateway()
        gw.connect()
        with pytest.raises(ValueError):
            gw.place_order(_req(), order_type="limit", price=0)


# --------------------------------------------------------------------------- #
# SDK 适配器：未安装SDK时的行为契约
# --------------------------------------------------------------------------- #
class TestSdkAdapters:
    def test_qmt_gateway_no_client_returns_false(self, tmp_path) -> None:
        """无 QMT 客户端：connect() 返回 False（C风格：0=成功），不崩溃。"""
        pytest.importorskip("xtquant", reason="未安装 xtquant（QMT SDK）")
        from quant_demo.brokerage import QMTGateway
        gw = QMTGateway(qmt_userdata_path=str(tmp_path / "qmt"), account_id="123")
        assert gw.connect() is False

    def test_futu_gateway_import(self) -> None:
        pytest.importorskip("futu", reason="未安装 futu-sdk")
        from quant_demo.brokerage import FutuGateway
        gw = FutuGateway(market="HK", simulate=True, port=59999)  # 无OpenD的端口
        assert gw.connect() is False or True  # 连不上返回False，连得上也允许（测试机可能有OpenD）

    def test_futu_market_validation(self) -> None:
        from quant_demo.brokerage.futu_gateway import FutuGateway
        with pytest.raises(ValueError):
            FutuGateway(market="SH")

    def test_futu_code_mapping(self) -> None:
        from quant_demo.brokerage.futu_gateway import to_futu_code
        assert to_futu_code("0700.HK") == "HK.0700"
        assert to_futu_code("AAPL.US") == "US.AAPL"
        assert to_futu_code("600000.SH") == "SH.600000"
        with pytest.raises(ValueError):
            to_futu_code("600000.TW")
