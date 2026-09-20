"""回测历史持久化测试：确认保存后可跨应用实例读取。"""

from __future__ import annotations

from pathlib import Path

from quant_demo.web.server import QuantDemoApplication


ROOT = Path(__file__).parents[1]


def request() -> dict[str, object]:
    return {
        "symbol": "510300.SH",
        "start": "2022-01-01",
        "end": "2022-03-01",
        "strategy": "dual_moving_average",
        "strategy_params": {"short_window": 5, "long_window": 20},
        "initial_cash": 1_000_000,
        "target_weight": 0.2,
    }


def app(history_dir: Path) -> QuantDemoApplication:
    return QuantDemoApplication(
        ROOT / "config/demo.json",
        ROOT / "examples/demo_daily.csv",
        history_dir,
    )


def test_backtest_is_saved_and_can_be_loaded_after_restart(tmp_path: Path) -> None:
    first_app = app(tmp_path / "history")
    report = first_app.run_backtest(request())
    history_id = report["history"]["id"]

    second_app = app(tmp_path / "history")
    rows = second_app.list_backtests()["items"]
    restored = second_app.get_backtest(history_id)

    assert len(rows) == 1
    assert rows[0]["id"] == history_id
    assert rows[0]["symbol"] == "510300.SH"
    assert restored["result"]["metrics"] == report["result"]["metrics"]
    assert restored["result"]["equity_curve"] == report["result"]["equity_curve"]


def test_saved_backtest_can_be_deleted(tmp_path: Path) -> None:
    application = app(tmp_path / "history")
    history_id = application.run_backtest(request())["history"]["id"]

    result = application.delete_backtest(history_id)

    assert result == {"deleted": True, "id": history_id}
    assert application.list_backtests()["items"] == []
