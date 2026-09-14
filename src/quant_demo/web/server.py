"""零运行时依赖的 Web 服务，负责参数校验、调用交易内核和结果序列化。"""

from __future__ import annotations

import argparse
import copy
import json
import math
import threading
from dataclasses import asdict
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from quant_demo.data import CsvDataService, detect_anomalies, snapshot_id
from quant_demo.modes import BacktestEngine, SimulationEngine, build_backtest_engine
from quant_demo.strategy import (
    BollingerBandsStrategy,
    DualMovingAverageStrategy,
    MACDStrategy,
    RSIStrategy,
    Strategy,
)
from quant_demo.trading import (
    Account,
    BrokerSimulator,
    OrderManagementSystem,
    RiskManager,
    TargetWeightSizer,
)

STATIC_DIR = Path(__file__).with_name("static")
DEFAULT_CONFIG = Path("config/demo.json")
DEFAULT_DATA = Path("examples/demo_daily.csv")


class ApiError(ValueError):
    """可安全返回给页面的参数或业务错误。"""


def _number(
    source: dict[str, Any], key: str, default: float, *, minimum: float | None = None
) -> float:
    value = source.get(key, default)
    if isinstance(value, bool):
        raise ApiError(f"{key} 必须是数字")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ApiError(f"{key} 必须是数字") from exc
    if not math.isfinite(parsed):
        raise ApiError(f"{key} 必须是有限数字")
    if minimum is not None and parsed < minimum:
        raise ApiError(f"{key} 不能小于 {minimum:g}")
    return parsed


def _integer(
    source: dict[str, Any], key: str, default: int, *, minimum: int = 1
) -> int:
    value = _number(source, key, default, minimum=float(minimum))
    if not value.is_integer():
        raise ApiError(f"{key} 必须是整数")
    return int(value)


def _date(value: Any, field: str) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise ApiError(f"{field} 日期格式无效") from exc


def build_strategy(name: str, params: dict[str, Any]) -> Strategy:
    """只组装 B 模块公开的策略，不复制策略判断逻辑。"""
    if name == "dual_moving_average":
        short_window = _integer(params, "short_window", 5)
        long_window = _integer(params, "long_window", 20)
        if short_window >= long_window:
            raise ApiError("短均线周期必须小于长均线周期")
        return DualMovingAverageStrategy(short_window, long_window)
    if name == "rsi":
        period = _integer(params, "period", 14)
        oversold = _number(params, "oversold", 30, minimum=0)
        overbought = _number(params, "overbought", 70, minimum=0)
        if not oversold < overbought <= 100:
            raise ApiError("RSI 阈值必须满足 0 ≤ 超卖 < 超买 ≤ 100")
        return RSIStrategy(period, oversold, overbought)
    if name == "macd":
        fast = _integer(params, "fast_period", 12)
        slow = _integer(params, "slow_period", 26)
        signal = _integer(params, "signal_period", 9)
        if fast >= slow:
            raise ApiError("MACD 快线周期必须小于慢线周期")
        return MACDStrategy(fast, slow, signal)
    if name == "bollinger":
        period = _integer(params, "period", 20, minimum=2)
        multiplier = _number(params, "std_multiplier", 2, minimum=0.01)
        return BollingerBandsStrategy(period, multiplier)
    raise ApiError("不支持的策略")


def build_components(config: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    """按照共享配置组装现有内核组件。"""
    market = config["market"]
    base_backtest = config["backtest"]
    base_strategy = config["strategy"]
    risk_config = config["risk"]
    strategy_name = str(request.get("strategy", base_strategy["name"]))
    strategy_params = request.get("strategy_params", {})
    if not isinstance(strategy_params, dict):
        raise ApiError("strategy_params 必须是对象")
    target_weight = _number(
        request, "target_weight", float(base_strategy["target_weight"]), minimum=0.01
    )
    if target_weight > 1:
        raise ApiError("目标仓位不能超过 100%")
    initial_cash = _number(
        request, "initial_cash", float(base_backtest["initial_cash"]), minimum=1
    )
    account = Account(initial_cash)
    return {
        "strategy": build_strategy(strategy_name, strategy_params),
        "account": account,
        "sizer": TargetWeightSizer(target_weight, int(market["lot_size"])),
        "risk": RiskManager(
            float(risk_config["max_order_value_ratio"]),
            float(risk_config["max_symbol_weight"]),
            int(market["lot_size"]),
        ),
        "oms": OrderManagementSystem(),
        "broker": BrokerSimulator(
            float(base_backtest["commission_rate"]),
            float(base_backtest["minimum_commission"]),
            float(base_backtest["sell_stamp_duty_rate"]),
            float(base_backtest["slippage_bps"]),
        ),
        "annual_trading_days": int(base_backtest["annual_trading_days"]),
    }


def build_request_config(
    base_config: dict[str, Any], request: dict[str, Any]
) -> dict[str, Any]:
    """将 Web 请求覆盖项转换为 C 工厂使用的完整配置。"""

    config = copy.deepcopy(base_config)
    base_strategy = config["strategy"]
    base_backtest = config["backtest"]
    strategy_name = str(request.get("strategy", base_strategy["name"]))
    strategy_params = request.get("strategy_params", {})
    if not isinstance(strategy_params, dict):
        raise ApiError("strategy_params 必须是对象")
    # 保留 Web 原有的有限值和参数范围校验；实例最终由 C 工厂创建。
    validation_name = strategy_name.strip().lower()
    if validation_name == "bollinger_bands":
        validation_name = "bollinger"
    build_strategy(validation_name, strategy_params)
    target_weight = _number(
        request,
        "target_weight",
        float(base_strategy["target_weight"]),
        minimum=0.01,
    )
    if target_weight > 1:
        raise ApiError("目标仓位不能超过 100%")
    initial_cash = _number(
        request,
        "initial_cash",
        float(base_backtest["initial_cash"]),
        minimum=1,
    )

    # 保留请求级参数优先级，同时禁止 strategy_params 覆盖保留字段。
    config["strategy"] = {
        **strategy_params,
        "name": strategy_name,
        "target_weight": target_weight,
    }
    config["backtest"]["initial_cash"] = initial_cash
    return config


def _factory_error_message(error: ValueError) -> str:
    """保留 Web 层已有的用户提示，同时使用 C 工厂完成校验。"""

    compatibility_messages = {
        "窗口必须满足 1 <= short_window < long_window": "短均线周期必须小于长均线周期",
    }
    return compatibility_messages.get(str(error), str(error))


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


class QuantDemoApplication:
    """HTTP 层的应用服务；数据文件在启动时固定，页面不能读取任意路径。"""

    def __init__(self, config_path: str | Path, data_path: str | Path) -> None:
        self.config_path = Path(config_path).resolve()
        self.data_path = Path(data_path).resolve()
        self.config: dict[str, Any] = json.loads(
            self.config_path.read_text(encoding="utf-8")
        )
        self.data_service = CsvDataService(self.data_path)
        self._simulation: dict[str, Any] | None = None
        self._lock = threading.Lock()

    def bootstrap(self) -> dict[str, Any]:
        symbols = list(self.config["market"]["symbols"])
        bars = self.data_service.get_bars(symbols)
        if not bars:
            raise ApiError("数据文件中没有配置标的的有效行情")
        available_symbols = sorted({bar.symbol for bar in bars})
        return {
            "symbols": available_symbols,
            "date_min": min(bar.datetime for bar in bars).date().isoformat(),
            "date_max": max(bar.datetime for bar in bars).date().isoformat(),
            "bar_count": len(bars),
            "data_file": self.data_path.name,
            "config": copy.deepcopy(self.config),
            "strategies": [
                {"id": "dual_moving_average", "name": "双均线趋势"},
                {"id": "rsi", "name": "RSI 反转"},
                {"id": "macd", "name": "MACD 趋势"},
                {"id": "bollinger", "name": "布林带均值回归"},
            ],
            "rules": {
                "bar_frequency": self.config["market"]["bar_frequency"],
                "execution": "当日收盘产生信号，下一交易日开盘成交",
                "lot_size": self.config["market"]["lot_size"],
            },
        }

    def _bars_for(self, request: dict[str, Any]) -> tuple[str, list[Any]]:
        allowed = set(self.config["market"]["symbols"])
        symbol = str(request.get("symbol", next(iter(allowed))))
        if symbol not in allowed:
            raise ApiError("标的不在配置允许范围内")
        start = _date(request.get("start"), "开始")
        end = _date(request.get("end"), "结束")
        if start and end and start > end:
            raise ApiError("开始日期不能晚于结束日期")
        bars = self.data_service.get_bars([symbol], start, end)
        if len(bars) < 2:
            raise ApiError("所选区间有效行情不足，请扩大日期范围")
        return symbol, bars

    def run_backtest(self, request: dict[str, Any]) -> dict[str, Any]:
        symbol, bars = self._bars_for(request)
        effective_config = build_request_config(self.config, request)
        try:
            engine = build_backtest_engine(effective_config)
            result = engine.run(bars)
        except ValueError as exc:
            raise ApiError(_factory_error_message(exc)) from exc
        initial_equity = float(result.metrics["initial_equity"])
        first_close = bars[0].close
        benchmark = [
            {
                "datetime": bar.datetime.isoformat(),
                "total_equity": initial_equity * bar.close / first_close,
            }
            for bar in bars
        ]
        rejected = [order for order in result.orders if order.status.value == "REJECTED"]
        return {
            "result": _jsonable(result),
            "benchmark_curve": benchmark,
            "summary": {
                "symbol": symbol,
                "start": bars[0].datetime.date().isoformat(),
                "end": bars[-1].datetime.date().isoformat(),
                "bar_count": len(bars),
                "snapshot_id": snapshot_id(bars),
                "rejected_order_count": len(rejected),
                "data_warnings": detect_anomalies(bars),
                "benchmark_name": f"{symbol} 买入并持有（收盘价）",
                "benchmark_return": bars[-1].close / first_close - 1,
            },
        }

    def start_simulation(self, request: dict[str, Any]) -> dict[str, Any]:
        symbol, bars = self._bars_for(request)
        components = build_components(self.config, request)
        components.pop("annual_trading_days")
        with self._lock:
            self._simulation = {
                "symbol": symbol,
                "bars": bars,
                "index": 0,
                "engine": SimulationEngine(**components),
                "snapshot_id": snapshot_id(bars),
            }
            return self._simulation_state()

    def step_simulation(self) -> dict[str, Any]:
        with self._lock:
            if self._simulation is None:
                raise ApiError("请先启动模拟回放")
            session = self._simulation
            if session["index"] < len(session["bars"]):
                bar = session["bars"][session["index"]]
                session["engine"].on_bar(bar)
                session["index"] += 1
            return self._simulation_state()

    def _simulation_state(self) -> dict[str, Any]:
        if self._simulation is None:
            return {"running": False}
        session = self._simulation
        engine = session["engine"]
        index = session["index"]
        total = len(session["bars"])
        current_bar = session["bars"][index - 1] if index else None
        return {
            "running": index < total,
            "complete": index >= total,
            "index": index,
            "total": total,
            "progress": index / total,
            "symbol": session["symbol"],
            "current_date": current_bar.datetime.isoformat() if current_bar else None,
            "current_close": current_bar.close if current_bar else None,
            "snapshot_id": session["snapshot_id"],
            "account": _jsonable(engine.account.snapshot()),
            "orders": _jsonable(engine.oms.orders[-20:]),
            "trades": _jsonable(engine.account.trades[-20:]),
        }


def make_handler(application: QuantDemoApplication) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "QuantDemo/0.1"

        def log_message(self, message: str, *args: object) -> None:
            print(f"[web] {self.address_string()} - {message % args}")

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/api/bootstrap":
                self._api(application.bootstrap)
                return
            if path == "/api/health":
                self._json({"status": "ok"})
                return
            if path in ("/", "/index.html"):
                self._file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
                return
            static_files = {
                "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                "/styles.css": ("styles.css", "text/css; charset=utf-8"),
            }
            if path in static_files:
                name, content_type = static_files[path]
                self._file(STATIC_DIR / name, content_type)
                return
            self._json({"error": "页面不存在"}, HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            routes = {
                "/api/backtest": application.run_backtest,
                "/api/simulation/start": application.start_simulation,
                "/api/simulation/step": lambda _: application.step_simulation(),
            }
            action = routes.get(path)
            if action is None:
                self._json({"error": "接口不存在"}, HTTPStatus.NOT_FOUND)
                return
            self._api(lambda: action(self._request_json()))

        def _request_json(self) -> dict[str, Any]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise ApiError("请求长度无效") from exc
            if length < 0 or length > 64 * 1024:
                raise ApiError("请求内容过大")
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise ApiError("请求不是有效 JSON") from exc
            if not isinstance(payload, dict):
                raise ApiError("请求 JSON 必须是对象")
            return payload

        def _api(self, action: Any) -> None:
            try:
                self._json(action())
            except (ApiError, FileNotFoundError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except Exception as exc:  # 最外层错误边界，避免把堆栈暴露给页面。
                print(f"[web] internal error: {type(exc).__name__}: {exc}")
                self._json(
                    {"error": "系统暂时无法完成请求，请检查服务端日志"},
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )

        def _json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(_jsonable(payload), ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _file(self, path: Path, content_type: str) -> None:
            try:
                body = path.read_bytes()
            except FileNotFoundError:
                self._json({"error": "静态资源不存在"}, HTTPStatus.NOT_FOUND)
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)

    return Handler


def create_server(
    application: QuantDemoApplication, host: str = "127.0.0.1", port: int = 8000
) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(application))


def main() -> None:
    parser = argparse.ArgumentParser(description="启动智能量化交易系统 Web Demo")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="团队共享配置路径")
    parser.add_argument("--data", default=str(DEFAULT_DATA), help="日 K CSV 路径")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    application = QuantDemoApplication(args.config, args.data)
    server = create_server(application, args.host, args.port)
    print(f"Quant Demo 已启动：http://{args.host}:{args.port}")
    print(f"数据文件：{application.data_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止服务…")
    finally:
        server.server_close()
