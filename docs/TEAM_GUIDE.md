# 团队接口与 Git 协作指南

这份说明面向第一次进行多人代码协作的同学。大家不需要一次学会 Git 的全部功能，只要坚持“每个人用自己的分支、不要直接改主分支、合并前先测试”即可。

## 一、系统怎么串起来

```text
行情数据 -> 策略判断 -> 计算买卖数量 -> 风险检查
        -> 创建订单 -> 模拟成交 -> 更新账户 -> 计算绩效
```

对应代码调用关系：

```text
MarketDataService -> Strategy -> TargetWeightSizer -> RiskManager
                  -> OMS -> BrokerSimulator -> Account -> Performance
```

回测由 `BacktestEngine.run(bars)` 一次性运行一段历史行情。模拟模式由 `SimulationEngine.on_bar(bar)` 在每收到一根新日 K 时运行一次。二者使用同一套策略、订单、账户和绩效代码。

## 二、五个人分别改哪里

| 人员 | 主要目录或文件 | 输入 | 应该交付的结果 | 不要做的事 |
|---|---|---|---|---|
| A 数据 | `src/quant_demo/data/`、`examples/` | 股票池、日期 | 排好序的 `list[Bar]` | 不让其他模块依赖 AkShare/DataFrame |
| B 策略 | `src/quant_demo/strategy/` | 当前和以前的 Bar | `Side.BUY`、`Side.SELL` 或 `None` | 不改现金和持仓，不看未来数据 |
| C 回测 | `src/quant_demo/modes/`、`broker.py`、`oms.py` | Bar、策略、风控等组件 | `BacktestResult` | 不绕过 Account 直接改账 |
| D 账户 | `portfolio.py`、`performance.py`，协助 `risk.py` | Trade、每日收盘价 | 资金持仓、净值和指标 | 不负责决定买卖时机 |
| E Web | 后续新建 `frontend/` 或 `api/` | 配置、BacktestResult、账户快照 | 页面和接口 | 不在页面里重写回测和记账规则 |

`src/quant_demo/models.py` 是大家共同使用的数据格式。例如策略和账户都使用同一个 `Side`，回测与 Web 都使用同一个 `BacktestResult`。任何人想修改这个文件，都先在群里说明修改原因和影响，得到确认后再改。

## 三、D 模块的记账规则

- 买入现金减少：`成交价 × 数量 + 佣金`；买入费用计入平均成本。
- 卖出现金增加：`成交价 × 数量 - 佣金 - 印花税`。
- 加仓后采用移动平均成本；部分卖出不改变剩余股票的平均成本。
- 已实现盈亏：`(卖价 - 平均成本) × 卖出数量 - 卖出费用`。
- 未实现盈亏：`(最新价 - 平均成本) × 当前数量`。
- 总资产：`现金 + 所有持仓市值`。
- 每个交易日记录一次净值，绩效函数只读取净值和成交，不修改账户。

## 四、回测每天按什么顺序运行

```text
第 T 日开盘：成交第 T-1 日收盘后产生的订单
第 T 日收盘：用 close 更新持仓市值和账户净值
第 T 日收盘后：策略读取截至 T 日的数据，决定是否创建新订单
```

因此，最后一天产生的新订单因为没有下一根 Bar，会保留为 `CREATED`，不会被错误地算成已经成交。

## 五、第一次建立共享仓库

由一名组员担任仓库管理员，在 GitHub 或 Gitee 创建一个空仓库，并把其他四人添加为协作者。管理员在当前项目目录执行：

```powershell
git remote add origin 你们的仓库地址
git branch -M main
git add .
git commit -m "chore: initialize quant demo"
git push -u origin main
```

仓库地址形如 `https://github.com/团队名/仓库名.git`。如果 `git remote -v` 已经能看到 `origin`，不要重复执行 `git remote add`。

其他四人在自己的电脑上执行：

```powershell
git clone 你们的仓库地址
cd Intelligent_Investment
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
```

看到测试通过，说明环境和代码正常。

## 六、每个人日常怎么提交代码

不要直接在 `main` 分支开发。开始一个任务时，先取得最新主分支，再创建自己的分支：

```powershell
git switch main
git pull origin main
git switch -c feature/account-performance
```

建议五个人分别使用：

```text
feature/data
feature/strategy
feature/backtest
feature/account-performance
feature/web
```

完成一小块可以运行的功能后：

```powershell
git status
pytest
git add 你实际修改的文件
git commit -m "feat: calculate account unrealized pnl"
git push -u origin feature/account-performance
```

然后到 GitHub/Gitee 页面创建 Pull Request（有的平台叫 Merge Request），选择从自己的功能分支合并到 `main`。请另一位组员检查后再合并。

以后在同一个分支继续提交，只需：

```powershell
git add 你实际修改的文件
git commit -m "fix: correct sell commission calculation"
git push
```

## 七、怎么减少代码冲突

1. 每个人主要修改自己负责的目录，不要顺手格式化整个项目。
2. 每天开始工作前执行 `git switch main` 和 `git pull origin main`，再创建新分支。
3. 一次提交只做一件事，提交说明写清楚 `feat`（功能）、`fix`（修复）、`test`（测试）或 `docs`（文档）。
4. 不提交 `.venv`、缓存和本地密钥；这些已由 `.gitignore` 排除。
5. `models.py`、`config/demo.json` 和成交记账规则属于公共部分，修改前先在群里确认。
6. 合并前运行 `pytest`，并让至少一位相关模块负责人检查接口是否仍能对接。

如果两个人改到了同一行，Git 会提示冲突。此时不要随便删除一方代码；让两位相关同学一起决定最终内容，修改完成后重新运行测试再提交。

## 八、推荐的合并顺序

第一轮先合并全员需要的数据格式；第二轮合并 A 的数据、B 的策略、C/D 的交易内核；最后由 E 接入 Web。开发不必完全串行，大家可以先依据当前接口写代码和测试，但公共接口变化要立即通知全组。

## 九、合并前检查表

1. 自己的模块没有直接修改其他模块的内部状态。
2. 新字段有合理默认值，旧代码仍能运行。
3. 买入、估值、卖出和费用等金额关系有测试。
4. 策略测试确认只使用当前和历史数据。
5. 行情按 `(datetime, symbol)` 排序，同一股票同一天没有重复数据。
6. `pytest` 全部通过。

## 十、团队还需要确认的事项

- “选大盘”是直接交易沪深 300 ETF，还是从沪深 300 成分股中选股；当前模板采用 ETF。
- 股票数据使用前复权、后复权还是不复权；建议课程回测统一使用前复权。
- 是否严格模拟 A 股 T+1；当前日线策略自然跨日，但尚未单独记录当日不可卖数量。
- 佣金和卖出印花税采用什么课程假设；目前都能在配置文件中修改。
- A 提供基准净值后，D 再增加相对沪深 300 的超额收益。

