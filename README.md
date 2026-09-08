# Intelligent Investment Demo

面向 A 股/ETF **日线低频策略**的五人协作代码骨架。第一版默认用沪深 300 ETF（`510300.SH`）代表大盘资产；如果课程要求“从沪深 300 成分股中选股”，只需由数据模块替换股票池和 Bar 数据，交易内核不变。

## 已统一的第一版规则

- 行情：日 K，统一 `Bar` 格式；
- 策略：双均线，只能读取当前及历史数据；
- 成交：当日收盘后产生信号，下一根 Bar 开盘成交；
- 市场：纯多头，A 股数量按 100 股一手；
- 成本：买卖佣金、最低佣金、卖出印花税、固定滑点均可配置；
- 仓位：默认单次目标 20%，单标的不超过 30%；
- 账户：成交是资金与持仓变化的唯一入口；
- 模式：回测和模拟运行共享策略、风控、OMS、撮合、账户与绩效模块。

## 目录与五人边界

```text
src/quant_demo/
├── models.py              # 全员共享的数据格式（先讨论再修改）
├── data/                  # A：行情读取与清洗
├── strategy/              # B：策略接口和双均线
├── modes/                 # C：回测/模拟的时间推进
├── trading/
│   ├── broker.py          # C：模拟撮合
│   ├── oms.py             # C：订单状态
│   ├── portfolio.py       # D：账户、持仓、盈亏
│   ├── sizing.py          # C/D 协作：仓位数量
│   └── risk.py            # C/D 协作：事前风控
├── analytics/             # D：净值和绩效指标
└── main.py                # E：命令行集成入口
config/demo.json           # 全员共享可配置参数
docs/TEAM_GUIDE.md         # 对接约定和 Git 协作教程
tests/                     # 接口和核心财务逻辑测试
```

E 的 Web 层应调用 `build_engine()` 或后续 service 层，不应复制账户与回测逻辑。

## 本地运行

需要 Python 3.9 或更高版本，无运行时第三方依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
quant-demo --data examples/demo_daily.csv
```

运行结果以 JSON 输出绩效指标，便于第五人直接接入 Web API。

## CSV 数据约定

```csv
symbol,date,open,high,low,close,volume
510300.SH,2025-01-02,4.00,4.06,3.98,4.04,1000000
```

真实数据必须统一复权方式、交易日历、股票代码后缀和时区。第一版建议把外部数据源下载后缓存为这个格式，Demo 时使用本地文件兜底。

## 协作方式

每人从独立分支开发，模块间只依赖 `models.py` 中的对象和公开接口。修改共享数据格式或成交/记账口径前先在群里确认；合并代码前至少运行一次 `pytest`。

从创建分支、提交代码到合并的完整操作见 [团队接口与 Git 协作指南](docs/TEAM_GUIDE.md)。该文件使用纯英文文件名，Windows、GitHub 和不同编辑器都更容易正确打开。
智能投资证券demo
