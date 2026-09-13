export const researchUniverse = [
  { code: '601398.SH', name: '工商银行', sector: '银行', tag: '大盘股 · 红利候选' },
  { code: '601939.SH', name: '建设银行', sector: '银行', tag: '大盘股 · 红利候选' },
  { code: '601288.SH', name: '农业银行', sector: '银行', tag: '大盘股 · 红利候选' },
  { code: '601988.SH', name: '中国银行', sector: '银行', tag: '大盘股 · 红利候选' },
  { code: '601088.SH', name: '中国神华', sector: '煤炭', tag: '大盘股 · 红利候选' },
  { code: '600900.SH', name: '长江电力', sector: '电力', tag: '大盘股 · 红利候选' },
  { code: '600028.SH', name: '中国石化', sector: '石油石化', tag: '大盘股 · 红利候选' },
  { code: '601857.SH', name: '中国石油', sector: '石油石化', tag: '大盘股 · 红利候选' },
  { code: '600036.SH', name: '招商银行', sector: '银行', tag: '大盘股 · 红利候选' },
  { code: '600585.SH', name: '海螺水泥', sector: '建筑材料', tag: '大盘股 · 红利候选' },
]

// These are UI seed records, not claims about current valuation, index membership,
// dividend yield, or live prices. Before the final demo, A should provide the
// authoritative universe and historical data source used by the group.
export const demoMetrics = {
  initialCash: 1000000,
  finalEquity: 1000000,
  totalReturn: null,
  annualizedReturn: null,
  maxDrawdown: null,
  sharpe: null,
  trades: 0,
  dataPeriod: '待接入真实历史数据',
}

export const strategy = {
  name: '大盘红利趋势低频策略',
  version: 'Web Demo V2',
  frequency: '日线',
  style: '低频 · 纯多头',
  universe: '沪深 A 股大盘股 + 红利候选池',
  selection: '先限定研究股票池，再以趋势信号决定是否交易',
  signal: 'MA5 上穿 MA20 买入，MA5 下穿 MA20 卖出',
  shortWindow: 5,
  longWindow: 20,
  targetWeight: 0.2,
  maxSymbolWeight: 0.3,
  execution: '收盘产生信号，下一根日 K 开盘模拟成交',
  dataPeriod: '最终答辩前由真实历史数据回测确定',
}
