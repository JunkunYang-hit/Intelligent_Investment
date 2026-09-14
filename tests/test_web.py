"""E Web 集成层测试：确认参数校验与现有交易内核正确对接。"""

from __future__ import annotations

from pathlib import Path

import pytest

from quant_demo.web.server import ApiError, QuantDemoApplication


ROOT = Path(__file__).parents[1]


def application() -> QuantDemoApplication:
    return QuantDemoApplication(ROOT / "config/demo.json", ROOT / "examples/demo_daily.csv")


def valid_request() -> dict[str, object]:
    return {
        "symbol": "510300.SH",
        "start": "2022-01-01",
        "end": "2023-12-31",
        "strategy": "dual_moving_average",
        "strategy_params": {"short_window": 5, "long_window": 20},
        "initial_cash": 1_000_000,
        "target_weight": 0.2,
    }


def test_bootstrap_reports_actual_dataset_range() -> None:
    payload = application().bootstrap()

    assert payload["symbols"] == ["510300.SH"]
    assert payload["date_min"] == "2021-09-14"
    assert payload["date_max"] == "2026-09-11"
    assert payload["bar_count"] == 1210


def test_backtest_serializes_real_engine_result_and_snapshot() -> None:
    payload = application().run_backtest(valid_request())

    assert payload["summary"]["bar_count"] > 400
    assert len(payload["summary"]["snapshot_id"]) == 16
    assert payload["result"]["metadata"]["execution_rule"] == "signal close -> next bar open"
    assert len(payload["result"]["equity_curve"]) == payload["summary"]["bar_count"]
    assert len(payload["benchmark_curve"]) == payload["summary"]["bar_count"]
    assert payload["result"]["metrics"]["initial_equity"] == 1_000_000
    assert payload["account"]["total_equity"] == payload["result"]["metrics"]["final_equity"]
    assert isinstance(payload["account"]["positions"], list)


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"symbol": "UNKNOWN"}, "标的不在配置允许范围内"),
        ({"start": "2024-01-01", "end": "2023-01-01"}, "开始日期不能晚于结束日期"),
        ({"strategy_params": {"short_window": 20, "long_window": 5}}, "短均线周期必须小于长均线周期"),
        ({"target_weight": 1.1}, "目标仓位不能超过 100%"),
    ],
)
def test_invalid_input_returns_explainable_error(updates: dict[str, object], message: str) -> None:
    request = valid_request()
    request.update(updates)

    with pytest.raises(ApiError, match=message):
        application().run_backtest(request)


def test_simulation_advances_one_bar_and_uses_account_snapshot() -> None:
    app = application()
    request = valid_request()
    request.update({"start": "2022-01-01", "end": "2022-03-01"})

    initial = app.start_simulation(request)
    first = app.step_simulation()

    assert initial["index"] == 0
    assert first["index"] == 1
    assert first["current_date"].startswith("2022-01-04")
    assert first["account"]["total_equity"] == 1_000_000
