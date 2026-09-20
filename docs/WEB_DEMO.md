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

浏览器打开 <http://127.0.0.1:8000>。服务默认读取 `config/demo.json` 和包含 13 个大盘代表标的的 `examples/stocks_5y.csv`，也可以指定其他符合团队格式的文件：

```bash
quant-web --data path/to/daily.csv --config config/demo.json --port 8000
```

> 不要在文件管理器或编辑器中直接双击 `index.html`。直接打开只能预览排版，浏览器无法获得 Python 提供的行情与回测 API。若尚未执行 `pip install -e ".[dev]"`，可以在仓库根目录直接运行 `PYTHONPATH=src python3 -m quant_demo.web`。

## 页面功能

- 蓝白主题：浅色背景、白色指标卡片和蓝色主操作，适合课堂投影；
- 总览面板：数据覆盖范围、核心绩效与统一交易链路；
- 策略回测：标的、日期、策略参数、资金与仓位输入；
- 结果展示：总收益率、最大回撤、Sharpe、胜率、策略/买入持有净值曲线及数据快照 ID；
- 模拟券商：可选择免账户的本地 `PaperBrokerGateway`，也可填写 OpenD 信息连接富途官方模拟盘；
- 联网行情：模拟券商打开、手动刷新或下单时从腾讯行情通道读取现价和行情时间，失败时明确回退到本地日 K；
- AI 分析：选择标的、输入问题和 DeepSeek API Key，由后端附加隐藏的多维分析要求与行情统计后调用 DeepSeek；
- 回测历史：成功回测后自动保存完整报告，可分页查看当次回测的成交与订单；
- 交易记录：只展示当前真实/模拟券商网关的订单，不再混入回测记录；
- 错误展示：日期、资金、仓位、策略参数和空数据区间均返回中文可读错误。

## 数据与口径

- 页面不能指定服务器任意文件路径，数据文件由启动参数固定；
- 收益、回撤、Sharpe、胜率和手续费直接展示 D 模块结果；
- 信号在当日收盘后产生，成交发生在下一根 Bar 开盘；
- 基准为所选标的在同区间内按收盘价计算的买入持有曲线；
- 每次回测返回基于 Bar 内容生成的快照 ID，便于复现和核对；
- 完整回测报告默认保存到 `.quant_demo/backtests/`，该运行目录已被 Git 忽略；可用 `--history-dir` 更改位置；
- 网页默认接入本地 `PaperBrokerGateway`，也可切换到富途 OpenD `SIMULATE` 官方模拟盘；页面没有实盘开关；
- 本地模拟券商与行情数据是两件事：成交和资金在本地模拟，价格优先采用腾讯联网行情；
- 本地模拟券商只在 A 股工作日的 09:30–11:30、13:00–15:00 且联网行情日期为当天时接受订单；富途模式由 OpenD 校验对应市场的交易时间和权限；
- 回测使用固定的 `stocks_5y.csv` 前复权日 K 快照，不会把今天的联网报价混入历史回测；
- DeepSeek API Key 仅用于当前请求，不写入配置、回测历史或浏览器存储；AI 输出仅供课程研究。

## API

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/api/health` | 健康检查 |
| `GET` | `/api/bootstrap` | 页面配置和数据范围 |
| `POST` | `/api/backtest` | 运行完整历史回测 |
| `GET` | `/api/backtests` | 列出已保存的回测 |
| `GET` | `/api/backtests/{id}` | 读取一份完整回测报告 |
| `DELETE` | `/api/backtests/{id}` | 删除一份回测报告 |
| `GET` | `/api/broker/state` | 查询当前选择的模拟券商账户 |
| `POST` | `/api/broker/connect` | 切换本地 PaperBroker 或连接富途 OpenD 模拟盘 |
| `POST` | `/api/broker/reset` | 重置本地模拟券商账户 |
| `POST` | `/api/broker/order` | 提交模拟市价单或限价单 |
| `GET` | `/api/market/snapshot?symbol=...` | 获取联网行情及本地统计快照 |
| `POST` | `/api/ai/analyze` | 携带本次 API Key 调用 DeepSeek 分析 |

合并前运行 `pytest`，确认交易内核、网页接口和历史记录功能均通过测试。
