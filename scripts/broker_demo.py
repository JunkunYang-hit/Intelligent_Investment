"""端到端交易演示：真实行情 → 动量信号 → 券商网关下单 → 成交 → 持仓。

用法：
    python scripts/broker_demo.py                     # 模拟撮合 + 真实行情价（默认，开箱即用）
    python scripts/broker_demo.py --symbols 600900.SH 601899.SH
    python scripts/broker_demo.py --gateway qmt --qmt-path "C:/QMT/userdata_mini" --account 资金账号
    python scripts/broker_demo.py --gateway futu --market HK --simulate

演示链路说明（诚实边界）：
  - 行情：腾讯实时接口，真实盘口价格（无需账户）；
  - 信号：股票池五年日K的动量排名（data.selection.momentum_rank）；
  - 撮合：默认 PaperBrokerGateway（本地模拟成交，价格用真实现价）；
  - 券商：--gateway qmt/futu 切换真实券商通道，未部署客户端时给出诊断
    而不是静默失败（接入步骤见 src/quant_demo/brokerage/README.md）。
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from quant_demo.brokerage import PaperBrokerGateway  # noqa: E402
from quant_demo.data import CsvDataService, momentum_rank  # noqa: E402
from quant_demo.data.realtime import get_realtime_quotes  # noqa: E402
from quant_demo.models import OrderRequest, Side  # noqa: E402

DEFAULT_SYMBOLS = ["600900.SH", "601899.SH", "600036.SH", "600519.SH",
                   "601318.SH", "000651.SZ", "600276.SH"]
LOT = 100  # A股一手100股


def build_gateway(args) -> PaperBrokerGateway:
    if args.gateway == "paper":
        return PaperBrokerGateway(initial_cash=args.cash)
    if args.gateway == "qmt":
        from quant_demo.brokerage import QMTGateway
        from quant_demo.brokerage.qmt_gateway import qmt_self_test
        report = qmt_self_test(args.qmt_path)
        print("[QMT 自检]", report)
        if not report["client_running"]:
            print("→ QMT 环境未就绪，诊断如上；先运行 paper 模式验证策略逻辑。")
            sys.exit(2)
        return QMTGateway(qmt_userdata_path=args.qmt_path, account_id=args.account)
    if args.gateway == "futu":
        from quant_demo.brokerage import FutuGateway
        gw = FutuGateway(market=args.market, simulate=not args.real)
        if not gw.connect():
            print("→ 富途 OpenD 未运行或账户未配置（需开户+运行OpenD）；先运行 paper 模式。")
            sys.exit(2)
        return gw
    raise ValueError(f"未知网关: {args.gateway}")


def main() -> None:
    parser = argparse.ArgumentParser(description="真实行情驱动的端到端交易演示")
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    parser.add_argument("--gateway", choices=["paper", "qmt", "futu"], default="paper")
    parser.add_argument("--cash", type=float, default=1_000_000.0)
    parser.add_argument("--top-k", type=int, default=2, help="动量选股取前K只")
    parser.add_argument("--weight", type=float, default=0.20, help="单标的目标仓位")
    parser.add_argument("--qmt-path", default="", help="QMT userdata_mini 路径")
    parser.add_argument("--account", default="", help="券商资金账号")
    parser.add_argument("--market", default="HK", choices=["HK", "US"], help="富通市场")
    parser.add_argument("--real", action="store_true", help="富途实盘（默认模拟盘）")
    args = parser.parse_args()

    print("=" * 62)
    print("端到端交易演示：真实行情 → 信号 → 网关下单 → 成交 → 持仓")
    print("=" * 62)

    # ── 1. 真实行情 ──────────────────────────────────────────────
    print(f"\n[1/5] 获取实时行情（腾讯接口，真实盘口）...")
    quotes = get_realtime_quotes(args.symbols)
    if not quotes:
        print("  ✗ 实时行情不可用（非交易时段也可能取到最新收盘价，请检查网络）")
        sys.exit(1)
    for sym, q in quotes.items():
        print(f"  {sym} {q.name:<6} 现价 {q.price:<8} 昨收 {q.pre_close:<8} {q.time}")

    # ── 2. 动量信号（基于自有五年数据） ─────────────────────────
    print(f"\n[2/5] 动量选股（股票池五年日K，取前{args.top_k}）...")
    svc = CsvDataService(REPO_ROOT / "examples" / "stocks_5y.csv")
    bars = svc.get_bars(args.symbols)
    as_of = max(b.datetime for b in bars)
    ranked = momentum_rank(bars, as_of=as_of, lookback=60, top_k=args.top_k)
    for sym, score in ranked:
        print(f"  {sym}  60日动量 {score:+.1%}")

    # ── 3. 网关连接 ─────────────────────────────────────────────
    print(f"\n[3/5] 连接交易网关（{args.gateway}）...")
    gw = build_gateway(args)
    if not gw.connect():
        print("  ✗ 网关连接失败")
        sys.exit(2)
    print(f"  ✓ 已连接 {gw.name} 网关，可用资金 {gw.query_cash():,.0f}")

    # ── 4. 下单（信号标的 × 目标仓位，按手取整） ────────────────
    print(f"\n[4/5] 下单执行（单标的仓位 {args.weight:.0%}，限价=实时价）...")
    for sym, _score in ranked:
        if sym not in quotes:
            continue
        price = quotes[sym].price
        budget = gw.query_cash() * args.weight
        lots = int(budget / (price * LOT))
        if lots <= 0:
            print(f"  - {sym} 资金不足一手，跳过")
            continue
        qty = lots * LOT
        req = OrderRequest(sym, Side.BUY, qty, datetime.now(), reason="动量信号演示")
        try:
            oid = gw.place_order(req, order_type="limit", price=price)
            order = gw.query_order(oid)
            status = order.status.value if order else "UNKNOWN"
            print(f"  → {sym} 买入 {qty} 股 @ {price}  [{oid}] {status}")
        except Exception as e:
            print(f"  → {sym} 下单失败: {e}")

    # ── 5. 账户状态 ─────────────────────────────────────────────
    print(f"\n[5/5] 账户状态")
    print(f"  可用资金: {gw.query_cash():>12,.2f}")
    positions = gw.query_positions()
    if positions:
        print(f"  {'标的':<12}{'数量':>8}{'成本':>10}{'现价':>10}{'浮动盈亏':>12}")
        for p in positions:
            pnl = p.unrealized_pnl
            print(f"  {p.symbol:<12}{p.quantity:>8}{p.average_cost:>10.3f}"
                  f"{p.last_price:>10.3f}{pnl:>12,.2f}")
    else:
        print("  （无持仓：可能全部被风控/资金检查拒绝，见上方下单日志）")
    gw.disconnect()
    print("\n提示：paper 网关为本地模拟撮合（真实价格）；接入 QMT/富途实盘的步骤")
    print("      见 src/quant_demo/brokerage/README.md。")


if __name__ == "__main__":
    main()
