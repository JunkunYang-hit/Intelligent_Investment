"""券商网关：统一实盘/模拟交易通道。"""

from .base import BrokerGateway
from .paper import PaperBrokerGateway


def __getattr__(name: str):
    # SDK 适配器延迟导入：未安装对应 SDK 时不影响包导入
    if name == "QMTGateway":
        from .qmt_gateway import QMTGateway
        return QMTGateway
    if name == "FutuGateway":
        from .futu_gateway import FutuGateway
        return FutuGateway
    raise AttributeError(name)


__all__ = ["BrokerGateway", "PaperBrokerGateway", "QMTGateway", "FutuGateway"]
