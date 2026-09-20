"""验证 Web 回测请求与 C 配置工厂之间的适配边界。"""

from __future__ import annotations

from pathlib import Path

import pytest

from quant_demo.web.server import ApiError, QuantDemoApplication, build_request_config


ROOT = Path(__file__).parents[1]


def application() -> QuantDemoApplication:
    return QuantDemoApplication(ROOT / "config/demo.json", ROOT / "examples/demo_daily.csv")


def request() -> dict[str, object]:
    return {
        "symbol": "510300.SH",
        "start": "2022-01-01",
        "end": "2022-12-31",
        "strategy": "rsi",
        "strategy_params": {"period": 3},
        "initial_cash": 500_000,
        "target_weight": 0.15,
    }


def test_request_config_replaces_strategy_specific_base_fields() -> None:
    config = build_request_config(application().config, request())

    assert config["strategy"] == {
        "name": "rsi",
        "period": 3,
        "target_weight": 0.15,
    }
    assert config["backtest"]["initial_cash"] == 500_000


def test_request_config_uses_symbol_specific_lot_size() -> None:
    payload = request()
    payload["symbol"] = "688981.SH"

    config = build_request_config(application().config, payload)

    assert config["market"]["lot_size"] == 200


def test_backtest_factory_errors_are_returned_as_api_errors() -> None:
    invalid = request()
    invalid["strategy"] = "unknown"

    with pytest.raises(ApiError, match="不支持的策略"):
        application().run_backtest(invalid)
