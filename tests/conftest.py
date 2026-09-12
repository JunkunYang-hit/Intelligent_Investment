"""pytest 共享配置。"""

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--run-network",
        action="store_true",
        default=False,
        help="运行需要联网的 BaoStock 测试",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "network: 标记需要联网的测试，默认跳过，用 --run-network 启用"
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-network"):
        return
    skip_network = pytest.mark.skip(reason="需要 --run-network 参数才运行联网测试")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip_network)
