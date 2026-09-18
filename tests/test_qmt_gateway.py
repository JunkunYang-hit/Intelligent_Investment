"""QMT 网关离线测试：回调缓存、状态映射、自检报告结构。

SDK（xtquant）已安装但无 QMT 客户端，因此用模拟的回报对象
测回调与映射逻辑；真实连通性由 scripts/broker_demo.py --gateway qmt 自检。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from quant_demo.models import OrderStatus, Side

from quant_demo.brokerage.qmt_gateway import (
    _STATUS_MAP,
    QmtCallbackHandler,
    QMTGateway,
    qmt_self_test,
)


def _fake_xt_order(order_id=101, status=56, order_type=23, volume=1000,
                   price=10.0, traded=1000, traded_price=10.0,
                   symbol="600900.SH", msg=""):
    return SimpleNamespace(
        order_id=order_id, stock_code=symbol, order_type=order_type,
        order_volume=volume, price=price, traded_volume=traded,
        traded_price=traded_price, order_status=status, status_msg=msg,
    )


class TestStatusMap:
    def test_all_xtquant_statuses_covered(self) -> None:
        for code in [48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 255]:
            assert code in _STATUS_MAP

    def test_semantics(self) -> None:
        assert _STATUS_MAP[56] is OrderStatus.FILLED      # 全部成交
        assert _STATUS_MAP[57] is OrderStatus.REJECTED    # 废单
        assert _STATUS_MAP[54] is OrderStatus.CANCELLED   # 已撤
        assert _STATUS_MAP[50] is OrderStatus.CREATED     # 已报在途


class TestCallbackHandler:
    def test_order_callback_updates_snapshot(self) -> None:
        cb = QmtCallbackHandler()
        cb.on_stock_order(_fake_xt_order(order_id=1, status=50))       # 已报
        cb.on_stock_order(_fake_xt_order(order_id=1, status=56))       # 成交
        snap = cb.snapshot(1)
        assert snap is not None
        assert snap["status"] is OrderStatus.FILLED
        assert snap["side"] is Side.BUY
        assert snap["quantity"] == 1000

    def test_sell_side_detected(self) -> None:
        cb = QmtCallbackHandler()
        cb.on_stock_order(_fake_xt_order(order_id=2, status=50, order_type=24))
        assert cb.snapshot(2)["side"] is Side.SELL

    def test_missing_snapshot(self) -> None:
        assert QmtCallbackHandler().snapshot(999) is None

    def test_all_snapshots_returns_copy(self) -> None:
        cb = QmtCallbackHandler()
        cb.on_stock_order(_fake_xt_order(order_id=3, status=50))
        all1 = cb.all_snapshots()
        all1.clear()
        assert cb.snapshot(3) is not None   # 清副本不影响内部状态


class TestSelfTest:
    def test_report_structure_without_client(self) -> None:
        """无 QMT 客户端的环境：报告应给出诊断而非崩溃。"""
        report = qmt_self_test()
        assert report["sdk_installed"] is True          # 本仓库环境已装
        assert isinstance(report["client_running"], bool)
        if not report["client_running"]:
            assert report["advice"], "未就绪时必须给出建议"


class TestGatewayContract:
    def test_construct_and_not_connected(self) -> None:
        gw = QMTGateway(qmt_userdata_path="C:/x", account_id="123")
        assert gw.name == "qmt"
        with pytest.raises(ConnectionError):
            gw.query_cash()   # 未连接时给出明确错误
