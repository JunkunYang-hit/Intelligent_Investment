"""命令行入口：读取配置和 CSV，组装组件并输出回测指标。"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from quant_demo.data import CsvDataService
from quant_demo.modes import BacktestEngine, build_backtest_engine


def build_engine(config: dict[str, object]) -> BacktestEngine:
    return build_backtest_engine(config)


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
