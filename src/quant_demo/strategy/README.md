# Strategy Module（策略模块）

负责人：B（Strategy / 策略模块）。本目录是策略模块的完整交付内容。

## 1. Module Overview

策略模块负责把**历史行情**转换成**方向意图**：

```text
historical market bars -> strategy logic -> Side.BUY / Side.SELL / None
```

策略模块**不负责**：账户现金、持仓、仓位数量、风险管理、Order 创建、
Broker 撮合、手续费、滑点、印花税、盈亏、收益率、Sharpe、最大回撤、
T+1 成交逻辑。这些由 C（回测/交易内核）、D（账户/绩效）模块负责。

## 2. Architecture

```text
        Market Bars (Bar, 按时间升序)
                    |
                    v
          Strategy.on_bar(bar, history)
                    |
        +-----------+-----------+
        v           v           v
     Side.BUY   Side.SELL     None   （方向意图，不含数量）
                    |
                    v
   TargetWeightSizer -> RiskManager -> OMS -> BrokerSimulator -> Account
```

策略输出的 `Side` 会交给后续的仓位计算（sizing）、事前风控（risk）、
订单管理（OMS）和模拟撮合（broker）模块，策略本身不知道后续细节。

## 3. Public Interface

策略模块只依赖 `quant_demo.models` 中的公共数据结构（`Bar`、`Side`），
不重复定义它们。

```python
class Strategy(ABC):
    @abstractmethod
    def on_bar(self, bar: Bar, history: Mapping[str, Sequence[Bar]]) -> Side | None: ...
```

- `bar`：当前这根已完成日 K（来自 `models.Bar`，含 OHLCV）。
- `history`：`symbol -> 该股票截至当前的 Bar 序列`，按时间升序。
  **约定：`history[bar.symbol][-1] == bar`，即 history 包含当前 Bar**
  （`BacktestEngine` 与 `SimulationEngine` 都是先 append 当前 Bar 再调用
  `on_bar`）。
- 返回值：`Side.BUY` / `Side.SELL` / `None`（无交易意图）。
- 策略按 `bar.symbol` 从 history 中取**该股票自己的**历史
  （`history.get(bar.symbol, ())`），天然支持多股票，不混用价格。

## 4. Timing Convention

```text
第 T 日收盘后：Strategy 根据截至 T 日的数据产生信号
第 T+1 日开盘：由交易模块创建订单并撮合成交
```

**Strategy 只产生交易意图，不决定成交价格，也不关心是否成交。**

## 5. No Look-Ahead Rule

第 T 日调用策略时，只允许使用 **<= T 日**的数据：

- 指标函数 `result[i]` 只依赖 `values[:i+1]`（见 `indicators.py`）；
- 策略只读取 `history` 中的 Bar，不接触任何外部行情源；
- 策略为无状态纯函数：相同 `(bar, history, 参数)` 必然返回相同信号，
  不存在隐藏状态导致的隐式“记忆”。

交叉判断统一采用“上一根 Bar 的指标值 vs 当前 Bar 的指标值”，
即 `closes[:-1]` 与 `closes`，两者都不含 T+1 之后的数据。

## 6. Available Strategies

### DualMovingAverageStrategy（双均线，`moving_average.py`）

- 用途：趋势跟踪基线策略。
- 参数：`short_window=5`、`long_window=20`（须满足 `1 <= short < long`）。
- 信号：短均线上穿长均线 BUY；下穿 SELL；否则 None。
  只在交叉当日发一次信号，短均线持续高于长均线不会重复 BUY。
- 预热期：`long_window + 1` 根 Bar（默认 21）。
- 优点：简单稳健、易于解释。局限：震荡市中频繁假交叉（磨损）。

### RSIStrategy（RSI 阈值穿越，`rsi.py`）

- 用途：超买超卖反转。
- 参数：`period=14`、`oversold=30`、`overbought=70`
  （须满足 `period > 0`、`0 <= oversold < overbought <= 100`）。
- 信号：RSI 从 <= 30 上穿 30 BUY；从 >= 70 下穿 70 SELL；否则 None。
  使用阈值穿越而不是“低于 30 每天 BUY”。
- 预热期：`period + 2` 根 Bar（默认 16）。
- 优点：能捕捉短期超调。局限：强趋势中 RSI 可长期停留在极端区。

### MACDStrategy（MACD 交叉，`macd.py`）

- 用途：中周期趋势与动量。
- 参数：`fast_period=12`、`slow_period=26`、`signal_period=9`
  （须均为正且 `fast < slow`）。
- 信号：MACD 线上穿信号线（金叉）BUY；下穿（死叉）SELL；否则 None。
- 预热期：`slow_period + signal_period` 根 Bar（默认 35）。
- 优点：比双均线平滑，过滤部分噪声。局限：信号滞后更明显。

### BollingerBandsStrategy（布林带均值回归，`bollinger.py`）

- 用途：均值回归——价格偏离过远后回归。
- 参数：`period=20`、`std_multiplier=2.0`（须 `period > 1`、倍数 > 0）。
- 信号：收盘价从下轨下方重新向上穿回下轨 BUY；
  从上轨上方重新向下穿回上轨 SELL；否则 None。
  每根 Bar 与**当根 Bar 自己的**轨道比较，不用未来数据。
- 预热期：`period + 1` 根 Bar（默认 21）。
- 优点：逻辑直观、适合震荡市。局限：单边突破行情会逆势亏损。

所有策略在数据不足时返回 `None`，不会抛 `IndexError` /
`ZeroDivisionError`，也不会随机产生信号；非法参数在构造时抛 `ValueError`。

## 7. Indicator Definitions

统一实现在 `indicators.py`（纯标准库，输入升序价格序列，输出等长，
预热期位置为 `None` 而非 NaN）：

- `sma(values, window)`：简单移动平均，窗口内收盘价的算术平均。
- `ema(values, period)`：指数移动平均，`alpha = 2/(period+1)`，
  首个有效值以窗口内 SMA 为种子递推。
- `rsi(values, period=14)`：Wilder RSI，`RSI = 100 - 100/(1+RS)`，
  RS 为平均涨幅/平均跌幅（Wilder 平滑）。
- `macd(values, fast=12, slow=26, signal=9)`：返回 `MacdResult`，
  快线 = `EMA(fast) - EMA(slow)`，信号线 = 快线的 `EMA(signal)`，
  柱线 = 快线 - 信号线。
- `bollinger_bands(values, period=20, std_multiplier=2.0)`：返回
  `BollingerBands`，中轨 = SMA，上下轨 = 中轨 ± 倍数 × 窗口总体标准差。

## 8. Usage Examples

```python
from quant_demo.models import Side
from quant_demo.strategy import RSIStrategy

strategy = RSIStrategy(period=14, oversold=30, overbought=70)

# bar 为当前日 K；history 为 {symbol: [截至当前的 Bar 序列]}
signal = strategy.on_bar(bar, history)

if signal is Side.BUY:
    pass  # 交给 sizing / risk / OMS / broker 模块处理
```

策略只返回方向，示例中不实现 Account、Broker 等逻辑。

## 9. How to Add a New Strategy

1. 在本目录新建文件，类继承 `Strategy`（`base.py`）；
2. 实现 `on_bar(bar, history) -> Side | None`；
3. 只使用当前及历史 Bar：`history.get(bar.symbol, ())`，禁止未来数据；
4. 只返回 `Side.BUY` / `Side.SELL` / `None`，不碰数量与账户；
5. 历史不足（预热期）时返回 `None`，不得抛异常；
6. 构造函数做参数校验，非法参数抛 `ValueError`；
7. 优先复用 `indicators.py`，不要重复实现指标；
8. 保持无状态、确定性：不在实例里保存跨调用的隐藏状态；
9. 在本 README 的第 6 节登记新策略（参数、信号规则、预热期）。

## 10. Integration Contract

```text
Data module (A)   provides: 排序后的 list[Bar] / history: Mapping[str, Sequence[Bar]]
Strategy (B)      provides: Side.BUY / Side.SELL / None
Trading (C/D)     consumes: 信号 -> 数量(sizing) -> 风控(risk) -> 订单(OMS) -> 撮合(broker)
```

**Strategy does NOT know**：现金、持仓数量、佣金、滑点、印花税、
成交价格、账户净值与任何绩效指标。对接方只需遵守第 3 节的接口约定
（尤其 `history[bar.symbol][-1] == bar` 这一时序约定）即可直接集成。

## 11. Limitations

- 技术指标都是向后看的（lagging），不预测未来；
- 参数为常用经验值，未做任何优化，不保证盈利；
- 当前策略是教学基线（educational baselines），非生产策略；
- 输出只有方向，不含仓位大小，仓位由 sizing 模块决定；
- 当前 `Strategy` API 只有 `on_bar` 一个入口，没有训练/预热钩子，
  对需要离线训练的 ML 策略支持有限（见下节）。

## 12. Future Work

- **ML 策略设计方案（暂未实现）**：在 `ml_strategy.py` 中以
  `fit(history)` / `on_bar(...)` 分离训练与推理；特征用近期收益、
  MA ratio、RSI、MACD、波动率、量能变化；模型用可解释的简单分类器；
  信号按 `P(up) > upper -> BUY`、`P(up) < lower -> SELL`。
  训练数据与决策数据必须按时间严格隔离，禁止未来标签。
  当前不实现的原因：项目要求零新增第三方依赖（`pyproject.toml`
  不可改），纯标准库手写训练器可靠性风险高；且公共接口没有训练钩子，
  强行塞入会污染 `on_bar` 的无状态语义。
- 多因子策略与策略集成（ensemble）；
- 参数优化（需回测模块提供网格搜索入口）；
- 市场状态感知（regime-aware）策略；
- 多资产 / 行业轮动策略。
