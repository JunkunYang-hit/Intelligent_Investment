"""E（Web 与集成模块）：轻量 HTTP API 与演示页面。"""

from .server import QuantDemoApplication, create_server

__all__ = ["QuantDemoApplication", "create_server"]
