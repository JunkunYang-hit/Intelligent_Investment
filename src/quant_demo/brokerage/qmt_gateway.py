"""QMT / miniQMT 券商网关适配器（A股实盘与仿真）。

老师的修改意见之二：接入真正的券商接口。本适配器按迅投官方 xtquant SDK
的公开接口编写，代码路径是真实可用的；但要实际连通，必须先完成开户与
授权（本代码无法替代），完整步骤见 ``brokerage/README.md``：

  1. 在支持 QMT 的券商（国金/国盛/中泰/华鑫等）开立证券账户；
  2. 向券商申请开通 QMT 或 miniQMT 量化交易权限（部分券商有资金门槛）；
  3. 本机安装 QMT 客户端并登录（极简模式即 miniQMT，保持后台运行）；
  4. ``pip install xtquant``；
  5. 用 QMT 客户端安装目录下的 ``userdata_mini`` 路径初始化本网关。

风险与合规：程序化实盘交易须遵守券商协议与交易所报备要求；
下单频率、报撤单比由券商风控约束，切勿高频报撤单。
"""

from __future__ import annotations

from datetime import datetime

from quant_demo.models import Order, OrderRequest, OrderStatus, Position, Side

from .base import BrokerGateway


class QMTGateway(BrokerGateway):
    """对接 miniQMT（XtQuantTrader）的 A股网关。"""

    name = "qmt"

    def __init__(
        self,
        qmt_userdata_path: str,
        account_id: str,
        session_id: int = 888888,
    ) -> None:
        """
        :param qmt_userdata_path: QMT 客户端 ``userdata_mini`` 目录的绝对路径
        :param account_id: 资金账号
        :param session_id: 交易会话号（1~2^31，同一客户端并发时各用不同值）
        """
        self._path = qmt_userdata_path
        self._account_id = account_id
        self._session_id = session_id
        self._trader = None
        self._account = None

    # ---- 连接 -------------------------------------------------------------- #
    def connect(self) -> bool:
        from xtquant.xttrader import XtQuantTrader
        from xtquant.xttype import StockAccount

        self._trader = XtQuantTrader(self._path, self._session_id)
        self._trader.start()
        if not self._trader.connect():
            return False
        self._account = StockAccount(self._account_id)
        return bool(self._trader.subscribe(self._account))

    def disconnect(self) -> None:
        if self._trader is not None:
            self._trader.stop()
            self._trader = None
        self._account = None

    def _ensure_connected(self) -> None:
        if self._trader is None or self._account is None:
            raise ConnectionError("QMT 网关未连接，请先调用 connect()")

    # ---- 交易 -------------------------------------------------------------- #
    def place_order(
        self,
        req: OrderRequest,
        order_type: str = "limit",
        price: float | None = None,
    ) -> str:
        from xtquant import xtconstant

        self._ensure_connected()
        action = xtconstant.STOCK_BUY if req.side == Side.BUY else xtconstant.STOCK_SELL
        price_type = xtconstant.FIX_PRICE if order_type == "limit" else xtconstant.LATEST_PRICE
        # 内部代码 600000.SH 与 QMT 代码格式一致，无需翻译
        seq = self._trader.order_stock(
            self._account, req.symbol, action, req.quantity, price_type, price
        )
        if seq < 0:
            raise RuntimeError(f"QMT 下单失败，错误码 {seq}（账号/权限/合约状态问题）")
        return str(seq)

    def cancel_order(self, broker_order_id: str) -> bool:
        self._ensure_connected()
        return self._trader.cancel_order_stock(self._account, int(broker_order_id)) == 0

    # ---- 查询 -------------------------------------------------------------- #
    def query_order(self, broker_order_id: str) -> Order | None:
        self._ensure_connected()
        wanted = int(broker_order_id)
        for xo in self._trader.query_stock_orders(self._account, True):
            if xo.stock_orders.order_id != wanted:
                continue
            status_map = {
                48: OrderStatus.CREATED,    # 已报
                49: OrderStatus.CREATED,    # 部分成交仍在途
                50: OrderStatus.CREATED,    # 部分成交
                51: OrderStatus.CREATED,    # 待报
                52: OrderStatus.CREATED,    # 已报待撤
                53: OrderStatus.FILLED,
                54: OrderStatus.CANCELLED,
                55: OrderStatus.CANCELLED,
                56: OrderStatus.REJECTED,
            }
            return Order(
                order_id=broker_order_id,
                symbol=xo.stock_orders.stock_code,
                side=Side.BUY if xo.stock_orders.order_type == 23 else Side.SELL,
                quantity=int(xo.stock_orders.order_volume),
                created_at=datetime.now(),
                status=status_map.get(xo.stock_orders.order_status, OrderStatus.CREATED),
                price=xo.stock_orders.price,
                reject_reason=getattr(xo.stock_orders, "status_msg", None),
            )
        return None

    def query_positions(self) -> list[Position]:
        self._ensure_connected()
        result: list[Position] = []
        for xp in self._trader.query_stock_positions(self._account, True):
            p = xp.stock_positions
            if p.can_use_volume <= 0 and p.volume <= 0:
                continue
            result.append(
                Position(
                    symbol=p.stock_code,
                    quantity=int(p.volume),
                    average_cost=float(p.open_price) or 0.0,
                    last_price=float(p.market_value / p.volume) if p.volume else 0.0,
                )
            )
        return result

    def query_cash(self) -> float:
        self._ensure_connected()
        asset = self._trader.query_stock_asset(self._account)
        if asset is None:
            raise ConnectionError("查询资产失败（会话可能已断开）")
        return float(asset.cash)
