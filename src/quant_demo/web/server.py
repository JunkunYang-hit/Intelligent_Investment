"""零运行时依赖的 Web 服务，负责参数校验、调用交易内核和结果序列化。"""

from __future__ import annotations

import argparse
import copy
import json
import math
import threading
import time
from dataclasses import asdict
from datetime import datetime, time as clock_time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from quant_demo.data import (
    CsvDataService,
    detect_anomalies,
    get_realtime_quotes,
    snapshot_id,
)
from quant_demo.brokerage import BrokerGateway, FutuGateway, PaperBrokerGateway
from quant_demo.models import OrderRequest, Side
from quant_demo.modes import build_backtest_engine
from quant_demo.strategy import (
    BollingerBandsStrategy,
    DualMovingAverageStrategy,
    MACDStrategy,
    RSIStrategy,
    Strategy,
)
from quant_demo.web.history import BacktestHistoryStore
from quant_demo.web.ai_analysis import call_deepseek

STATIC_DIR = Path(__file__).with_name("static")
DEFAULT_CONFIG = Path("config/demo.json")
DEFAULT_DATA = Path("examples/stocks_5y.csv")


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


def configured_lot_size(config: dict[str, Any], symbol: str) -> int:
    """读取标的专用交易单位；未单独配置时使用市场默认值。"""
    market = config["market"]
    return int(market.get("lot_sizes", {}).get(symbol, market["lot_size"]))


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
    symbol = str(request.get("symbol", config["market"]["symbols"][0]))
    config["market"]["lot_size"] = configured_lot_size(base_config, symbol)
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

    def __init__(
        self,
        config_path: str | Path,
        data_path: str | Path,
        history_dir: str | Path | None = None,
        enable_realtime: bool = False,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.config_path = Path(config_path).resolve()
        self.data_path = Path(data_path).resolve()
        self.config: dict[str, Any] = json.loads(
            self.config_path.read_text(encoding="utf-8")
        )
        self.data_service = CsvDataService(self.data_path)
        self.history_store = (
            BacktestHistoryStore(history_dir) if history_dir is not None else None
        )
        self.enable_realtime = enable_realtime
        self._now_provider = now_provider or (
            lambda: datetime.now(ZoneInfo("Asia/Shanghai"))
        )
        self._paper = PaperBrokerGateway(float(self.config["backtest"]["initial_cash"]))
        self._paper.connect()
        self._paper_order_ids: list[str] = []
        self._broker: BrokerGateway = self._paper
        self._broker_kind = "paper"
        self._broker_market = "A"
        self._broker_order_ids = self._paper_order_ids
        self._paper_market_meta = {
            "source": "本地历史日 K",
            "quote_time": None,
            "is_realtime": False,
        }
        self._lock = threading.Lock()

    def bootstrap(self) -> dict[str, Any]:
        symbols = list(self.config["market"]["symbols"])
        bars = self.data_service.get_bars(symbols)
        if not bars:
            raise ApiError("数据文件中没有配置标的的有效行情")
        available_set = {bar.symbol for bar in bars}
        # 保留配置中的业务顺序，让沪深300ETF继续作为默认大盘标的。
        available_symbols = [symbol for symbol in symbols if symbol in available_set]
        configured_names = self.config["market"].get("symbol_names", {})
        bars_by_symbol: dict[str, list[Any]] = {
            symbol: [bar for bar in bars if bar.symbol == symbol]
            for symbol in available_symbols
        }
        warnings = detect_anomalies(bars)
        return {
            "symbols": available_symbols,
            "symbol_names": {
                symbol: configured_names.get(symbol, symbol)
                for symbol in available_symbols
            },
            "lot_sizes": {
                symbol: configured_lot_size(self.config, symbol)
                for symbol in available_symbols
            },
            "date_min": min(bar.datetime for bar in bars).date().isoformat(),
            "date_max": max(bar.datetime for bar in bars).date().isoformat(),
            "bar_count": len(bars),
            "symbol_ranges": {
                symbol: {
                    "date_min": rows[0].datetime.date().isoformat(),
                    "date_max": rows[-1].datetime.date().isoformat(),
                    "bar_count": len(rows),
                }
                for symbol, rows in bars_by_symbol.items()
            },
            "data_quality": {
                "warning_count": len(warnings),
                "warnings": warnings[:20],
                "source": "腾讯行情接口前复权日 K（本地 CSV 快照）",
            },
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
                "realtime_enabled": self.enable_realtime,
            },
        }

    def market_snapshot(self, symbol: str) -> dict[str, Any]:
        """返回真实行情优先、历史日 K 兜底的分析快照。"""
        if symbol not in set(self.config["market"]["symbols"]):
            raise ApiError("标的不在配置允许范围内")
        bars = self.data_service.get_bars([symbol])
        if len(bars) < 2:
            raise ApiError("所选标的没有足够行情用于分析")
        closes = [bar.close for bar in bars]
        latest_bar = bars[-1]
        quote = None
        if self.enable_realtime:
            try:
                quote = get_realtime_quotes([symbol]).get(symbol)
            except (OSError, ValueError):
                quote = None

        def period_return(days: int) -> float | None:
            return closes[-1] / closes[-days - 1] - 1 if len(closes) > days else None

        recent_closes = closes[-120:]
        peak = recent_closes[0]
        max_drawdown = 0.0
        for close in recent_closes:
            peak = max(peak, close)
            max_drawdown = max(max_drawdown, 1 - close / peak)
        daily_returns = [
            closes[index] / closes[index - 1] - 1
            for index in range(max(1, len(closes) - 60), len(closes))
        ]
        mean_return = sum(daily_returns) / len(daily_returns)
        variance = sum((item - mean_return) ** 2 for item in daily_returns) / max(
            1, len(daily_returns) - 1
        )
        volumes = [bar.volume for bar in bars[-20:]]
        snapshot = {
            "symbol": symbol,
            "data_source": "腾讯行情接口" if quote else "本地历史日 K（实时行情不可用时兜底）",
            "is_realtime_quote": quote is not None,
            "quote_time": quote.time if quote else latest_bar.datetime.isoformat(),
            "name": (
                quote.name
                if quote
                else self.config["market"].get("symbol_names", {}).get(symbol)
            ),
            "price": quote.price if quote else latest_bar.close,
            "pre_close": quote.pre_close if quote else None,
            "open": quote.open if quote else latest_bar.open,
            "high": quote.high if quote else latest_bar.high,
            "low": quote.low if quote else latest_bar.low,
            "volume": quote.volume if quote else latest_bar.volume,
            "historical_last_date": latest_bar.datetime.date().isoformat(),
            "historical_last_close": latest_bar.close,
            "return_5d": period_return(5),
            "return_20d": period_return(20),
            "return_60d": period_return(60),
            "moving_average_20d": sum(closes[-20:]) / min(20, len(closes)),
            "moving_average_60d": sum(closes[-60:]) / min(60, len(closes)),
            "annualized_volatility_60d": math.sqrt(variance) * math.sqrt(252),
            "max_drawdown_120d": max_drawdown,
            "latest_volume_vs_20d_average": (
                latest_bar.volume / (sum(volumes) / len(volumes))
                if volumes and sum(volumes) > 0
                else None
            ),
            "limitations": "不含公司财务、估值、新闻、公告或资金流数据",
        }
        return snapshot

    def analyze_symbol(self, request: dict[str, Any]) -> dict[str, Any]:
        api_key = str(request.get("api_key", "")).strip()
        question = str(request.get("question", "")).strip()
        symbol = str(request.get("symbol", "")).strip()
        if not api_key or len(api_key) > 512:
            raise ApiError("请输入有效的 DeepSeek API Key")
        if not question:
            raise ApiError("请输入想分析的问题")
        if len(question) > 2000:
            raise ApiError("问题不能超过 2000 个字符")
        context = self.market_snapshot(symbol)
        try:
            result = call_deepseek(api_key, symbol, question, context)
        except ConnectionError as exc:
            raise ApiError(str(exc)) from exc
        return {**result, "symbol": symbol, "market_context": context}

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
        started_at = time.perf_counter()
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
        report = {
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
                "lot_size": configured_lot_size(self.config, symbol),
                "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
            },
        }
        if self.history_store is not None:
            report = self.history_store.save(copy.deepcopy(request), report)
        return report

    def list_backtests(self) -> dict[str, Any]:
        if self.history_store is None:
            return {"items": [], "persistence_enabled": False}
        return {
            "items": self.history_store.list(),
            "persistence_enabled": True,
            "directory": str(self.history_store.directory),
        }

    def get_backtest(self, history_id: str) -> dict[str, Any]:
        if self.history_store is None:
            raise ApiError("回测历史保存功能未启用")
        try:
            report = self.history_store.get(history_id)
        except ValueError as exc:
            raise ApiError(str(exc)) from exc
        if report is None:
            raise ApiError("找不到这条回测历史")
        return report

    def delete_backtest(self, history_id: str) -> dict[str, Any]:
        if self.history_store is None:
            raise ApiError("回测历史保存功能未启用")
        try:
            deleted = self.history_store.delete(history_id)
        except ValueError as exc:
            raise ApiError(str(exc)) from exc
        if not deleted:
            raise ApiError("找不到这条回测历史")
        return {"deleted": True, "id": history_id}

    def reset_paper_broker(self, request: dict[str, Any]) -> dict[str, Any]:
        """创建全新的本地模拟券商账户，并注入各标的最新收盘价。"""
        if self._broker_kind != "paper":
            raise ApiError("富途模拟账户不能由本系统重置；请在富途模拟盘中管理资金")
        initial_cash = _number(
            request,
            "initial_cash",
            float(self.config["backtest"]["initial_cash"]),
            minimum=1,
        )
        with self._lock:
            self._paper = PaperBrokerGateway(initial_cash)
            self._paper.connect()
            self._paper_order_ids = []
            self._broker = self._paper
            self._broker_order_ids = self._paper_order_ids
            self._inject_latest_prices()
            return self._broker_state()

    def connect_broker(self, request: dict[str, Any]) -> dict[str, Any]:
        """切换交易网关；连接参数只保存在当前进程内存中。"""
        gateway = str(request.get("gateway", "paper")).strip().lower()
        if gateway == "paper":
            initial_cash = _number(
                request,
                "initial_cash",
                float(self.config["backtest"]["initial_cash"]),
                minimum=1,
            )
            candidate: BrokerGateway = PaperBrokerGateway(initial_cash)
            market = "A"
        elif gateway == "futu":
            host = str(request.get("host", "127.0.0.1")).strip()
            if not host or len(host) > 255:
                raise ApiError("OpenD 主机地址不能为空或过长")
            port = _integer(request, "port", 11111)
            if port > 65535:
                raise ApiError("OpenD 端口不能超过 65535")
            market = str(request.get("market", "HK")).strip().upper()
            if market not in {"HK", "US"}:
                raise ApiError("富途模拟盘市场只能选择港股 HK 或美股 US")
            account_id = str(request.get("account_id", "")).strip() or None
            try:
                candidate = FutuGateway(
                    market=market,
                    host=host,
                    port=port,
                    simulate=True,
                    account_id=account_id,
                )
            except (TypeError, ValueError) as exc:
                raise ApiError(str(exc)) from exc
        else:
            raise ApiError("目前网页只支持本地模拟和富途模拟盘")

        try:
            connected = candidate.connect()
        except ModuleNotFoundError as exc:
            raise ApiError('缺少富途 SDK，请先执行 pip install -e ".[dev,futu]"') from exc
        except Exception as exc:
            raise ApiError(f"券商连接失败：{exc}") from exc
        if not connected:
            if gateway == "futu":
                raise ApiError("无法连接富途 OpenD，请确认 OpenD 已启动、已登录且主机端口正确")
            raise ApiError("本地模拟券商初始化失败")
        try:
            candidate.query_cash()
            candidate.query_positions()
        except Exception as exc:
            candidate.disconnect()
            raise ApiError(f"券商已响应，但模拟账户读取失败：{exc}") from exc

        with self._lock:
            previous = self._broker
            self._broker = candidate
            self._broker_kind = gateway
            self._broker_market = market
            self._broker_order_ids = []
            if gateway == "paper":
                self._paper = candidate  # type: ignore[assignment]
                self._paper_order_ids = self._broker_order_ids
                self._inject_latest_prices()
            if previous is not candidate:
                try:
                    previous.disconnect()
                except Exception:
                    pass
            return self._broker_state()

    def paper_broker_state(self) -> dict[str, Any]:
        with self._lock:
            if self._broker_kind == "paper":
                self._inject_latest_prices()
            return self._broker_state()

    def place_paper_order(self, request: dict[str, Any]) -> dict[str, Any]:
        symbol = str(request.get("symbol", ""))
        if self._broker_kind == "paper":
            if symbol not in set(self.config["market"]["symbols"]):
                raise ApiError("本地模拟标的不在配置允许范围内")
        else:
            expected_suffix = f".{self._broker_market}"
            if not symbol.upper().endswith(expected_suffix):
                example = "0700.HK" if self._broker_market == "HK" else "AAPL.US"
                raise ApiError(f"当前市场代码必须以 {expected_suffix} 结尾，例如 {example}")
        try:
            side = Side(str(request.get("side", "BUY")).upper())
        except ValueError as exc:
            raise ApiError("交易方向只能是 BUY 或 SELL") from exc
        quantity = _integer(request, "quantity", 100)
        if self._broker_kind == "paper":
            lot_size = configured_lot_size(self.config, symbol)
            if quantity % lot_size:
                raise ApiError(f"数量必须是每手 {lot_size} 股的整数倍")
        order_type = str(request.get("order_type", "market")).lower()
        if order_type not in {"market", "limit"}:
            raise ApiError("订单类型只能是 market 或 limit")
        price = None
        if order_type == "limit":
            price = _number(request, "price", 0, minimum=0.001)

        snapshot = None
        if self._broker_kind == "paper":
            snapshot = self.market_snapshot(symbol)
            self._require_a_share_trading_session(snapshot)
        with self._lock:
            if snapshot is not None:
                self._paper.set_last_close(symbol, float(snapshot["price"]))
            try:
                broker_id = self._broker.place_order(
                    OrderRequest(symbol, side, quantity, datetime.now(), "Web 模拟下单"),
                    order_type,
                    price,
                )
                self._broker_order_ids.append(broker_id)
                result = self._broker_state()
                submitted = self._broker.query_order(broker_id)
                result["submitted_order"] = _jsonable(submitted) if submitted else {
                    "order_id": broker_id,
                    "symbol": symbol,
                    "side": side.value,
                    "quantity": quantity,
                    "created_at": datetime.now().isoformat(),
                    "status": "CREATED",
                    "price": price,
                    "reject_reason": None,
                }
            except Exception as exc:
                raise ApiError(f"券商下单失败：{exc}") from exc
            return result

    def _require_a_share_trading_session(self, snapshot: dict[str, Any]) -> None:
        is_open, reason = self._a_share_trading_status(snapshot.get("quote_time"))
        if not is_open:
            raise ApiError(reason)
        if self.enable_realtime and not snapshot.get("is_realtime_quote"):
            raise ApiError("联网行情不可用，为避免按历史价格成交，本次模拟下单已拒绝")

    def _a_share_trading_status(self, quote_time: str | None) -> tuple[bool, str]:
        now = self._now_provider()
        shanghai = ZoneInfo("Asia/Shanghai")
        if now.tzinfo is None:
            now = now.replace(tzinfo=shanghai)
        else:
            now = now.astimezone(shanghai)
        if now.weekday() >= 5:
            return False, "当前是周末，A 股模拟券商不接受订单"
        current = now.time().replace(tzinfo=None)
        in_session = (
            clock_time(9, 30) <= current <= clock_time(11, 30)
            or clock_time(13, 0) <= current <= clock_time(15, 0)
        )
        if not in_session:
            return False, "当前不在 A 股交易时段（09:30-11:30、13:00-15:00）"
        if self.enable_realtime:
            if not quote_time or len(quote_time) < 8 or not quote_time[:8].isdigit():
                return False, "无法确认联网行情日期，模拟下单已暂停"
            quote_date = datetime.strptime(quote_time[:8], "%Y%m%d").date()
            if quote_date != now.date():
                return False, "行情不是今天的数据，可能处于节假日或行情已停止更新"
        return True, "A 股交易时段内"

    def _inject_latest_prices(self) -> None:
        symbols = list(self.config["market"]["symbols"])
        latest: dict[str, float] = {}
        for bar in self.data_service.get_bars(symbols):
            latest[bar.symbol] = bar.close
        quotes = {}
        if self.enable_realtime:
            try:
                quotes = get_realtime_quotes(symbols)
            except (OSError, ValueError):
                quotes = {}
        for symbol, price in latest.items():
            self._paper.set_last_close(symbol, quotes.get(symbol).price if symbol in quotes else price)
        quote_times = [quote.time for quote in quotes.values()]
        self._paper_market_meta = {
            "source": "腾讯行情接口" if quotes else "本地历史日 K",
            "quote_time": max(quote_times) if quote_times else None,
            "is_realtime": bool(quotes),
        }

    def _broker_state(self) -> dict[str, Any]:
        try:
            positions = self._broker.query_positions()
            cash = self._broker.query_cash()
            orders = [self._broker.query_order(order_id) for order_id in self._broker_order_ids]
        except Exception as exc:
            raise ApiError(f"读取券商账户失败：{exc}") from exc
        market_value = sum(position.market_value for position in positions)
        position_rows = [
            {
                **_jsonable(position),
                "market_value": position.market_value,
                "unrealized_pnl": position.unrealized_pnl,
                "total_pnl": position.total_pnl,
            }
            for position in positions
        ]
        if self._broker_kind == "paper":
            session_open, session_message = self._a_share_trading_status(
                self._paper_market_meta.get("quote_time")
            )
            market_data = self._paper_market_meta
        else:
            session_open = True
            session_message = "富途 OpenD 已连接；交易时段、权限和订单有效性由富途模拟盘校验"
            market_data = {
                "source": f"富途 OpenD（{self._broker_market} 官方模拟盘）",
                "quote_time": None,
                "is_realtime": True,
            }
        return {
            "connected": True,
            "gateway": self._broker.name,
            "broker_market": self._broker_market,
            "is_external_simulation": self._broker_kind != "paper",
            "cash": cash,
            "market_value": market_value,
            "total_equity": cash + market_value,
            "positions": position_rows,
            "orders": _jsonable([order for order in orders if order is not None]),
            "market_data": market_data,
            "trading_session": {
                "is_open": session_open,
                "message": session_message,
            },
        }


def make_handler(application: QuantDemoApplication) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "QuantDemo/0.1"

        def log_message(self, message: str, *args: object) -> None:
            print(f"[web] {self.address_string()} - {message % args}")

        def do_GET(self) -> None:  # noqa: N802
            parsed_url = urlparse(self.path)
            path = parsed_url.path
            if path == "/api/bootstrap":
                self._api(application.bootstrap)
                return
            if path == "/api/health":
                self._json({"status": "ok"})
                return
            if path == "/api/broker/state":
                self._api(application.paper_broker_state)
                return
            if path == "/api/market/snapshot":
                symbol = parse_qs(parsed_url.query).get("symbol", [""])[0]
                self._api(lambda: application.market_snapshot(symbol))
                return
            if path == "/api/backtests":
                self._api(application.list_backtests)
                return
            if path.startswith("/api/backtests/"):
                history_id = path.removeprefix("/api/backtests/")
                self._api(lambda: application.get_backtest(history_id))
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
                "/api/broker/connect": application.connect_broker,
                "/api/broker/reset": application.reset_paper_broker,
                "/api/broker/order": application.place_paper_order,
                "/api/ai/analyze": application.analyze_symbol,
            }
            action = routes.get(path)
            if action is None:
                self._json({"error": "接口不存在"}, HTTPStatus.NOT_FOUND)
                return
            self._api(lambda: action(self._request_json()))

        def do_DELETE(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path.startswith("/api/backtests/"):
                history_id = path.removeprefix("/api/backtests/")
                self._api(lambda: application.delete_backtest(history_id))
                return
            self._json({"error": "接口不存在"}, HTTPStatus.NOT_FOUND)

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
    parser.add_argument(
        "--history-dir",
        default=".quant_demo/backtests",
        help="回测历史保存目录",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    application = QuantDemoApplication(
        args.config,
        args.data,
        history_dir=args.history_dir,
        enable_realtime=True,
    )
    server = create_server(application, args.host, args.port)
    print(f"Quant Demo 已启动：http://{args.host}:{args.port}")
    print(f"数据文件：{application.data_path}")
    print(f"回测历史：{application.history_store.directory}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止服务…")
    finally:
        server.server_close()
