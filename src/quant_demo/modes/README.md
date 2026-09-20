# Backtest Modes Module（回测与运行模式模块）

负责人：C（Backtest / 回测与交易编排模块）。本目录负责历史回测的时间推进、模块编排，以及持续模拟模式的运行入口。

## 1. Module Overview

C 模块把已经清洗并标准化的市场 Bar 按时间重放：

```text
Market Bars
  -> execute pending orders at next open
  -> Account.apply_trade
  -> mark portfolio at close
  -> Strategy.on_bar
  -> sizing / risk / OMS
  -> wait for the symbol's next Bar
```

C 模块负责：

- 按时间推进历史行情；
- 保证策略只看到当前及历史 Bar；
- 保证收盘信号只能在下一根对应标的 Bar 开盘成交；
- 编排 Strategy、Sizer、Risk、OMS、Broker、Account 和 Performance；
- 维护待成交订单；
- 返回 `BacktestResult`；
- 提供内置策略的配置适配入口。

C 模块不负责：

- 下载、清洗、复权或修复行情；
- 计算 RSI、MACD、均线或布林带；
- 修改策略信号；
- 绕过 `Account.apply_trade()` 修改现金和持仓；
- 定义绩效指标公式；
- 实现 Web 页面、权限、任务调度或实盘网关。

当前 C 模块已经可以通过命令行和 Web 回测入口运行。命令行入口保留
`main.build_engine(config)` 兼容接口，但实际由本模块的
`build_backtest_engine(config)` 负责组装组件；Web 的 `/api/backtest` 也使用
同一个 C 工厂。这样策略选择、账户初始资金、费用和风控参数不会在入口层重复实现。

## 2. Files

```text
modes/
├── backtest.py    # 历史回测时间推进和结果汇总
├── factory.py     # 配置到策略及独立 Engine 的白名单适配
├── simulation.py  # 逐 Bar 持续模拟模式
├── __init__.py    # 公共接口导出
└── README.md      # 本文档
```

OMS 和 Broker 也属于 C 的交易内核职责，但位于 `quant_demo/trading/`：

```text
trading/oms.py
trading/broker.py
```

## 3. Public Interfaces

### 3.1 Direct construction

原有构造方式保持有效：

```python
engine = BacktestEngine(
    strategy=strategy,
    account=account,
    sizer=sizer,
    risk=risk,
    oms=oms,
    broker=broker,
)

result = engine.run(bars)
```

适用于单元测试、依赖注入和调用方自行组装组件。

### 3.2 Strategy configuration adapter

`build_strategy()` 根据白名单名称构造策略，并返回解析后的规范名称和参数：

```python
from quant_demo.modes import build_strategy

selection = build_strategy({
    "name": "rsi",
    "target_weight": 0.2,
    "period": 14,
    "oversold": 30,
    "overbought": 70,
})

strategy = selection.strategy
parameters = selection.parameters
```

支持的名称：

```text
dual_moving_average
rsi
macd
bollinger_bands
```

`bollinger` 作为 `bollinger_bands` 的兼容别名。未知策略或拼错的参数字段会立即抛出 `ValueError`，不会动态导入任意类。

### 3.3 Configured Engine construction

`build_backtest_engine()` 从完整配置创建相互隔离的 Engine：

```python
from quant_demo.modes import build_backtest_engine

engine = build_backtest_engine(config)
result = engine.run(bars)
```

每次调用都会创建新的：

- Strategy；
- Account；
- TargetWeightSizer；
- RiskManager；
- OMS；
- BrokerSimulator；
- BacktestEngine。

不要复用已经运行过的 Engine。

### 3.4 Simulation construction

持续模拟模式按 Bar 推进，不接收完整历史列表：

```python
from quant_demo.modes import SimulationEngine

engine = SimulationEngine(
    strategy=strategy,
    account=account,
    sizer=sizer,
    risk=risk,
    oms=oms,
    broker=broker,
)
snapshot = engine.on_bar(bar)
```

`SimulationEngine.on_bar()` 每次处理一根已完成的 Bar，先撮合该标的此前产生的
待成交订单，再更新收盘估值、追加 history、调用策略并返回账户快照。它与历史
回测共享 Strategy、Sizer、Risk、OMS、Broker 和 Account 的交易规则，但不会返回
完整的 `BacktestResult`。

## 4. Strategy Configuration

所有策略共享 `name` 和 `target_weight`。算法参数不填写时使用策略模块 README 中声明的默认值。

### Dual moving average

```json
{
  "name": "dual_moving_average",
  "short_window": 5,
  "long_window": 20,
  "target_weight": 0.2
}
```

### RSI

```json
{
  "name": "rsi",
  "period": 14,
  "oversold": 30,
  "overbought": 70,
  "target_weight": 0.2
}
```

### MACD

```json
{
  "name": "macd",
  "fast_period": 12,
  "slow_period": 26,
  "signal_period": 9,
  "target_weight": 0.2
}
```

### Bollinger bands

```json
{
  "name": "bollinger_bands",
  "period": 20,
  "std_multiplier": 2.0,
  "target_weight": 0.2
}
```

策略的算法和参数含义见 [`strategy/README.md`](../strategy/README.md)。C 只解析白名单配置并把实例交给回测引擎，不实现指标逻辑。

## 5. Timing Contract

每个回测时间点遵循：

```text
T 日开盘
  -> 撮合此前为该标的创建的订单
  -> Account.apply_trade

T 日收盘
  -> 更新所有标的最新 close
  -> Account.mark_to_market
  -> 将当前 Bar 加入该标的 history
  -> Strategy.on_bar(bar, history)
  -> sizing / risk / OMS
  -> 通过的订单等待下一根对应标的 Bar
```

调用策略时必须满足：

```python
history[bar.symbol][-1] == bar
```

预热期由策略处理。策略返回 `None` 时 C 不创建订单，也不把它记录成拒单。

## 6. Input Rules

`BacktestEngine.run(bars)` 要求：

- 输入至少包含一根 Bar；
- `Bar.datetime` 是 `datetime`；
- symbol 非空；
- 不混用带时区和不带时区的 datetime；
- `(datetime, symbol)` 唯一；
- 日线模式下同一自然日使用统一时间戳。

输入可以无序，Engine 会按 `(datetime, symbol)` 排序。数据错误立即抛出 `ValueError`。

## 7. Result and Reproducibility

`BacktestResult` 包含：

- `metrics`：绩效指标；
- `equity_curve`：组合净值曲线；
- `trades`：成功过账的成交；
- `orders`：全部订单及状态；
- `metadata`：执行和复现信息。

通过配置适配器构造时，metadata 额外包含：

```text
strategy               Python 策略类名，保留原字段兼容
strategy_name          配置使用的规范策略名
strategy_parameters    已解析且补齐默认值的算法参数
```

还会记录 Bar 数、标的、区间、初始资金、年交易日数量和订单状态汇总。

## 8. Error Semantics

- 行情、配置或非法状态属于程序/输入错误，抛出异常；
- 风控不通过属于业务结果，订单记为 `REJECTED`；
- 账户过账失败同样记为 `REJECTED`，回测继续；
- 最后一根 Bar 后产生且没有下一根行情的订单保持 `CREATED`；
- 一个 `BacktestEngine` 只能运行一次，再次调用抛出 `RuntimeError`。

### 8.1 Optional multi-symbol portfolio constraints

为了兼容既有单标的和多标的结果，以下组合约束默认关闭，只有在配置中显式开启
才会生效：

```json
{
  "backtest": {
    "reserve_cash": true
  },
  "risk": {
    "max_total_weight": 0.8
  }
}
```

- `reserve_cash=true`：创建买单时按当前收盘价、滑点和佣金估算成本，并从后续
  待成交订单的可用现金中预占；资金不足的订单在创建阶段标记为 `REJECTED`。
- `max_total_weight`：把当前持仓和已接受的待成交订单一起计入组合敞口，超过
  上限的订单标记为 `REJECTED`。取值范围为 `(0, 1]`。
- 同一标的的待成交订单按 `(created_at, order_id)` 排序；日 Bar 本身按
  `(datetime, symbol)` 排序，因此输入文件顺序不会影响成交顺序。

默认配置不设置这两个字段，仍采用原有逐订单风控和账户过账规则。持续模拟
模式目前不自动启用这些回测专用约束，以确保已有模拟结果保持不变。

## 9. End-to-end workflow

一次历史回测的完整数据流如下：

```text
CsvDataService / other MarketDataService
        -> list[Bar]
        -> build_backtest_engine(config)
        -> BacktestEngine.run(bars)
        -> Strategy signal
        -> TargetWeightSizer
        -> RiskManager
        -> OMS
        -> BrokerSimulator (next Bar open)
        -> Account.apply_trade / mark_to_market
        -> calculate_performance
        -> BacktestResult
```

当前结果可以被 CLI、Web 或测试调用方消费：

- CLI 输出 `result.metrics` 的 JSON；
- Web 回测额外生成买入并持有基准曲线、数据快照 ID 和异常提示；
- `BacktestResult` 保留净值、成交、订单和 metadata，便于审计和复现；
- 模拟模式逐 Bar 返回账户、订单和成交快照，不改变历史回测结果。

当前配置仍默认使用 `510300.SH` 的 A 股/ETF 日线数据。数据模块虽然已经提供
13 只 A 股及港美股数据和动量排名函数，但这些股票池和动态选股规则尚未自动
接入 C 的回测配置；使用它们前需要明确多标的资金、交易单位、市场币种和调仓
时序规则。

## 10. Testing

运行全部测试：

```bash
.venv/bin/pytest -q
```

C 模块重点验证：

- 下一根 Bar 开盘成交；
- 输入唯一性和时间一致性；
- Engine 状态隔离；
- OMS 合法状态迁移；
- Broker 撮合前置校验；
- 四种内置策略的白名单配置；
- 未知策略和拼错参数快速失败；
- 策略名称和参数进入 metadata；
- 每次工厂调用创建独立组件。
- 多标的待成交订单的确定性顺序；
- 可选现金预占和组合总仓位限制；
- 多标的资金不足时的拒单行为；
- CLI、Web 回测和模拟模式的兼容性。

## 11. Current Limitations

- 没有严格 A 股 T+1 可卖数量；
- 多订单资金预占和组合总仓位上限目前是可选项，默认关闭；
- 没有停牌、涨跌停、成交量限制和部分成交；
- 没有限价单、止损单和订单有效期；
- 没有完整 SignalEvent、批量参数实验和结果持久化；
- 没有策略生命周期回调。
- 尚未把 `data.selection.momentum_rank()` 接入动态调仓回测；
- 账户仍是单一现金余额，尚不支持港股/美股的多币种和汇率；
- `lot_size`、佣金、印花税和滑点仍以单一配置应用于整次回测；
- 尚未实现跨市场交易日历、时区和市场特定费用模型。

这些内容涉及其他模块或共享模型，应在团队确认接口后单独实施。
