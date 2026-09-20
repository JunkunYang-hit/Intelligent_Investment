"""E Web 集成层测试：确认参数校验与现有交易内核正确对接。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from quant_demo.web.server import ApiError, QuantDemoApplication
from quant_demo.brokerage import PaperBrokerGateway


ROOT = Path(__file__).parents[1]


def application() -> QuantDemoApplication:
    return QuantDemoApplication(
        ROOT / "config/demo.json",
        ROOT / "examples/demo_daily.csv",
        now_provider=lambda: datetime(2026, 9, 14, 10, 0),
    )


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
    assert payload["symbol_names"]["510300.SH"] == "沪深300ETF"
    assert payload["lot_sizes"]["510300.SH"] == 100
    assert payload["date_min"] == "2021-09-14"
    assert payload["date_max"] == "2026-09-11"
    assert payload["bar_count"] == 1210
    assert payload["symbol_ranges"]["510300.SH"]["bar_count"] == 1210
    assert "warning_count" in payload["data_quality"]


def test_web_uses_blue_white_theme_and_shows_max_drawdown() -> None:
    html = (ROOT / "src/quant_demo/web/static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "src/quant_demo/web/static/styles.css").read_text(encoding="utf-8")

    assert 'name="color-scheme" content="light"' in html
    assert 'id="result-max-drawdown"' in html
    assert "收益与风险指标" in html
    assert "--bg: #f3f7fc" in css
    assert "--panel: #ffffff" in css
    assert 'id="view-broker"' in html
    assert 'id="view-simulation"' not in html
    assert 'id="view-history"' in html
    assert 'id="view-ai"' in html
    assert 'type="password" name="api_key"' in html
    assert 'id="initial-cash" min="10000" step="10000"' in html
    assert 'id="broker-refresh"' in html
    assert 'id="result-detail"' in html
    assert 'id="strategy-description"' in html
    assert 'id="target-weight" min="1" max="100"' in html
    assert 'id="history-prev"' in html
    assert 'id="side-backtest-data"' in html
    assert 'id="side-broker-data"' in html
    assert 'id="broker-connect-form"' in html
    assert 'value="futu"' in html
    assert 'name="account_id"' in html
    javascript = (ROOT / "src/quant_demo/web/static/app.js").read_text(encoding="utf-8")
    assert "historyPageSize: 10" in javascript


def test_backtest_serializes_real_engine_result_and_snapshot() -> None:
    payload = application().run_backtest(valid_request())

    assert payload["summary"]["bar_count"] > 400
    assert len(payload["summary"]["snapshot_id"]) == 16
    assert payload["result"]["metadata"]["execution_rule"] == "signal close -> next bar open"
    assert len(payload["result"]["equity_curve"]) == payload["summary"]["bar_count"]
    assert len(payload["benchmark_curve"]) == payload["summary"]["bar_count"]
    assert payload["result"]["metrics"]["initial_equity"] == 1_000_000


@pytest.mark.parametrize(
    ("strategy", "params"),
    [
        ("dual_moving_average", {"short_window": 5, "long_window": 20}),
        ("rsi", {"period": 14, "oversold": 30, "overbought": 70}),
        ("macd", {"fast_period": 12, "slow_period": 26, "signal_period": 9}),
        ("bollinger", {"period": 20, "std_multiplier": 2}),
    ],
)
def test_complete_user_backtest_flow_supports_every_visible_strategy(
    strategy: str, params: dict[str, float | int]
) -> None:
    request = valid_request()
    request.update({"strategy": strategy, "strategy_params": params})

    payload = application().run_backtest(request)

    assert payload["summary"]["bar_count"] == len(payload["result"]["equity_curve"])
    assert payload["result"]["metrics"]["trade_count"] > 0
    assert payload["summary"]["rejected_order_count"] == 0


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


def test_paper_broker_market_order_updates_cash_position_and_order() -> None:
    app = application()
    reset = app.reset_paper_broker({"initial_cash": 1_000_000})
    result = app.place_paper_order(
        {"symbol": "510300.SH", "side": "BUY", "quantity": 100, "order_type": "market"}
    )

    assert reset["gateway"] == "paper"
    assert result["submitted_order"]["status"] == "FILLED"
    assert result["cash"] < 1_000_000
    assert result["positions"][0]["symbol"] == "510300.SH"
    assert result["positions"][0]["quantity"] == 100
    assert result["total_equity"] == pytest.approx(1_000_000)


def test_paper_broker_enforces_a_share_lot_size() -> None:
    app = application()

    with pytest.raises(ApiError, match="数量必须是每手 100 股的整数倍"):
        app.place_paper_order(
            {"symbol": "510300.SH", "side": "BUY", "quantity": 1, "order_type": "market"}
        )


def test_paper_broker_rejects_orders_outside_trading_day() -> None:
    app = QuantDemoApplication(
        ROOT / "config/demo.json",
        ROOT / "examples/demo_daily.csv",
        now_provider=lambda: datetime(2026, 9, 20, 10, 0),  # 周日
    )

    with pytest.raises(ApiError, match="周末"):
        app.place_paper_order(
            {"symbol": "510300.SH", "side": "BUY", "quantity": 100, "order_type": "market"}
        )


def test_paper_broker_rejects_orders_during_lunch_break() -> None:
    app = QuantDemoApplication(
        ROOT / "config/demo.json",
        ROOT / "examples/demo_daily.csv",
        now_provider=lambda: datetime(2026, 9, 14, 12, 0),  # 周一午间休市
    )

    with pytest.raises(ApiError, match="交易时段"):
        app.place_paper_order(
            {"symbol": "510300.SH", "side": "BUY", "quantity": 100, "order_type": "market"}
        )


def test_paper_broker_rejects_stale_online_quote(monkeypatch: pytest.MonkeyPatch) -> None:
    app = QuantDemoApplication(
        ROOT / "config/demo.json",
        ROOT / "examples/demo_daily.csv",
        now_provider=lambda: datetime(2026, 9, 14, 10, 0),
    )
    snapshot = app.market_snapshot("510300.SH")
    app.enable_realtime = True
    snapshot.update(
        {
            "price": 4.0,
            "quote_time": "20260911150000",
            "is_realtime_quote": True,
        }
    )
    monkeypatch.setattr(app, "market_snapshot", lambda _symbol: snapshot)

    with pytest.raises(ApiError, match="不是今天的数据"):
        app.place_paper_order(
            {"symbol": "510300.SH", "side": "BUY", "quantity": 100, "order_type": "market"}
        )


def test_backtest_allows_full_target_weight() -> None:
    request = valid_request()
    request["target_weight"] = 1.0

    payload = application().run_backtest(request)

    assert payload["summary"]["rejected_order_count"] == 0


def test_can_switch_to_external_futu_simulation(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeFutuGateway(PaperBrokerGateway):
        name = "futu"

        def __init__(self, **_kwargs: object) -> None:
            super().__init__(50_000)

    monkeypatch.setattr("quant_demo.web.server.FutuGateway", FakeFutuGateway)
    app = application()

    connected = app.connect_broker(
        {"gateway": "futu", "host": "127.0.0.1", "port": 11111, "market": "US"}
    )
    result = app.place_paper_order(
        {
            "symbol": "AAPL.US",
            "side": "BUY",
            "quantity": 1,
            "order_type": "limit",
            "price": 100,
        }
    )

    assert connected["gateway"] == "futu"
    assert connected["is_external_simulation"] is True
    assert connected["broker_market"] == "US"
    assert result["submitted_order"]["status"] == "FILLED"
    assert result["cash"] == 49_900


def test_external_broker_symbol_must_match_market(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeFutuGateway(PaperBrokerGateway):
        name = "futu"

        def __init__(self, **_kwargs: object) -> None:
            super().__init__()

    monkeypatch.setattr("quant_demo.web.server.FutuGateway", FakeFutuGateway)
    app = application()
    app.connect_broker({"gateway": "futu", "market": "HK"})

    with pytest.raises(ApiError, match="必须以 .HK 结尾"):
        app.place_paper_order(
            {"symbol": "AAPL.US", "side": "BUY", "quantity": 1, "order_type": "limit", "price": 1}
        )
