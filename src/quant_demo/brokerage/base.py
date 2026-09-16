"""券商网关抽象接口。

老师的修改意见之二：接入真正的券商接口。本包提供统一的 ``BrokerGateway``
契约：回测/模拟与实盘共用同一套下单、撤单、查询语义，切换券商只需更换网关实现。

实盘接入的现实约束（诚实说明，详见 README.md）：
  - 任何真实券商接口都需要「证券账户 + 量化权限 + 本机客户端/网关程序」，
    代码层无法替代开户与授权流程；
  - 因此本包提供：①本地模拟网关（课程演示可直接跑通全流程）；
    ②QMT/miniQMT 与富途 OpenAPI 两套真实适配器（按官方 SDK 编写，
    安装对应 SDK 并完成开户授权后即可实际连通）；
    ③模拟盘模式（富途 OpenD SIMULATE）用于真实环境下的仿真交易。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from quant_demo.models import Order, OrderRequest, Position


class BrokerGateway(ABC):
    """对接外部交易通道的统一契约。

    实现方必须保证：
      - ``place_order`` 返回网关侧唯一订单号（字符串）；
      - 所有查询方法在断线/超时时抛出 ``ConnectionError`` 而非静默返回脏数据；
      - A股代码使用 ``600000.SH/000001.SZ``，港股 ``0700.HK``，美股 ``AAPL.US``
        （内部格式），由各适配器自行翻译为券商格式。
    """

    name: str = "base"

    @abstractmethod
    def connect(self) -> bool:
        """建立连接。返回是否成功。"""

    @abstractmethod
    def disconnect(self) -> None:
        """断开连接并释放资源。"""

    @abstractmethod
    def place_order(
        self,
        req: OrderRequest,
        order_type: str = "limit",
        price: float | None = None,
    ) -> str:
        """下单。``order_type``: 'limit' | 'market'。返回网关侧订单号。"""

    @abstractmethod
    def cancel_order(self, broker_order_id: str) -> bool:
        """撤单。返回是否成功提交撤单请求。"""

    @abstractmethod
    def query_order(self, broker_order_id: str) -> Order | None:
        """查询订单状态。找不到返回 None。"""

    @abstractmethod
    def query_positions(self) -> list[Position]:
        """查询全部持仓。"""

    @abstractmethod
    def query_cash(self) -> float:
        """查询可用资金（账户本币）。"""
