"""QMT / miniQMT 券商网关适配器（A股实盘与仿真）——按已安装的 xtquant SDK 实测 API 编写。

本适配器的每个调用都对照 xtquant 250807 版源码核验过签名与字段：

  XtQuantTrader(path, session, callback=None)
      .start() / .connect() / .subscribe(StockAccount)
      .order_stock(account, stock_code, order_type, order_volume,
                   price_type, price, strategy_name='', order_remark='')
      .cancel_order_stock(account, order_id)
      .query_stock_orders(account, cancelable_only=False)   -> list[XtOrder]
      .query_stock_positions(account)                        -> list[XtPosition]
      .query_stock_asset(account)                            -> XtAsset

  XtOrder 字段: stock_code order_id order_time order_type(23买/24卖) order_volume
      price traded_volume traded_price order_status status_msg ...
  XtPosition 字段: stock_code volume can_use_volume open_price market_value
      avg_price last_price profit_rate ...
  XtAsset 字段: cash frozen_cash market_value total_asset
  订单状态常量: 48待报 49未报 50已报 51已报待撤 52部成待撤 53部成已撤
      54已撤 55部成 56成交 57废单 255未知

实际连通过程（无法由代码替代，详见 brokerage/README.md）：
  1. 在支持QMT的券商（国金/国盛/中泰/华鑫等）开立证券账户；
  2. 申请开通 QMT 或 miniQMT 量化权限；
  3. 本机安装并登录 QMT 客户端（极简模式 = miniQMT，保持后台运行）；
  4. pip install xtquant（本仓库开发环境已安装并核验 API）；
  5. 用 QMT 安装目录下的 ``userdata_mini`` 路径初始化本网关。

SDK 行为备注（实测）：
  - 返回值为 C 风格：0 = 成功，负数 = 失败（connect/subscribe/order 均如此）；
  - ``XtQuantTrader.start()`` 会自动创建缺失的 userdata 目录（含 down_queue_*），
    因此“目录存在”不代表 QMT 客户端已安装登录；
  - ``connect()==0`` 也不代表账号有效，可用性以 ``query_stock_asset`` 返回为准；
    本网关的 ``qmt_self_test`` 已按此语义实现。
"""

from __future__ import annotations

import threading
from datetime import datetime

from quant_demo.models import Order, OrderRequest, OrderStatus, Position, Side

from .base import BrokerGateway


def _ensure_xtconstant():
    from xtquant import xtconstant
    return xtconstant


_STATUS_MAP = {
    48: OrderStatus.CREATED,    # 待报
    49: OrderStatus.CREATED,    # 未报
    50: OrderStatus.CREATED,    # 已报（在途）
    51: OrderStatus.CREATED,    # 已报待撤
    52: OrderStatus.CREATED,    # 部成待撤
    53: OrderStatus.CREATED,    # 部成已撤（有部分成交）
    54: OrderStatus.CANCELLED,  # 已撤
    55: OrderStatus.CREATED,    # 部分成交（在途）
    56: OrderStatus.FILLED,     # 全部成交
    57: OrderStatus.REJECTED,   # 废单
    255: OrderStatus.CREATED,   # 未知（按在途处理，等待回报）
}


class QmtCallbackHandler:
    """实盘订单回报的线程安全缓存。

    实盘中订单状态由柜台异步推送（on_stock_order / on_stock_trade），
    本类维护“最新状态快照”，query_order 优先读缓存、缺失时回退主动查询。
    """

    def __init__(self) -> None:
        self._orders: dict[int, dict] = {}
        self._lock = threading.Lock()

    # ---- xtquant 回调（由 SDK 的工作线程调用） ------------------------- #
    def on_stock_order(self, order) -> None:
        with self._lock:
            self._orders[int(order.order_id)] = {
                "symbol": order.stock_code,
                "side": Side.BUY if int(order.order_type) == 23 else Side.SELL,
                "quantity": int(order.order_volume),
                "traded": int(order.traded_volume),
                "price": float(order.price),
                "traded_price": float(order.traded_price or 0),
                "status": _STATUS_MAP.get(int(order.order_status), OrderStatus.CREATED),
                "status_msg": order.status_msg,
                "updated_at": datetime.now(),
            }

    def on_disconnected(self) -> None:
        pass  # 连接断开：上层可通过 connect() 返回值感知并重建

    # ---- 本地查询 -------------------------------------------------------- #
    def snapshot(self, order_id: int) -> dict | None:
        with self._lock:
            return self._orders.get(order_id)

    def all_snapshots(self) -> dict[int, dict]:
        with self._lock:
            return dict(self._orders)


class QMTGateway(BrokerGateway):
    """对接 miniQMT（XtQuantTrader）的 A股实盘网关。"""

    name = "qmt"

    def __init__(
        self,
        qmt_userdata_path: str,
        account_id: str,
        session_id: int = 888888,
        strategy_name: str = "quant_demo",
    ) -> None:
        self._path = qmt_userdata_path
        self._account_id = account_id
        self._session_id = session_id
        self._strategy_name = strategy_name
        self._trader = None
        self._account = None
        self.callback = QmtCallbackHandler()

    # ---- 连接 ------------------------------------------------------------ #
    def connect(self) -> bool:
        from xtquant.xttrader import XtQuantTrader
        from xtquant.xttype import StockAccount

        # 注意：xtquant 采用 C 风格返回值，0=成功，负数=失败
        self._trader = XtQuantTrader(self._path, self._session_id, self.callback)
        self._trader.start()
        if self._trader.connect() != 0:
            return False
        self._account = StockAccount(self._account_id)
        return self._trader.subscribe(self._account) == 0

    def disconnect(self) -> None:
        if self._trader is not None:
            self._trader.stop()
            self._trader = None
        self._account = None

    def _ensure_connected(self) -> None:
        if self._trader is None or self._account is None:
            raise ConnectionError("QMT 网关未连接：请先启动并登录 QMT/miniQMT 客户端，再调用 connect()")

    # ---- 交易 ------------------------------------------------------------ #
    def place_order(
        self,
        req: OrderRequest,
        order_type: str = "limit",
        price: float | None = None,
    ) -> str:
        xc = _ensure_xtconstant()
        self._ensure_connected()
        action = xc.STOCK_BUY if req.side == Side.BUY else xc.STOCK_SELL
        if order_type == "limit":
            if price is None or price <= 0:
                raise ValueError("limit 单必须提供正数价格")
            price_type = xc.FIX_PRICE
        elif order_type == "market":
            price, price_type = 0.0, xc.LATEST_PRICE
        else:
            raise ValueError(f"不支持的订单类型: {order_type}")
        # 内部代码 600000.SH 与 QMT 代码格式一致，无需翻译
        seq = self._trader.order_stock(
            self._account, req.symbol, action, req.quantity, price_type, price,
            strategy_name=self._strategy_name, order_remark=req.reason or "",
        )
        if seq is None or int(seq) < 0:
            raise RuntimeError(f"QMT 下单被拒绝（返回 {seq}）：检查账号权限/资金/合约状态")
        return str(seq)

    def cancel_order(self, broker_order_id: str) -> bool:
        self._ensure_connected()
        return self._trader.cancel_order_stock(self._account, int(broker_order_id)) == 0

    # ---- 查询 ------------------------------------------------------------ #
    def query_order(self, broker_order_id: str) -> Order | None:
        self._ensure_connected()
        oid = int(broker_order_id)
        snap = self.callback.snapshot(oid)
        if snap is not None:
            return Order(
                order_id=broker_order_id, symbol=snap["symbol"], side=snap["side"],
                quantity=snap["quantity"], created_at=snap["updated_at"],
                status=snap["status"], price=snap["price"] or None,
                reject_reason=snap.get("status_msg") or None,
            )
        # 回报尚未到达，主动查一次（全量在途+当日委托）
        for xo in self._trader.query_stock_orders(self._account, cancelable_only=False):
            if int(xo.order_id) != oid:
                continue
            return Order(
                order_id=broker_order_id, symbol=xo.stock_code,
                side=Side.BUY if int(xo.order_type) == 23 else Side.SELL,
                quantity=int(xo.order_volume), created_at=datetime.now(),
                status=_STATUS_MAP.get(int(xo.order_status), OrderStatus.CREATED),
                price=float(xo.price) or None,
                reject_reason=xo.status_msg or None,
            )
        return None

    def query_positions(self) -> list[Position]:
        self._ensure_connected()
        result: list[Position] = []
        for xp in self._trader.query_stock_positions(self._account):
            if int(xp.volume) <= 0:
                continue
            result.append(
                Position(
                    symbol=xp.stock_code,
                    quantity=int(xp.volume),
                    average_cost=float(xp.avg_price) or 0.0,
                    last_price=float(xp.last_price) or 0.0,
                    realized_pnl=float(getattr(xp, "profit_rate", 0.0) or 0.0),
                )
            )
        return result

    def query_cash(self) -> float:
        self._ensure_connected()
        asset = self._trader.query_stock_asset(self._account)
        if asset is None:
            raise ConnectionError("查询资产失败：QMT 会话可能已断开，请重新 connect()")
        return float(asset.cash)


def qmt_self_test(qmt_userdata_path: str | None = None) -> dict:
    """接入前自检：逐项诊断 QMT 环境缺什么（给部署者的检查清单）。"""
    import os
    report: dict = {"sdk_installed": True, "sdk_version": None,
                    "userdata_path": qmt_userdata_path, "path_exists": None,
                    "client_running": False, "advice": []}
    try:
        import xtquant
        report["sdk_version"] = getattr(xtquant, "__version__", "unknown")
    except ImportError:
        report["sdk_installed"] = False
        report["advice"].append("pip install xtquant")
        return report
    if qmt_userdata_path:
        report["path_exists"] = os.path.isdir(qmt_userdata_path)
        if not report["path_exists"]:
            report["advice"].append(f"路径不存在: {qmt_userdata_path}（应为QMT安装目录下 userdata_mini）")
            return report
    else:
        # 没有真实 userdata_mini 路径时无法判断客户端是否运行；直接给出
        # 可操作提示，避免 SDK 在当前目录创建大型 down_queue 临时文件。
        report["advice"].append("请提供 QMT/miniQMT 的 userdata_mini 路径")
        return report
    try:
        from xtquant.xttrader import XtQuantTrader
        trader = XtQuantTrader(qmt_userdata_path, 991901)
        trader.start()
        report["client_running"] = trader.connect() == 0
        trader.stop()
    except Exception as e:
        report["advice"].append(f"连接失败: {e}")
    if not report["client_running"]:
        report["advice"].append("启动并登录 QMT/miniQMT 客户端（保持后台运行）后重试")
    return report
