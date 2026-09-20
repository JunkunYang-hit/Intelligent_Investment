"""富途 OpenAPI 券商网关适配器（港股 / 美股 / A股通，支持模拟盘）。

老师的修改意见之二、之三：接入真正的券商接口 + 港股美股对接。富途 OpenAPI
同时覆盖港股与美股行情交易，且提供官方模拟盘（SIMULATE），是课程环境下
最可行的真实通道。代码按富途官方 futu-sdk 公开接口编写；实际连通需要：

  1. 注册富途牛牛并开通证券账户（港股/美股需签署对应市场协议）；
  2. 本机下载并运行 OpenD 网关程序，登录账户（默认端口 11111）；
  3. ``pip install futu-api``；
  4. 模拟盘：``simulate=True``（使用富途模拟账户，无需真实资金）；
     实盘：``simulate=False`` 且需在 OpenD 中开启交易解锁（unlock_trade）。

完整步骤与风险提示见 ``brokerage/README.md``。
"""

from __future__ import annotations

import socket
from datetime import datetime

from quant_demo.models import Order, OrderRequest, OrderStatus, Position, Side

from .base import BrokerGateway


def to_futu_code(symbol: str) -> str:
    """内部代码 -> 富途代码：0700.HK -> HK.0700，AAPL.US -> US.AAPL，600000.SH -> SH.600000。"""
    num, suffix = symbol.rsplit(".", 1)
    suffix = suffix.upper()
    if suffix == "HK":
        return f"HK.{num}"
    if suffix == "US":
        return f"US.{num}"
    if suffix in ("SH", "SZ"):
        return f"{suffix}.{num}"
    raise ValueError(f"无法识别的代码: {symbol}")


def from_futu_code(symbol: str) -> str:
    """富途代码转回系统内部格式，例如 US.AAPL -> AAPL.US。"""
    market, code = symbol.split(".", 1)
    return f"{code}.{market}"


class FutuGateway(BrokerGateway):
    """对接富途 OpenD 的交易网关。market: 'HK' | 'US'。"""

    name = "futu"

    def __init__(
        self,
        market: str = "HK",
        host: str = "127.0.0.1",
        port: int = 11111,
        simulate: bool = True,
        unlock_key: str | None = None,
        account_id: str | None = None,
    ) -> None:
        if market not in ("HK", "US"):
            raise ValueError("market 仅支持 'HK' 或 'US'")
        self._market = market
        self._host = host
        self._port = port
        self._simulate = simulate
        self._unlock_key = unlock_key
        self._account_id = int(account_id) if account_id else None
        self._ctx = None
        self._trd_env = None
        self._trd_side_mod = None

    # ---- 连接 -------------------------------------------------------------- #
    def connect(self) -> bool:
        import futu as ft

        # OpenSecTradeContext 在端口不可用时会长时间重试。先做快速探测，
        # 让未启动 OpenD 的开发/演示环境立即得到 False。
        try:
            with socket.create_connection((self._host, self._port), timeout=0.8):
                pass
        except OSError:
            return False

        # futu-api 10.x 统一为 OpenSecTradeContext；旧版仍保留市场专用类。
        legacy_name = "OpenHKTradeContext" if self._market == "HK" else "OpenUSTradeContext"
        ctx_cls = getattr(ft, legacy_name, None)
        if ctx_cls is not None:
            self._ctx = ctx_cls(host=self._host, port=self._port)
        else:
            market = ft.TrdMarket.HK if self._market == "HK" else ft.TrdMarket.US
            self._ctx = ft.OpenSecTradeContext(
                filter_trdmarket=market, host=self._host, port=self._port
            )
        ret, accounts = self._ctx.get_acc_list()
        if ret != 0:
            return False
        self._trd_env = ft.TrdEnv.SIMULATE if self._simulate else ft.TrdEnv.REAL
        self._ft = ft
        if self._account_id is None and accounts is not None and len(accounts) > 0:
            matching = accounts
            if "trd_env" in accounts.columns:
                expected = "SIMULATE" if self._simulate else "REAL"
                filtered = accounts[accounts["trd_env"].astype(str).str.endswith(expected)]
                if len(filtered) > 0:
                    matching = filtered
            if "acc_id" in matching.columns:
                self._account_id = int(matching.iloc[0]["acc_id"])
        if not self._simulate and self._unlock_key:
            # 实盘交易必须先解锁（在 OpenD 端配置交易密码）
            r, _ = self._ctx.unlock_trade(self._unlock_key)
            if r != 0:
                raise PermissionError("交易解锁失败，无法进入实盘模式")
        return True

    def _account_kwargs(self) -> dict[str, object]:
        """返回下单和查询共用的交易环境、账户编号参数。"""
        values: dict[str, object] = {"trd_env": self._trd_env}
        if self._account_id is not None:
            values["acc_id"] = self._account_id
        return values

    def disconnect(self) -> None:
        if self._ctx is not None:
            self._ctx.close()
            self._ctx = None

    def _ensure_connected(self) -> None:
        if self._ctx is None:
            raise ConnectionError("富途网关未连接，请先调用 connect()")

    # ---- 交易 -------------------------------------------------------------- #
    def place_order(
        self,
        req: OrderRequest,
        order_type: str = "limit",
        price: float | None = None,
    ) -> str:
        ft = self._ft
        self._ensure_connected()
        code = to_futu_code(req.symbol)
        trd_side = ft.TrdSide.BUY if req.side == Side.BUY else ft.TrdSide.SELL
        order_type_map = {
            "limit": ft.OrderType.LIMIT,
            "market": ft.OrderType.MARKET,
        }
        if order_type not in order_type_map:
            raise ValueError(f"不支持的订单类型: {order_type}")
        ret, data = self._ctx.place_order(
            price=price or 0.0,
            qty=float(req.quantity),
            code=code,
            trd_side=trd_side,
            order_type=order_type_map[order_type],
            **self._account_kwargs(),
        )
        if ret != 0:
            raise RuntimeError(f"富途下单失败: {data}")
        return str(data["order_id"])

    def cancel_order(self, broker_order_id: str) -> bool:
        self._ensure_connected()
        ret, _ = self._ctx.modify_order(
            modify_op=self._ft.ModifyOrderOp.CANCEL,
            order_id=broker_order_id,
            qty=0,
            price=0,
            **self._account_kwargs(),
        )
        return ret == 0

    # ---- 查询 -------------------------------------------------------------- #
    def query_order(self, broker_order_id: str) -> Order | None:
        self._ensure_connected()
        query = getattr(self._ctx, "order_list_query", None) or self._ctx.order_list
        ret, data = query(
            order_id=broker_order_id, refresh_cache=True, **self._account_kwargs()
        )
        if ret != 0 or data is None or len(data) == 0:
            return None
        row = data.iloc[0]
        status_map = {
            "NONE": OrderStatus.CREATED,
            "WAITING_SUBMIT": OrderStatus.CREATED,
            "SUBMITTED": OrderStatus.CREATED,
            "DEALING": OrderStatus.CREATED,
            "CANCELLED": OrderStatus.CANCELLED,
            "CANCEL_SUBMIT": OrderStatus.CANCELLED,
            "FILLED_ALL": OrderStatus.FILLED,
            "FILLED_PART": OrderStatus.CREATED,
            "SUBMIT_FAILED": OrderStatus.REJECTED,
            "CANCEL_FAILED": OrderStatus.REJECTED,
            "FAILED": OrderStatus.REJECTED,
        }
        return Order(
            order_id=broker_order_id,
            symbol=from_futu_code(str(row["code"])),
            side=Side.BUY if str(row["trd_side"]).endswith("BUY") else Side.SELL,
            quantity=int(row["qty"]),
            created_at=datetime.now(),
            status=status_map.get(str(row["order_status"]), OrderStatus.CREATED),
            price=float(row["price"]) if row["price"] else None,
        )

    def query_positions(self) -> list[Position]:
        self._ensure_connected()
        query = getattr(self._ctx, "position_list_query", None) or self._ctx.position_list
        ret, data = query(**self._account_kwargs())
        if ret != 0:
            raise ConnectionError(f"查询持仓失败: {data}")
        result: list[Position] = []
        for _, row in data.iterrows():
            qty = int(row["qty"])
            if qty <= 0:
                continue
            result.append(
                Position(
                    symbol=from_futu_code(str(row["code"])),
                    quantity=qty,
                    average_cost=float(row["cost_price"]) or 0.0,
                    last_price=float(row["cur_price"]) or 0.0,
                )
            )
        return result

    def query_cash(self) -> float:
        self._ensure_connected()
        query = getattr(self._ctx, "accinfo_query", None) or self._ctx.accinfo_get
        ret, data = query(
            currency="HKD" if self._market == "HK" else "USD",
            **self._account_kwargs(),
        )
        if ret != 0:
            raise ConnectionError(f"查询资产失败: {data}")
        return float(data.iloc[0]["cash"])
