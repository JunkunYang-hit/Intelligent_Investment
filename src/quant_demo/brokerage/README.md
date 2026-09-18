# 券商网关接入指南（Brokerage）

响应老师意见「接入真正的券商接口」：本包建立了统一的 `BrokerGateway` 通道层，
策略与订单系统只面向该接口编程，更换券商 = 更换网关实现，业务代码零改动。

## 网关实现一览

| 网关 | 市场 | 模式 | 前置条件 | 课程演示可用 |
|------|------|------|----------|:---:|
| `PaperBrokerGateway` | 任意 | 本地模拟 | 无 | ✅ 直接跑通 |
| `FutuGateway(simulate=True)` | 港股/美股 | 富途官方模拟盘 | 富途账户 + OpenD + `pip install futu-api` | ✅ 真实环境仿真 |
| `FutuGateway(simulate=False)` | 港股/美股 | 实盘 | 上述 + 交易解锁 | ⚠️ 需自行开通，风险自负 |
| `QMTGateway` | A股 | 实盘/仿真 | 券商账户 + QMT量化权限 + QMT客户端 + `pip install xtquant` | ⚠️ 需券商开通 |

**诚实说明**：任何真实券商接口都需要「证券账户 + 量化权限 + 本机客户端程序」，
这是开户与授权流程，代码无法替代。适配器代码按官方 SDK 公开接口编写，
完成授权后即可实际连通；未授权环境下运行会在 `connect()` 处失败并给出明确提示。

## 快速开始（端到端演示，真实行情价格）

```bash
python scripts/broker_demo.py            # 模拟撮合 + 腾讯实时真实盘口价（开箱即用）
```

演示链路：**真实行情（免账户）→ 股票池五年数据动量选股 → 网关下单 → 成交回报 → 持仓/资金**。
paper 网关用真实现价撮合；换真实券商只需 `--gateway qmt|futu`，环境未就绪时自动给出诊断清单而不是静默失败。

QMT 环境自检（部署实盘前的检查清单）：

```python
from quant_demo.brokerage.qmt_gateway import qmt_self_test
print(qmt_self_test(r"C:\QMT安装目录\userdata_mini"))
# {'sdk_installed': True, 'client_running': False, 'advice': ['启动并登录 QMT/miniQMT 客户端...']}
```

## 最小下单示例（本地模拟，零依赖）

```python
from datetime import datetime
from quant_demo.brokerage import PaperBrokerGateway
from quant_demo.models import OrderRequest, Side

gw = PaperBrokerGateway(initial_cash=1_000_000)
gw.connect()
gw.set_last_close("600900.SH", 28.63)          # 引擎每根Bar注入最新价

oid = gw.place_order(
    OrderRequest("600900.SH", Side.BUY, 1000, datetime.now(), reason="示例"),
    order_type="market",
)
print(gw.query_order(oid).status)   # FILLED
print(gw.query_positions())          # [Position(symbol='600900.SH', quantity=1000, ...)]
print(gw.query_cash())
```

## 接入富途（港股/美股，推荐路径）

1. 注册富途牛牛，开通证券账户（港股/美股需在 App 内签署市场协议）；
2. 电脑端下载 **OpenD** 网关程序并登录（默认监听 `127.0.0.1:11111`）；
3. 安装 SDK：`pip install futu-api`；
4. 模拟盘演示（无需真实资金）：

```python
from quant_demo.brokerage import FutuGateway

gw = FutuGateway(market="HK", simulate=True)   # 富途模拟账户
gw.connect()
oid = gw.place_order(req, order_type="limit", price=300.0)
```

5. 切换实盘：`simulate=False` + 在 OpenD 配置交易解锁。**下单前务必
   核对合约、数量与账户，模拟盘验证充分后再考虑实盘。**

## 接入 QMT/miniQMT（A股实盘）

1. 在支持 QMT 的券商（国金、国盛、中泰、华鑫等）开户；
2. 向券商申请 **QMT/miniQMT 量化权限**（部分券商有资金门槛，miniQMT 门槛更低）；
3. 安装 QMT 客户端并登录，切换到极简模式（miniQMT），保持后台运行；
4. 安装 SDK：`pip install xtquant`；
5. 连接：

```python
from quant_demo.brokerage import QMTGateway

gw = QMTGateway(
    qmt_userdata_path=r"C:\国金QMT交易端\userdata_mini",  # QMT安装目录下
    account_id="你的资金账号",
)
gw.connect()
```

## 风险与合规提示

- 程序化交易须遵守券商协议；境内程序化交易需按监管要求完成**报备**；
- 券商对报单频率、报撤单比有风控限制，禁止高频报撤单行为；
- 实盘前必须在模拟环境完整验证：下单、成交回报、撤单、对账全链路；
- 本项目为课程作业，默认全部使用模拟通道，实盘风险自负。
