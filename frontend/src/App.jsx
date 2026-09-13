import { useMemo, useState } from 'react'
import { researchUniverse, strategy, demoMetrics } from './mock/demo'

const nav = [
  ['dashboard', '总览'],
  ['market', '股票行情'],
  ['ai', 'AI预测'],
  ['stockpick', '智能选股'],
  ['universe', '研究股票池'],
  ['backtest', '历史回测'],
  ['simulation', '模拟盘'],
  ['orders', '订单与成交'],
]

const market = [
  { code: '600519.SH', name: '贵州茅台', price: '1,450.20', change: '+1.82%', score: 92, signal: '买入', risk: '中' },
  { code: '601398.SH', name: '工商银行', price: '6.42', change: '+0.94%', score: 89, signal: '买入', risk: '低' },
  { code: '601939.SH', name: '建设银行', price: '8.16', change: '+0.61%', score: 87, signal: '持有', risk: '低' },
  { code: '601088.SH', name: '中国神华', price: '38.52', change: '+1.35%', score: 91, signal: '买入', risk: '中' },
  { code: '600900.SH', name: '长江电力', price: '28.73', change: '+0.48%', score: 86, signal: '持有', risk: '低' },
]

const prediction = { up: 72, down: 28, target: '1,492.00', confidence: 82, risk: 34 }

function Metric({ label, value, note }) {
  return <div className="metric"><span>{label}</span><strong>{value}</strong>{note && <small>{note}</small>}</div>
}

function LineChart({ compact = false }) {
  const points = [24, 21, 26, 25, 31, 29, 35, 33, 39, 43, 41, 48, 46, 53, 58, 55, 62, 67, 64, 72]
  const max = Math.max(...points)
  const path = points.map((v, i) => `${(i / (points.length - 1)) * 100},${100 - (v / max) * 78 - 8}`).join(' ')
  return <div className={`chart ${compact ? 'compact-chart' : ''}`}><svg viewBox="0 0 100 100" preserveAspectRatio="none"><polyline points={path} fill="none" stroke="currentColor" strokeWidth="1.8" vectorEffect="non-scaling-stroke" /></svg><div className="axis"><span>回测开始</span><span>最新</span></div></div>
}

function Dashboard({ setPage }) {
  return <>
    <section className="hero">
      <div><div className="eyebrow">LOW-FREQUENCY A-SHARE QUANT</div><h1>智能证券交易<br /><em>低频大盘 · 红利策略</em></h1><p>从研究股票池、AI辅助分析，到历史回测、智能信号和模拟成交，完整展示 E 部分可演示的量化投资闭环。</p></div>
      <div className="status"><span className="dot" />模拟环境 · 就绪<div>策略：{strategy.name}</div><small>MA{strategy.shortWindow} / MA{strategy.longWindow} · 日线</small></div>
    </section>
    <div className="metrics"><Metric label="模拟初始资金" value="¥1,000,000" /><Metric label="策略累计收益" value="待真实回测" note="不虚构历史收益" /><Metric label="最大回撤" value="待真实回测" /><Metric label="AI市场信号" value="偏多" note="演示数据" /></div>
    <div className="grid two">
      <section className="panel"><div className="panel-head"><div><span className="eyebrow">PERFORMANCE</span><h2>策略净值曲线</h2></div><button onClick={() => setPage('backtest')}>进入回测 →</button></div><LineChart /><div className="notice">当前曲线为界面演示占位，不代表历史收益。正式答辩时将由真实多年 A 股数据和后端回测结果自动替换。</div></section>
      <section className="panel"><div className="panel-head"><div><span className="eyebrow">TODAY'S SIGNALS</span><h2>今日智能信号</h2></div><span className="pill">演示模式</span></div><div className="signal-list">{market.slice(0, 4).map(s => <div className="signal-row" key={s.code}><div><strong>{s.name}</strong><small>{s.code} · AI评分 {s.score}</small></div><b>{s.signal}</b><span>{s.change}</span></div>)}</div></section>
    </div>
    <div className="grid three"><section className="panel mini"><span className="eyebrow">WORKFLOW 01</span><h3>股票筛选</h3><p>沪深 A 股 → 大盘股 / 红利研究池 → 技术条件过滤</p></section><section className="panel mini"><span className="eyebrow">WORKFLOW 02</span><h3>策略决策</h3><p>MA5 / MA20 信号 → 仓位管理 → 风控检查</p></section><section className="panel mini"><span className="eyebrow">WORKFLOW 03</span><h3>模拟交易</h3><p>信号 → 模拟订单 → 撮合成交 → 账户净值</p></section></div>
  </>
}

function Market() {
  return <section className="panel full"><div className="panel-head"><div><span className="eyebrow">A-SHARE MARKET</span><h2>沪深 A 股行情</h2><p>演示市场行情、技术信号与 AI 评分的统一入口。真实行情接入后替换当前演示数据。</p></div><span className="count">沪 · 深 · 创 · 科创</span></div><div className="index-strip"><div><span>上证指数</span><b>3,245.61</b><em>+0.82%</em></div><div><span>深证成指</span><b>10,432.18</b><em>+1.14%</em></div><div><span>创业板指</span><b>2,118.55</b><i>-0.36%</i></div><div><span>科创50</span><b>1,024.73</b><em>+0.65%</em></div></div><div className="table-wrap"><table><thead><tr><th>代码</th><th>名称</th><th>最新价</th><th>涨跌幅</th><th>AI评分</th><th>策略信号</th><th>风险</th></tr></thead><tbody>{market.map(s => <tr key={s.code}><td className="mono">{s.code}</td><td><strong>{s.name}</strong></td><td>{s.price}</td><td className="up">{s.change}</td><td><span className="score">{s.score}</span></td><td><span className="signal-badge">{s.signal}</span></td><td>{s.risk}</td></tr>)}</tbody></table></div></section>
}

function AI() {
  return <div className="grid two"><section className="panel"><span className="eyebrow">AI PREDICTION</span><h2>贵州茅台 · AI 股票预测</h2><div className="prediction-main"><div className="ring"><strong>{prediction.up}%</strong><span>上涨概率</span></div><div><div className="big-signal">上涨 ↑</div><p>模型置信度 <b>{prediction.confidence}%</b></p><div className="bar"><i style={{ width: `${prediction.up}%` }} /></div><small>下跌概率 {prediction.down}%</small></div></div><div className="result-grid"><Metric label="未来价格预测" value={`¥${prediction.target}`} /><Metric label="风险评分" value={`${prediction.risk}/100`} /><Metric label="操作建议" value="买入" /><Metric label="预测周期" value="下一交易日" /></div><div className="notice">AI 模块为前端演示位，正式接入后直接读取团队模型输出：涨跌预测、未来价格、买卖建议、风险评分。</div></section><section className="panel"><span className="eyebrow">TECHNICAL VIEW</span><h2>技术指标</h2><LineChart compact /><div className="indicator-grid"><div><span>MA5</span><b>1,438.20</b></div><div><span>MA20</span><b>1,421.60</b></div><div><span>MACD</span><b className="up">+12.6</b></div><div><span>RSI</span><b>64.2</b></div></div></section></div>
}

function StockPick({ setPage }) {
  return <section className="panel full"><div className="panel-head"><div><span className="eyebrow">SMART STOCK PICKING</span><h2>智能选股推荐</h2><p>综合研究池标签、技术信号和 AI 评分，形成可解释的候选排名。</p></div><button onClick={() => setPage('universe')}>查看研究池 →</button></div><div className="pick-grid">{market.map((s, i) => <div className="pick-card" key={s.code}><span className="rank">0{i + 1}</span><div><strong>{s.name}</strong><small>{s.code} · {researchUniverse.find(x => x.code === s.code)?.sector || '研究池'}</small></div><b>{s.score}</b><span>AI评分</span><p>策略建议：{s.signal} · 风险：{s.risk}</p></div>)}</div><div className="notice">排名是产品演示逻辑，不构成真实投资建议；正式版本应由后端模型/策略服务提供评分与解释字段。</div></section>
}

function Universe() {
  return <section className="panel full"><div className="panel-head"><div><span className="eyebrow">RESEARCH UNIVERSE</span><h2>沪深 A 股大盘 / 红利研究池</h2><p>当前已建立至少 10 个标的的前端展示入口，后续由数据服务提供动态股票池。</p></div><span className="count">{researchUniverse.length} 个标的</span></div><div className="table-wrap"><table><thead><tr><th>代码</th><th>名称</th><th>行业</th><th>研究标签</th></tr></thead><tbody>{researchUniverse.map(s => <tr key={s.code}><td className="mono">{s.code}</td><td><strong>{s.name}</strong></td><td>{s.sector}</td><td><span className="tag">{s.tag}</span></td></tr>)}</tbody></table></div></section>
}

function Backtest({ onRun, result }) {
  const [years, setYears] = useState('2021-2025')
  const [short, setShort] = useState(strategy.shortWindow)
  const [long, setLong] = useState(strategy.longWindow)
  return <div className="grid two"><section className="panel"><span className="eyebrow">BACKTEST CONFIG</span><h2>历史回测</h2><p>前端只负责配置和展示，真实计算由后端回测引擎完成。</p><div className="form"><label>历史数据区间<select value={years} onChange={e => setYears(e.target.value)}><option>2021-2025</option><option>2020-2025</option><option>2019-2025</option><option>自定义</option></select></label><label>短均线<input type="number" value={short} onChange={e => setShort(Number(e.target.value))} /></label><label>长均线<input type="number" value={long} onChange={e => setLong(Number(e.target.value))} /></label><label>初始资金<input value="¥1,000,000" disabled /></label><button className="primary" onClick={() => onRun(years, short, long)}>运行策略回测</button></div></section><section className="panel"><span className="eyebrow">BACKTEST RESULT</span><h2>{result ? '回测任务已提交' : '回测结果'}</h2><div className="result-grid"><Metric label="累计收益" value={result ? '待后端计算' : '待计算'} /><Metric label="年化收益" value="待计算" /><Metric label="最大回撤" value="待计算" /><Metric label="交易次数" value="待计算" /></div><div className="backtest-box"><span>数据区间</span><b>{result?.years || '未运行'}</b><span>参数</span><b>{result ? `MA${result.short} / MA${result.long}` : 'MA5 / MA20'}</b></div><div className="notice">“这几年赚了多少个点”必须由真实历史数据回测产生。当前页面不会伪造收益数字。</div></section></div>
}

function Simulation({ running, setRunning }) {
  const [cash, setCash] = useState(1000000)
  const [holding, setHolding] = useState(0)
  const trade = () => { if (!running) setRunning(true); setCash(cash - 145020); setHolding(100) }
  return <div className="grid two"><section className="panel"><span className="eyebrow">SIMULATION MODE</span><h2>智能模拟盘</h2><p>演示策略信号触发订单、模拟成交和账户更新的完整链路。</p><div className={`sim-state ${running ? 'on' : ''}`}><span className="dot" />{running ? '策略运行中' : '策略已停止'}<strong>{running ? 'RUNNING' : 'STOPPED'}</strong></div><div className="action-row"><button className={running ? 'danger' : 'primary'} onClick={() => setRunning(!running)}>{running ? '停止模拟交易' : '启动模拟交易'}</button><button onClick={trade}>模拟买入 100 股</button></div><div className="chain"><span>策略信号</span><i>→</i><span>风控</span><i>→</i><span>订单</span><i>→</i><span>成交</span><i>→</i><span>账户</span></div></section><section className="panel"><span className="eyebrow">ACCOUNT</span><h2>模拟账户</h2><div className="metrics compact"><Metric label="现金" value={`¥${cash.toLocaleString()}`} /><Metric label="持仓数量" value={`${holding} 股`} /><Metric label="持仓市值" value={`¥${(holding * 1450.2).toLocaleString()}`} /><Metric label="总资产" value={`¥${(cash + holding * 1450.2).toLocaleString()}`} /></div><div className="notice">账户数值仅用于前端交互演示；正式版本应由后端 Simulation Mode 返回。</div></section></div>
}

function Orders() {
  return <section className="panel full"><div className="panel-head"><div><span className="eyebrow">OMS / TRADES</span><h2>订单与成交</h2><p>展示智能交易闭环中的订单、成交和状态。</p></div><span className="pill">模拟环境</span></div><div className="order-demo"><div><span>订单状态</span><b>FILLED</b></div><div><span>标的</span><b>600519.SH · 贵州茅台</b></div><div><span>方向</span><b>BUY</b></div><div><span>数量</span><b>100 股</b></div><div><span>成交价</span><b>¥1,450.20</b></div><div><span>成交状态</span><b className="up">已成交</b></div></div><div className="notice">这是可演示的订单链路样例。接入后端 OMS 后，页面将替换为真实 Order → Trade → Position → Account 数据。</div></section>
}

export default function App() {
  const [page, setPage] = useState('dashboard')
  const [running, setRunning] = useState(false)
  const [toast, setToast] = useState('')
  const [backtestResult, setBacktestResult] = useState(null)
  const title = useMemo(() => nav.find(n => n[0] === page)?.[1] || '总览', [page])
  const run = (years, short, long) => { setBacktestResult({ years, short, long }); setToast(`已提交回测：${years} · MA${short}/MA${long}`); setTimeout(() => setToast(''), 3200) }
  return <div className="app"><aside><div className="brand"><span className="mark">IQ</span><div><strong>INTELLIGENT</strong><small>INVESTMENT</small></div></div><nav>{nav.map(([id, label], i) => <button className={page === id ? 'active' : ''} key={id} onClick={() => setPage(id)}><span>{String(i + 1).padStart(2, '0')}</span>{label}</button>)}</nav><div className="side-foot">E · WEB & INTEGRATION<br /><span>e-web-v2 · simulation</span></div></aside><main><header><span>{title}</span><div className="branch">● e-web-v2</div></header><div className="content">{page === 'dashboard' && <Dashboard setPage={setPage} />}{page === 'market' && <Market />}{page === 'ai' && <AI />}{page === 'stockpick' && <StockPick setPage={setPage} />}{page === 'universe' && <Universe />}{page === 'backtest' && <Backtest onRun={run} result={backtestResult} />}{page === 'simulation' && <Simulation running={running} setRunning={setRunning} />}{page === 'orders' && <Orders />}</div></main>{toast && <div className="toast">{toast}</div>}</div>
}
