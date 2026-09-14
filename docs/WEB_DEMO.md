# E 模块：Web Demo 使用说明

该页面只负责参数输入、调用后端和展示结果。策略、风控、成交、账户与绩效均复用团队现有交易内核，没有在前端重复实现业务规则。

## 启动

在仓库根目录执行：

```bash
python -m venv .venv
source .venv/bin/activate        # Windows 使用 .venv\Scripts\activate
pip install -e ".[dev]"
quant-web
```

浏览器打开 <http://127.0.0.1:8000>。服务默认读取 `config/demo.json` 和 `examples/demo_daily.csv`，也可以指定其他符合团队格式的文件：

```bash
quant-web --data path/to/daily.csv --config config/demo.json --port 8000
```

## 页面功能

- 总览面板：数据覆盖范围、核心绩效与统一交易链路；
- 策略回测：标的、日期、策略参数、资金与仓位输入；
- 结果展示：策略/买入持有净值曲线、绩效指标及数据快照 ID；
- 模拟运行：逐根日 K 推送至 `SimulationEngine`，可暂停与单步；
- 交易记录：成交、订单状态、价格、费用、拒绝原因；
- 错误展示：日期、资金、仓位、策略参数和空数据区间均返回中文可读错误。

## 数据与口径

- 页面不能指定服务器任意文件路径，数据文件由启动参数固定；
- 收益、回撤、Sharpe、胜率和手续费直接展示 D 模块结果；
- 信号在当日收盘后产生，成交发生在下一根 Bar 开盘；
- 基准为所选标的在同区间内按收盘价计算的买入持有曲线；
- 每次回测返回基于 Bar 内容生成的快照 ID，便于复现和核对；
- 该系统仅用于课程模拟，不连接券商、不执行真实交易。

## API

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/api/health` | 健康检查 |
| `GET` | `/api/bootstrap` | 页面配置和数据范围 |
| `POST` | `/api/backtest` | 运行完整历史回测 |
| `POST` | `/api/simulation/start` | 初始化行情回放 |
| `POST` | `/api/simulation/step` | 推进一根 Bar |

合并前运行 `pytest`。E 分支未修改 `models.py`、共享配置、账户、绩效、策略或成交规则。
