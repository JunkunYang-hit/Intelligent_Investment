# 智能量化交易系统 Demo

这是一个面向课程展示和多人协作开发的低频量化交易系统。系统提供大盘相关标的、日线策略回测、账户与绩效分析、回测历史、免费联网行情、本地模拟交易、富途官方模拟盘接入和 DeepSeek 分析界面。

默认不会连接实盘账户，也不会执行真实资金交易。

## 已实现功能

- 13 个 A 股大盘指数、行业和跨市场 ETF，界面同时显示中文名称和证券代码；
- 双均线、RSI、MACD、布林带四种容易解释的低频策略；
- 一键快速回测，遵循“收盘产生信号，下一交易日开盘成交”；
- 佣金、最低佣金、印花税、滑点、交易手数和仓位限制；
- 总收益率、年化收益率、最大回撤、Sharpe、胜率、交易次数和费用；
- 回测报告自动保存，成交与订单支持分页查看；
- 腾讯公开行情快照，无需行情账号或 API Key；
- 本地 `PaperBroker` 模拟账户，适合随时演示完整交易流程；
- 富途 OpenD 官方模拟盘，可从网页填写连接信息并切换；
- DeepSeek 标的分析，API Key 只用于当次请求，不保存在项目中；

## 三种数据与账户不要混淆


| 功能         | 当前来源                                 | 是否需要账户 | 用途                                 |
| ------------ | ---------------------------------------- | -----------: | ------------------------------------ |
| 历史回测     | `examples/stocks_5y.csv` 前复权日 K 快照 |           否 | 保证每个人能复现相同结果             |
| 最新行情     | 腾讯公开行情接口                         |           否 | 查看最新报价、本地模拟下单和 AI 分析 |
| 本地模拟券商 | `PaperBrokerGateway`                     |           否 | 在本机内存中模拟资金、持仓和成交     |
| 富途模拟券商 | 富途 OpenD`SIMULATE` 环境                |           是 | 使用富途官方模拟账户、订单和持仓     |

腾讯行情和券商账户是两个独立部分。选择富途后，订单、资金和持仓来自富途模拟账户，不再由本地程序模拟成交。

腾讯通道属于按请求获取的免费最新行情快照，不是交易所付费低延迟行情，也不是持续推送流。页面打开、手动刷新或本地下单时才会请求更新，适合本项目的低频演示。

## 项目目录

```text
config/demo.json                 策略、成本、风控和股票池配置
examples/stocks_5y.csv           可复现的五年日 K 数据
src/quant_demo/
├── data/                        行情读取、清洗和联网报价
├── strategy/                    低频策略
├── modes/                       回测时间推进
├── trading/                     订单、撮合、仓位和风控
├── analytics/                   账户净值与绩效指标
├── brokerage/                   本地、富途、QMT 券商适配器
└── web/                         Web 服务、历史记录和 AI 分析
tests/                           自动化测试
docs/TEAM_GUIDE.md               团队接口和 Git 协作说明
docs/WEB_DEMO.md                 Web 接口补充说明
```

## 从零安装并复现

### 1. 准备软件

安装 Python 3.9 或更高版本、Git 和现代浏览器。在 PowerShell 中检查：

```powershell
python --version
git --version
```

### 2. 获取项目

如果还没有项目：

```powershell
git clone https://github.com/JunkunYang-hit/Intelligent_Investment.git
cd Intelligent_Investment
```


### 3. 创建独立 Python 环境

推荐使用项目自己的虚拟环境，避免和电脑中其他 Python 项目冲突：

```powershell
python -m venv .venv
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

如果使用 Conda：

```powershell
conda create -n quant-demo python=3.11 -y
conda activate quant-demo
pip install -e ".[dev]"
```

### 4. 验证安装并启动

```powershell
python -m pytest -q
quant-web
```

浏览器打开 `http://127.0.0.1:8000`。

不要直接双击 `index.html`。页面必须通过 Python 服务访问，回测、行情、历史记录和 AI 接口才能工作。

### 5. 推荐演示流程

1. 打开“策略回测”；
2. 选择标的、策略、日期、初始资金和目标仓位；
3. 点击“一键快速回测”；
4. 查看收益率、最大回撤、胜率、费用和净值曲线；
5. 打开“回测历史”，查看本次回测的成交和订单；
6. 打开“模拟券商”，选择本地模拟或富途模拟盘；
7. 打开“AI 分析”，填写自己的 DeepSeek API Key 后提问。

回测历史默认保存在 `.quant_demo/backtests/`。该目录不会提交到 Git，但服务重启后历史仍然存在。

## 使用本地模拟券商

本地模拟不需要开户，也不需要额外安装软件：

1. 在“模拟券商”页面选择“本地 PaperBroker”；
2. 点击“连接所选模拟券商”；
3. 选择 A 股 ETF、方向、数量和订单类型；
4. 在 A 股交易时间提交订单。

本地模拟订单只允许在工作日 `09:30–11:30`、`13:00–15:00` 提交。联网报价不是当天数据、周末或休市时会拒单。账户和订单保存在当前服务内存，重启服务后清空。

## 接入富途官方模拟盘

富途模拟盘使用官方 OpenD 通道，所以需要富途账户和本机 OpenD，但不使用真实资金。

### 安装富途支持

```powershell
pip install -e ".[dev,futu]"
```

### 准备 OpenD

1. 安装富途 OpenD；
2. 使用富途账户登录 OpenD；
3. 确认 OpenD 正在运行，默认地址为 `127.0.0.1:11111`；
4. 确认账户具有港股或美股模拟交易环境。

### 在网页连接

1. 打开“模拟券商”；
2. 选择“富途 OpenD 官方模拟盘”；
3. 填写 OpenD 主机、端口和市场；
4. 通常把“模拟账户 ID”留空，系统会自动选择模拟账户；有多个账户时可填写 OpenD 返回的 `acc_id`；
5. 点击“连接所选模拟券商”；
6. 港股代码使用 `0700.HK`，美股代码使用 `AAPL.US`；
7. 提交订单后在网页和富途模拟账户中核对状态。

网页固定使用 `simulate=True`，没有提供切换实盘的按钮，也不会要求输入富途密码。连接参数只保存在当前 Python 进程内存中。

## DeepSeek AI 分析

在“AI 分析”页面填写 DeepSeek API Key、选择标的并输入问题即可。后端会附加行情统计和风险分析要求，再调用 DeepSeek。

- API Key 不写入配置文件；
- API Key 不写入回测历史；
- API Key 不保存在浏览器存储；
- AI 内容仅用于课程研究，不构成投资建议。

## 常用启动参数

```powershell
quant-web --port 8080
quant-web --data examples/stocks_5y.csv --config config/demo.json
quant-web --history-dir .quant_demo/my-backtests
```

命令行回测也可以单独运行：

```powershell
quant-demo --data examples/stocks_5y.csv
```

## 常见问题

### `quant-web` 无法识别

确认已经激活虚拟环境并执行过 `pip install -e ".[dev]"`。也可以在仓库根目录运行：

```powershell
python -m quant_demo.web
```

### 富途连接失败

依次检查：是否安装 `futu-api`、OpenD 是否启动并登录、主机端口是否正确、防火墙是否拦截，以及所选市场是否存在对应的模拟账户。

### 周末无法演示下单

这是正常的交易时段保护。周末仍可演示历史回测、回测历史和 AI 分析。券商下单需要在对应市场交易时间演示。

### 腾讯行情访问失败

检查网络连接。历史回测仍可使用本地 CSV；为了避免按过期价格成交，本地模拟券商会暂停下单。

## 团队协作

修改前先拉取最新代码，从独立分支开发，提交前运行测试：

```powershell
git pull
git switch -c feature/你的功能名
python -m pytest -q
git add .
git commit -m "feat: 简要说明修改内容"
git push -u origin feature/你的功能名
```

然后在 GitHub 创建 Pull Request。更详细的模块边界、接口说明和 Git 操作见 [团队接口与 Git 协作指南](docs/TEAM_GUIDE.md)。

## 风险说明

本项目是教学 Demo，不构成投资建议。即使使用券商模拟盘，也应核对市场、证券代码、方向、数量和订单状态。连接真实账户、程序化实盘交易和监管报备不属于本项目默认演示范围。
