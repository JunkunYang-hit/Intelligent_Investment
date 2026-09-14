"""验证命令行入口委托给 C 模块的配置工厂。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from quant_demo.main import build_engine
from quant_demo.models import Bar


ROOT = Path(__file__).parents[1]


def _config() -> dict[str, object]:
    return json.loads((ROOT / "config/demo.json").read_text(encoding="utf-8"))


def _bars() -> list[Bar]:
    start = datetime(2025, 1, 1)
    prices = [10.0, 10.5, 11.0, 10.0, 9.5]
    return [
        Bar("510300.SH", start + timedelta(days=index), price, price, price, price, 1000)
        for index, price in enumerate(prices)
    ]


def test_build_engine_uses_c_factory_for_default_config() -> None:
    engine = build_engine(_config())

    assert type(engine.strategy).__name__ == "DualMovingAverageStrategy"
    assert engine.strategy_name == "dual_moving_average"
    result = engine.run(_bars())
    assert result.metadata["strategy_name"] == "dual_moving_average"
    assert result.metadata["strategy_parameters"] == {
        "short_window": 5,
        "long_window": 20,
    }


def test_build_engine_honors_configured_strategy_name() -> None:
    config = _config()
    config["strategy"] = {"name": "rsi", "period": 3, "target_weight": 0.2}

    engine = build_engine(config)

    assert type(engine.strategy).__name__ == "RSIStrategy"
    assert engine.strategy_name == "rsi"
