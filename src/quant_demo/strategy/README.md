# Strategy Module（策略模块）

负责人：B（Strategy / 策略模块）。本目录是策略模块的完整交付内容。

当前版本：**Strategy V2**（在 V1 的 4 个教学基线之上，扩充为 10 个策略 +
统一注册表，覆盖趋势 / 均值回归 / 波动率感知 / 多因子综合四大类别）。

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
  不存在隐藏状态导致的隐式“记忆”；
- 通道类策略（Donchian）的参考通道**不包含当前 Bar 自身**——第 T 日的
  上下轨取“截至第 T-1 日”的滚动极值，不存在“用自己突破自己”；
- 所有指标满足 prefix invariance：用完整序列计算到 T 的结果，与只输入
  截至 T 的序列计算结果完全一致（无 centered rolling、无未来引用）。

交叉判断统一采用“上一根 Bar 的指标值 vs 当前 Bar 的指标值”，
即 `closes[:-1]` 与 `closes`，两者都不含 T+1 之后的数据。

## 6. Strategy Families

| Strategy | Type | Typical Market | Main Risk |
|---|---|---|---|
| Dual MA | Trend | Trending | Lag（信号滞后） |
| MACD | Trend / Momentum | Trending | 滞后更明显，震荡市假交叉 |
| Momentum | Momentum / Trend | Trending | 反转日追高杀低 |
| Donchian | Breakout / Trend | Trending | False breakout（假突破） |
| RSI | Mean Reversion | Sideways | 强趋势中长期停留极端区 |
| Bollinger | Mean Reversion | Sideways | 单边突破行情逆势亏损 |
| Z-score | Mean Reversion | Sideways | 与 Bollinger 同源，同上 |
| Stochastic | Oscillator / Mean Reversion | Sideways | 极端区钝化、强趋势失效 |
| ATR Trend | Volatility Aware | High-volatility / Trending | 波动骤变时轨道失真 |
| Composite | Multi-factor | Mixed | Parameter sensitivity |

分类思路：**不同思想类别**优先于指标数量——同一类别的指标高度相关，
叠加同类指标不等于更聪明。四类别（趋势 / 均值回归 / 波动率感知 /
多因子综合）对应不同的市场假设，也是未来自适应策略选择的基础。

## 7. Available Strategies

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

### MomentumStrategy（动量阈值穿越，`momentum.py`）

- 用途：捕捉中短期价格趋势，最直接的动量基线。
- 核心思想：`momentum = close_t / close_(t-lookback) - 1`，
  过去 N 日涨跌幅本身就是趋势强弱的度量。
- 参数：`lookback=20`、`positive_threshold=0.0`、`negative_threshold=0.0`
  （须 `lookback > 0` 且 `negative_threshold <= positive_threshold`）。
  默认阈值 0 即“动量过零”；加大阈值可过滤弱趋势。
- 信号：动量上穿正阈值 BUY；下穿负阈值 SELL；否则 None。
  采用穿越方式，动量持续为正不会每天重复 BUY。
- 预热期：`lookback + 2` 根 Bar（默认 22）。
- 优点：定义透明、参数少。局限：不经过平滑，V 型反转日容易追高杀低。

### DonchianBreakoutStrategy（唐奇安通道突破，`donchian.py`）

- 用途：经典趋势突破——突破前 N 日区间意味着新趋势可能启动。
- 核心思想：上轨 = **前** N 根 Bar 的最高价（不含当天），
  下轨 = 前 N 根 Bar 的最低价（不含当天）；当前收盘突破轨道才行动。
  当前 Bar 的 high/low 不参与通道计算，杜绝“自己突破自己”。
- 参数：`lookback=20`（须 `lookback > 0`）。
- 信号：收盘价上穿上轨 BUY；下穿下轨 SELL；否则 None。
  采用穿越方式（上一根收盘尚未突破），突破后不会重复发信号。
- 预热期：`lookback + 2` 根 Bar（默认 22）。
- 优点：抓趋势起点、用 high/low 比 close 信息量更大。
  局限：假突破（false breakout）是主要亏损来源。

### StochasticStrategy（随机指标交叉，`stochastic.py`）

- 用途：超买超卖摆动指标，利用 close 在近期高低区间中的位置。
- 核心思想：`%K = (close - N日最低) / (N日最高 - N日最低) * 100`，
  `%D = %K 的 d_period 日 SMA`；%K/%D 在极端区域的交叉比单纯阈值
  更接近“动能转向”。
- 参数：`k_period=14`、`d_period=3`、`oversold=20`、`overbought=80`
  （须 `k_period, d_period > 0`、`0 <= oversold < overbought <= 100`）。
- 信号：超卖区内 %K 上穿 %D（低位金叉）BUY；
  超买区内 %K 下穿 %D（高位死叉）SELL；否则 None。
  “区域 + 交叉”双重条件，避免极端区钝化时每天重复信号。
- 预热期：`k_period + d_period` 根 Bar（默认 17）。
- 优点：对短期拐点敏感。局限：强趋势中 %K 可长期贴着极端区失效。

### ATRTrendStrategy（ATR 波动率感知趋势，`atr_trend.py`）

- 用途：只有当价格偏离**显著超过正常波动**时才交易，过滤噪声。
- 核心思想：以 `MA(ma_window)` 为趋势中枢，以 `ATR(atr_period)` 为
  波动尺度，轨道 = 中枢 ± `atr_multiplier` × ATR。ATR 只用于衡量
  波动是否显著，**不用于仓位管理**（仓位由 sizing 模块负责）。
- 参数：`ma_window=20`、`atr_period=14`、`atr_multiplier=2.0`
  （须 `ma_window > 0`、`atr_period > 0`、`atr_multiplier > 0`）。
- 信号：收盘价上穿上轨 BUY；下穿下轨 SELL；否则 None（穿越式）。
- 预热期：`max(ma_window, atr_period) + 1` 根 Bar（默认 21）。
- 优点：波动大时轨道自动变宽，低波动震荡市不交易。
  局限：波动率骤变（跳空后 ATR 抬升）会瞬间推高/压低轨道，信号失真。

### ZScoreMeanReversionStrategy（Z 分数均值回归，`mean_reversion.py`）

- 用途：用标准化偏离度量“价格偏离均值几个标准差”，偏离收敛时交易。
- 核心思想：`z = (close - 窗口均值) / 窗口总体标准差`；
  z 从极端区域穿回阈值内说明偏离开始收敛。
- 参数：`window=20`、`buy_z=-2.0`、`sell_z=2.0`
  （须 `window > 1`、`buy_z < sell_z`）。
- 信号：z 从 <= buy_z 向上穿回 buy_z BUY；
  z 从 >= sell_z 向下穿回 sell_z SELL；否则 None（穿越式）。
- 预热期：`window + 1` 根 Bar（默认 21）。
- **与 Bollinger 的关系**：默认对称参数下二者数学等价
  （z = ±2 恰为 2 倍标准差轨道）。本策略的独立价值在于支持
  **非对称阈值**（例如 `buy_z=-2.5, sell_z=1.5`，表达“跌得深才抄底、
  涨一点就兑现”的非对称假设），以及 Z 分数形式便于和其他因子比较。
- 局限：与 Bollinger 同源，强趋势中同样会逆势亏损。

### CompositeStrategy（多指标综合，`composite.py`）

- 用途：不依赖单一指标，综合**趋势、动量、强弱**三个维度投票打分，
  是当前策略库中最“智能”的策略。
- 核心思想：每个维度各投一票（-1 / 0 / +1），总分 [-3, 3]：

  | 维度 | 指标 | 票规则 |
  |---|---|---|
  | 趋势 | 短/长 SMA | 短 SMA > 长 SMA → +1，否则 -1 |
  | 动量 | MACD 柱线 | histogram > 0 → +1，否则 -1 |
  | 强弱 | RSI | >= rsi_bull → +1；<= rsi_bear → -1；中间区 0（中性不投票） |

- 避免重复计票的设计：三个维度选自不同指标族；RSI 设中性区，
  温和行情中不与趋势票重复表态；默认要求总分 >= 2（至少两票同向）
  才触发，而不是一票定音。注意均线与 MACD 仍有正相关，这是已知的
  设计折中，可用 `buy_threshold=3` 要求全票通过来提高严格度。
- 参数：`short_window=5`、`long_window=20`、`rsi_period=14`、
  `rsi_bull=55`、`rsi_bear=45`、`fast_period=12`、`slow_period=26`、
  `signal_period=9`、`buy_threshold=2`、`sell_threshold=-2`。
- 信号：总分从 < buy_threshold 上升为 >= buy_threshold BUY；
  从 > sell_threshold 下降为 <= sell_threshold SELL；否则 None。
  采用“得分穿越阈值”的事件方式，不每天重复。
- 可解释性：`score_components(closes)` 公开方法返回 `CompositeScore`
  （trend / momentum / rsi / total），每次信号都能分解到具体哪几票，
  可用于日志、调试与 Web 展示。
- 预热期：`max(long_window + 1, rsi_period + 2, slow_period +
  signal_period)` 根 Bar（默认 35）。
- 优点：多维度互相确认，单一指标失灵时不至于满仓误判。
  局限：参数多，对参数选择敏感；投票规则是先验的，未经过优化。

所有策略在数据不足时返回 `None`，不会抛 `IndexError` /
`ZeroDivisionError`，也不会随机产生信号；非法参数在构造时抛 `ValueError`。

## 8. Strategy Applicability（策略适用性）

以下是各策略的**典型 / 潜在**适用场景，不是“某策略一定适合某股票”的结论。
实际选择必须由回测结果验证。

```text
Trending market（趋势市）:
    Momentum / MACD / Donchian / Dual MA
Range-bound market（震荡市）:
    RSI / Bollinger / Z-score / Stochastic
High-volatility market（高波动市）:
    ATR-aware strategy（ATR Trend）
Mixed / unclear regime（混合市况）:
    Composite（多维度互相确认）
```

使用时的注意点：

- 同一类别的策略高度相关，同时启用多个趋势策略不等于分散风险；
- 震荡策略在单边行情中会持续逆势发信号，趋势策略在震荡市中会被
  反复磨损，**没有策略在所有市场状态下都有效**；
- 以上归类基于策略的市场假设（趋势延续 vs 均值回归），
  是否成立请以分市场、分时段的回测表现为准。

## 9. Indicator Definitions

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
- `momentum(values, lookback)`：N 日动量，`values[i]/values[i-lookback]-1`。
- `highest(values, window)` / `lowest(values, window)`：滚动最高/最低值。
- `true_range(highs, lows, closes)`：真实波幅 TR。
- `atr(highs, lows, closes, period=14)`：Wilder 平均真实波幅。
- `stochastic(highs, lows, closes, k_period=14, d_period=3)`：返回
  `StochasticResult`（%K、%D）；窗口内零价差时 %K 返回 50。
- `rolling_std(values, window)`：滚动总体标准差。
- `zscore(values, window)`：滚动 Z 分数；窗口标准差为 0 时返回 0。

多输入指标（`true_range` / `atr` / `stochastic`）要求三条序列等长，
否则抛 `ValueError`。所有指标满足 prefix invariance（见第 5 节）。

## 10. Strategy Registry

`registry.py` 提供轻量注册表，按名字统一查询和构造策略：

```python
from quant_demo.strategy import available_strategies, create_strategy

available_strategies()
# ('atr_trend', 'bollinger', 'composite', 'donchian', 'dual_ma',
#  'macd', 'momentum', 'rsi', 'stochastic', 'zscore_mean_reversion')

strategy = create_strategy("composite", buy_threshold=2)
```

注册表是策略模块内部的便捷入口：它不改变 C 模块 `modes/factory.py`
的配置白名单（新策略接入配置文件需 C 组登记），但为上层（Web、未来的
自适应选择）提供了统一的“名字 -> 策略类”映射，避免硬编码 import。

## 11. Usage Examples

```python
from quant_demo.models import Side
from quant_demo.strategy import CompositeStrategy

strategy = CompositeStrategy(buy_threshold=2, sell_threshold=-2)

# bar 为当前日 K；history 为 {symbol: [截至当前的 Bar 序列]}
signal = strategy.on_bar(bar, history)

if signal is Side.BUY:
    pass  # 交给 sizing / risk / OMS / broker 模块处理

# 调试 / 展示：查看打分明细
closes = [b.close for b in history[bar.symbol]]
print(strategy.score_components(closes))  # CompositeScore(trend=1, ...)
```

策略只返回方向，示例中不实现 Account、Broker 等逻辑。

## 12. How to Add a New Strategy

1. 在本目录新建文件，类继承 `Strategy`（`base.py`）；
2. 实现 `on_bar(bar, history) -> Side | None`；
3. 只使用当前及历史 Bar：`history.get(bar.symbol, ())`，禁止未来数据；
4. 只返回 `Side.BUY` / `Side.SELL` / `None`，不碰数量与账户；
5. 历史不足（预热期）时返回 `None`，不得抛异常；
6. 构造函数做参数校验，非法参数抛 `ValueError`；
7. 优先复用 `indicators.py`，不要重复实现指标；
8. 保持无状态、确定性：不在实例里保存跨调用的隐藏状态；
9. 在 `registry.py` 的 `STRATEGY_REGISTRY` 中登记名字；
10. 在本 README 的第 6/7 节登记新策略（参数、信号规则、预热期）。

## 13. Future Adaptive Strategy Selection（未来自适应策略选择）

本次升级**刻意不实现**自动策略选择系统，但当前设计已为其实现做好准备：

```text
Market Regime Detection（新增模块，不在 strategy/ 内）
        |
        v
Trending / Range-bound / High-volatility
        |
        v
create_strategy("momentum" | "bollinger" | "atr_trend", ...)   # registry.py
        |
        v
BacktestEngine / SimulationEngine（接口不变，on_bar 契约不变）
```

已经具备的扩展基础：

1. **接口统一**：所有策略共享 `on_bar(bar, history)` 契约，选择器可以把
   任意策略当作可替换组件；
2. **参数透明**：每个策略的参数都在构造函数中显式声明并校验，
   选择器可以按配置安全地构造；
3. **注册表**：`create_strategy(name, **params)` 提供按名字构造的统一
   入口，选择器不需要硬编码 import；
4. **可解释打分**：`CompositeStrategy.score_components` 展示了一条
   “信号可分解”的路线，未来选择器的决策也应可解释；
5. **适用性文档**：第 6/8 节的分类表可以作为 regime -> 策略映射的
   初始假设（待回测验证）。

未来实现时的建议：

- Regime 检测（如基于波动率分位数、趋势强度 ADX、Hurst 指数等）
  应放在独立模块中，输出 regime 标签；策略模块本身保持无状态；
- 选择器切换策略时应只切换“未来信号由谁产生”，不回溯修改历史信号；
- 先用固定 regime 规则 + 分 regime 回测验证，再考虑学习式选择器；
- 避免在选择器中叠加过多策略，先用第 6 节分类表每类取一个代表。

## 14. Integration Contract

```text
Data module (A)   provides: 排序后的 list[Bar] / history: Mapping[str, Sequence[Bar]]
Strategy (B)      provides: Side.BUY / Side.SELL / None
Trading (C/D)     consumes: 信号 -> 数量(sizing) -> 风控(risk) -> 订单(OMS) -> 撮合(broker)
```

**Strategy does NOT know**：现金、持仓数量、佣金、滑点、印花税、
成交价格、账户净值与任何绩效指标。对接方只需遵守第 3 节的接口约定
（尤其 `history[bar.symbol][-1] == bar` 这一时序约定）即可直接集成。

## 15. Limitations

- 技术指标都是向后看的（lagging），不预测未来；
- 参数为常用经验值，未做任何优化，不保证盈利；
- 当前策略是教学基线（educational baselines），非生产策略；
- 输出只有方向，不含仓位大小，仓位由 sizing 模块决定；
- Z-score 均值回归与 Bollinger 在默认对称参数下数学等价，
  独立价值在于非对称阈值；
- CompositeStrategy 的投票权重固定为等权（1 票/维度），
  均线票与 MACD 票存在已知正相关；
- 当前 `Strategy` API 只有 `on_bar` 一个入口，没有训练/预热钩子，
  对需要离线训练的 ML 策略支持有限（见下节）。

## 16. Future Work

- **ML 策略设计方案（暂未实现）**：在 `ml_strategy.py` 中以
  `fit(history)` / `on_bar(...)` 分离训练与推理；特征用近期收益、
  MA ratio、RSI、MACD、波动率、量能变化；模型用可解释的简单分类器；
  信号按 `P(up) > upper -> BUY`、`P(up) < lower -> SELL`。
  训练数据与决策数据必须按时间严格隔离，禁止未来标签。
  当前不实现的原因：项目要求零新增第三方依赖（`pyproject.toml`
  不可改），环境中也没有 numpy / pandas / sklearn，纯标准库手写
  训练器可靠性风险高；且公共接口没有训练钩子，强行塞入会污染
  `on_bar` 的无状态语义。
- 自适应策略选择（见第 13 节，本期只预留结构不实现）；
- 参数优化（需回测模块提供网格搜索入口）；
- 多资产 / 行业轮动策略；
- 成交量因子（当前 Bar 含 volume，但 V2 策略暂未使用）。
