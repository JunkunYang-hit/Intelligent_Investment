"""C 模块配置适配器：按白名单构造策略和独立回测 Engine。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Callable, Union

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

from .backtest import BacktestEngine


StrategyParameter = Union[int, float]


@dataclass(frozen=True)
class StrategySelection:
    """已解析的策略实例及其可复现配置。"""

    strategy: Strategy
    name: str
    parameters: dict[str, StrategyParameter]


def build_strategy(config: Mapping[str, object]) -> StrategySelection:
    """根据策略配置构造白名单中的内置策略。"""

    raw_name = config.get("name")
    if not isinstance(raw_name, str) or not raw_name.strip():
        raise ValueError("strategy.name 必须是非空字符串")
    name = raw_name.strip().lower()
    canonical_name = "bollinger_bands" if name == "bollinger" else name

    builders: dict[str, Callable[[Mapping[str, object]], StrategySelection]] = {
        "dual_moving_average": _build_dual_moving_average,
        "rsi": _build_rsi,
        "macd": _build_macd,
        "bollinger_bands": _build_bollinger_bands,
    }
    builder = builders.get(canonical_name)
    if builder is None:
        supported = ", ".join(sorted(builders))
        raise ValueError(f"不支持的策略 {raw_name!r}；可选值: {supported}")
    return builder(config)


def build_backtest_engine(config: Mapping[str, object]) -> BacktestEngine:
    """从完整配置创建一次性、状态隔离的回测 Engine。"""

    market = _section(config, "market")
    backtest = _section(config, "backtest")
    strategy_config = _section(config, "strategy")
    risk = _section(config, "risk")
    selection = build_strategy(strategy_config)

    lot_size = _as_int(market, "lot_size")
    return BacktestEngine(
        strategy=selection.strategy,
        account=Account(_as_float(backtest, "initial_cash")),
        sizer=TargetWeightSizer(_as_float(strategy_config, "target_weight"), lot_size),
        risk=RiskManager(
            _as_float(risk, "max_order_value_ratio"),
            _as_float(risk, "max_symbol_weight"),
            lot_size,
        ),
        oms=OrderManagementSystem(),
        broker=BrokerSimulator(
            _as_float(backtest, "commission_rate"),
            _as_float(backtest, "minimum_commission"),
            _as_float(backtest, "sell_stamp_duty_rate"),
            _as_float(backtest, "slippage_bps"),
        ),
        annual_trading_days=_as_int(backtest, "annual_trading_days"),
        strategy_name=selection.name,
        strategy_parameters=selection.parameters,
    )


def _build_dual_moving_average(config: Mapping[str, object]) -> StrategySelection:
    _reject_unknown_keys(config, {"name", "target_weight", "short_window", "long_window"})
    parameters: dict[str, StrategyParameter] = {
        "short_window": _as_int(config, "short_window", 5),
        "long_window": _as_int(config, "long_window", 20),
    }
    strategy = DualMovingAverageStrategy(
        short_window=int(parameters["short_window"]),
        long_window=int(parameters["long_window"]),
    )
    return StrategySelection(strategy, "dual_moving_average", parameters)


def _build_rsi(config: Mapping[str, object]) -> StrategySelection:
    _reject_unknown_keys(config, {"name", "target_weight", "period", "oversold", "overbought"})
    parameters: dict[str, StrategyParameter] = {
        "period": _as_int(config, "period", 14),
        "oversold": _as_float(config, "oversold", 30.0),
        "overbought": _as_float(config, "overbought", 70.0),
    }
    strategy = RSIStrategy(
        period=int(parameters["period"]),
        oversold=float(parameters["oversold"]),
        overbought=float(parameters["overbought"]),
    )
    return StrategySelection(strategy, "rsi", parameters)


def _build_macd(config: Mapping[str, object]) -> StrategySelection:
    _reject_unknown_keys(
        config,
        {"name", "target_weight", "fast_period", "slow_period", "signal_period"},
    )
    parameters: dict[str, StrategyParameter] = {
        "fast_period": _as_int(config, "fast_period", 12),
        "slow_period": _as_int(config, "slow_period", 26),
        "signal_period": _as_int(config, "signal_period", 9),
    }
    strategy = MACDStrategy(
        fast_period=int(parameters["fast_period"]),
        slow_period=int(parameters["slow_period"]),
        signal_period=int(parameters["signal_period"]),
    )
    return StrategySelection(strategy, "macd", parameters)


def _build_bollinger_bands(config: Mapping[str, object]) -> StrategySelection:
    _reject_unknown_keys(config, {"name", "target_weight", "period", "std_multiplier"})
    parameters: dict[str, StrategyParameter] = {
        "period": _as_int(config, "period", 20),
        "std_multiplier": _as_float(config, "std_multiplier", 2.0),
    }
    strategy = BollingerBandsStrategy(
        period=int(parameters["period"]),
        std_multiplier=float(parameters["std_multiplier"]),
    )
    return StrategySelection(strategy, "bollinger_bands", parameters)


def _section(config: Mapping[str, object], name: str) -> Mapping[str, object]:
    value = config.get(name)
    if not isinstance(value, Mapping):
        raise ValueError(f"配置项 {name} 必须是对象")
    return value


def _as_int(config: Mapping[str, object], key: str, default: int | None = None) -> int:
    value = config.get(key, default)
    if value is None or isinstance(value, bool):
        raise ValueError(f"配置项 {key} 必须是整数")
    try:
        converted = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"配置项 {key} 必须是整数") from exc
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"配置项 {key} 必须是整数")
    return converted


def _as_float(config: Mapping[str, object], key: str, default: float | None = None) -> float:
    value = config.get(key, default)
    if value is None or isinstance(value, bool):
        raise ValueError(f"配置项 {key} 必须是数字")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"配置项 {key} 必须是数字") from exc


def _reject_unknown_keys(config: Mapping[str, object], allowed: set[str]) -> None:
    unknown = sorted(set(config) - allowed)
    if unknown:
        raise ValueError(f"策略配置包含未知字段: {', '.join(unknown)}")
