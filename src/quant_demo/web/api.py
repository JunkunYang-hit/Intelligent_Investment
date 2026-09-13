"""E 部分 FastAPI 适配层。

只做 HTTP 编排，不复制策略、账户、风控和绩效计算逻辑；这些仍由现有量化内核负责。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from quant_demo.data import CsvDataService
from quant_demo.main import build_engine


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = ROOT / "config" / "demo.json"

app = FastAPI(title="Intelligent Investment Web API", version="0.1.0")
LATEST: dict[str, Any] | None = None


class BacktestRequest(BaseModel):
    data_path: str = "examples/demo_daily.csv"
    start: str | None = None
    end: str | None = None
    short_window: int = Field(5, ge=1, le=200)
    long_window: int = Field(20, ge=2, le=500)


def _serialize_result(result) -> dict[str, Any]:
    return {
        "metrics": result.metrics,
        "equity": [
            {"date": p.datetime.isoformat(), "cash": p.cash, "market_value": p.market_value, "equity": p.total_equity}
            for p in result.equity_curve
        ],
        "trades": [
            {"id": t.trade_id, "order_id": t.order_id, "symbol": t.symbol, "side": t.side.value,
             "quantity": t.quantity, "price": t.price, "datetime": t.datetime.isoformat(), "fee": t.total_fee}
            for t in result.trades
        ],
        "orders": [
            {"id": o.order_id, "symbol": o.symbol, "side": o.side.value, "quantity": o.quantity,
             "status": o.status.value, "price": o.price, "created_at": o.created_at.isoformat(),
             "reject_reason": o.reject_reason}
            for o in result.orders
        ],
        "metadata": result.metadata,
    }


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "quant-demo-web"}


@app.get("/api/config")
def config() -> dict[str, Any]:
    import json
    return json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))


@app.post("/api/backtest/run")
def run_backtest(request: BacktestRequest) -> dict[str, Any]:
    global LATEST
    import json

    data_path = Path(request.data_path)
    if not data_path.is_absolute():
        data_path = ROOT / data_path
    if not data_path.exists():
        raise HTTPException(status_code=404, detail=f"数据文件不存在: {data_path}")

    config = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))
    config["strategy"]["short_window"] = request.short_window
    config["strategy"]["long_window"] = request.long_window
    symbols = config["market"]["symbols"]
    try:
        bars = CsvDataService(data_path).get_bars(
            symbols,
            datetime.fromisoformat(request.start) if request.start else None,
            datetime.fromisoformat(request.end) if request.end else None,
        )
        if not bars:
            raise HTTPException(status_code=422, detail="指定区间没有可用行情数据")
        result = build_engine(config).run(bars)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    LATEST = _serialize_result(result)
    LATEST["request"] = request.model_dump()
    return LATEST


@app.get("/api/backtest/latest")
def latest_backtest() -> dict[str, Any]:
    return LATEST or {"status": "empty", "message": "尚未运行回测"}


@app.get("/api/backtest/metrics")
def latest_metrics() -> dict[str, Any]:
    return (LATEST or {}).get("metrics", {})


@app.get("/api/backtest/equity")
def latest_equity() -> list[dict[str, Any]]:
    return (LATEST or {}).get("equity", [])


@app.get("/api/backtest/trades")
def latest_trades() -> list[dict[str, Any]]:
    return (LATEST or {}).get("trades", [])


@app.get("/api/backtest/orders")
def latest_orders() -> list[dict[str, Any]]:
    return (LATEST or {}).get("orders", [])
