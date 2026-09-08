"""命令行入口：读取配置和 CSV，组装组件并输出回测指标。"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from quant_demo.data import CsvDataService
from quant_demo.modes import BacktestEngine
from quant_demo.strategy import DualMovingAverageStrategy
from quant_demo.trading import (
    Account,
    BrokerSimulator,
    OrderManagementSystem,
    RiskManager,
    TargetWeightSizer,
)


def build_engine(config: dict[str, object]) -> BacktestEngine:
    market = config["market"]
    backtest = config["backtest"]
    strategy = config["strategy"]
    risk = config["risk"]
    assert isinstance(market, dict) and isinstance(backtest, dict)
    assert isinstance(strategy, dict) and isinstance(risk, dict)
    return BacktestEngine(
        strategy=DualMovingAverageStrategy(
            int(strategy["short_window"]), int(strategy["long_window"])
        ),
        account=Account(float(backtest["initial_cash"])),
        sizer=TargetWeightSizer(float(strategy["target_weight"]), int(market["lot_size"])),
        risk=RiskManager(
            float(risk["max_order_value_ratio"]),
            float(risk["max_symbol_weight"]),
            int(market["lot_size"]),
        ),
        oms=OrderManagementSystem(),
        broker=BrokerSimulator(
            float(backtest["commission_rate"]),
            float(backtest["minimum_commission"]),
            float(backtest["sell_stamp_duty_rate"]),
            float(backtest["slippage_bps"]),
        ),
        annual_trading_days=int(backtest["annual_trading_days"]),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="运行低频大盘策略回测")
    parser.add_argument("--config", default="config/demo.json")
    parser.add_argument("--data", required=True, help="日 K CSV 路径")
    parser.add_argument("--start")
    parser.add_argument("--end")
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    symbols = config["market"]["symbols"]
    bars = CsvDataService(args.data).get_bars(
        symbols,
        datetime.fromisoformat(args.start) if args.start else None,
        datetime.fromisoformat(args.end) if args.end else None,
    )
    result = build_engine(config).run(bars)
    print(json.dumps(result.metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
