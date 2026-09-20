const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const state = { bootstrap: null, result: null, broker: null, brokerTable: "filled", historyReport: null, historyTable: "trades", historyPage: 1, historyPageSize: 10 };
const titles = { overview: "策略作战总览", backtest: "历史回测实验室", broker: "模拟券商交易台", ai: "DeepSeek 标的分析", history: "回测历史档案", activity: "券商交易记录" };
const strategyFields = {
  dual_moving_average: [["short_window", "短均线周期", 5, 1], ["long_window", "长均线周期", 20, 2]],
  rsi: [["period", "RSI 周期", 14, 1], ["oversold", "超卖阈值", 30, 0], ["overbought", "超买阈值", 70, 1]],
  macd: [["fast_period", "快线周期", 12, 1], ["slow_period", "慢线周期", 26, 2], ["signal_period", "信号周期", 9, 1]],
  bollinger: [["period", "计算周期", 20, 2], ["std_multiplier", "标准差倍数", 2, 0.1]],
};
const strategyDescriptions = {
  dual_moving_average: "短均线上穿长均线买入，下穿卖出；适合观察中期趋势，不会每天重复下单。",
  rsi: "RSI 进入超卖区买入、进入超买区卖出；偏均值回归，震荡行情更容易触发。",
  macd: "MACD 线上穿信号线买入、下穿卖出；偏趋势跟随，信号通常比短均线更慢。",
  bollinger: "价格跌破下轨买入、升破上轨卖出；偏均值回归，单边行情可能长时间不交易。",
};

function navigate(view) {
  $$(".nav-item").forEach(item => item.classList.toggle("active", item.dataset.view === view));
  $$(".view").forEach(item => item.classList.toggle("active", item.id === `view-${view}`));
  $("#page-title").textContent = titles[view];
  history.replaceState(null, "", `#${view}`);
}

function notice(message, success = false) {
  const box = $("#notice");
  $("span", box).textContent = message;
  box.classList.remove("hidden", "success");
  if (success) box.classList.add("success");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function money(value) { return new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY", maximumFractionDigits: 2 }).format(value || 0); }
function brokerMoney(value) {
  const currency = state.broker?.broker_market === "HK" ? "HKD" : state.broker?.broker_market === "US" ? "USD" : "CNY";
  return new Intl.NumberFormat("zh-CN", { style: "currency", currency, maximumFractionDigits: 2 }).format(value || 0);
}
function percent(value) { return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(2)}%`; }
function number(value, digits = 2) { return Number(value || 0).toFixed(digits); }
function shortDate(value) { return value ? value.slice(0, 10) : "—"; }
function symbolLabel(symbol) {
  const name = state.bootstrap?.symbol_names?.[symbol];
  return name && name !== symbol ? `${name}（${symbol}）` : symbol;
}
function quoteTime(value) {
  if (!value) return "—";
  if (/^\d{14}$/.test(value)) return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)} ${value.slice(8, 10)}:${value.slice(10, 12)}:${value.slice(12, 14)}`;
  return value.replace("T", " ").slice(0, 19);
}

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  let body;
  try { body = await response.json(); } catch { throw new Error("服务返回了无法解析的响应"); }
  if (!response.ok) throw new Error(body.error || `请求失败（${response.status}）`);
  return body;
}

function renderStrategyFields() {
  const selected = $("#strategy").value;
  const fields = strategyFields[selected] || [];
  $("#strategy-fields").innerHTML = fields.map(([name, label, value, min]) => `<label>${label}<input type="number" name="${name}" value="${value}" min="${min}" step="${name.includes("multiplier") ? ".1" : "1"}"></label>`).join("");
  $("#strategy-description").textContent = strategyDescriptions[selected] || "—";
}

function requestPayload() {
  const form = $("#backtest-form");
  const data = new FormData(form);
  const strategy = data.get("strategy");
  const strategy_params = {};
  for (const [name] of strategyFields[strategy]) strategy_params[name] = Number(data.get(name));
  return {
    symbol: data.get("symbol"), start: data.get("start"), end: data.get("end"), strategy,
    initial_cash: Number(data.get("initial_cash")), target_weight: Number(data.get("target_weight")) / 100,
    strategy_params,
  };
}

function setMetricGrid(selector, values) {
  const cards = $$(".metric", $(selector));
  values.forEach((entry, index) => {
    const element = $("strong", cards[index]);
    element.textContent = entry.text;
    element.classList.toggle("positive", entry.tone === "positive");
    element.classList.toggle("negative", entry.tone === "negative");
    if (entry.small) $("small", cards[index]).textContent = entry.small;
  });
}

function metricTone(value) { return value >= 0 ? "positive" : "negative"; }

function renderResults(data) {
  state.result = data;
  const m = data.result.metrics;
  const metrics = [
    { text: percent(m.total_return), tone: metricTone(m.total_return) },
    // 后端以正数保存回撤幅度；页面用负号展示，符合“从历史高点下跌”的直觉。
    { text: percent(-m.max_drawdown), tone: m.max_drawdown <= .15 ? "positive" : "negative" },
    { text: number(m.sharpe_ratio), tone: metricTone(m.sharpe_ratio) },
    { text: percent(m.win_rate), tone: "positive" },
  ];
  setMetricGrid("#result-metrics", metrics);
  setMetricGrid("#overview-metrics", [metrics[0], metrics[1], metrics[2], { text: String(m.trade_count), tone: "positive", small: `${m.closed_trade_count} 个完整持仓周期` }]);
  $("#result-period").textContent = `${symbolLabel(data.summary.symbol)} · ${data.summary.start} → ${data.summary.end} · ${data.summary.bar_count} BAR`;
  $("#snapshot-id").textContent = `SNAPSHOT ${data.summary.snapshot_id.toUpperCase()}`;
  $("#benchmark-label").textContent = `买入持有 ${percent(data.summary.benchmark_return)}`;
  const warnings = data.summary.data_warnings.length;
  $("#result-detail").textContent = `最终资产 ${money(m.final_equity)} · 年化收益 ${percent(m.annualized_return)} · 基准收益 ${percent(data.summary.benchmark_return)} · 总费用 ${money(m.total_fees)} · 拒绝订单 ${data.summary.rejected_order_count} · 数据告警 ${warnings}`;
  drawChart(data.result.equity_curve, data.benchmark_curve);
}

function downsample(points, max = 420) {
  if (points.length <= max) return points;
  const step = (points.length - 1) / (max - 1);
  return Array.from({ length: max }, (_, i) => points[Math.round(i * step)]);
}

function drawChart(strategy, benchmark) {
  const svg = $("#equity-chart");
  if (!strategy.length) { svg.innerHTML = '<text x="450" y="165" text-anchor="middle">所选区间没有净值数据</text>'; return; }
  const s = downsample(strategy), b = downsample(benchmark);
  const values = [...s, ...b].map(point => point.total_equity);
  let min = Math.min(...values), max = Math.max(...values);
  const pad = Math.max((max - min) * .15, max * .005); min -= pad; max += pad;
  const x = (index, length) => 58 + index / Math.max(1, length - 1) * 815;
  const y = value => 285 - (value - min) / Math.max(1, max - min) * 240;
  const line = points => points.map((point, i) => `${i ? "L" : "M"}${x(i, points.length).toFixed(1)},${y(point.total_equity).toFixed(1)}`).join(" ");
  const grid = Array.from({ length: 5 }, (_, i) => { const yy = 45 + i * 60; const value = max - i / 4 * (max - min); return `<line class="grid" x1="58" y1="${yy}" x2="873" y2="${yy}"/><text x="4" y="${yy + 4}">${(value / 10000).toFixed(1)}万</text>`; }).join("");
  const sPath = line(s), bPath = line(b);
  const area = `${sPath} L${x(s.length - 1, s.length)},285 L58,285 Z`;
  svg.innerHTML = `<defs><linearGradient id="areaGradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#1769e0" stop-opacity=".20"/><stop offset="1" stop-color="#1769e0" stop-opacity="0"/></linearGradient></defs>${grid}<path class="area" d="${area}"/><path class="benchmark-line" d="${bPath}"/><path class="strategy-line" d="${sPath}"/>`;
}

function renderBrokerActivity() {
  const orders = state.broker?.orders || [];
  const rows = state.brokerTable === "filled" ? orders.filter(row => row.status === "FILLED") : orders;
  $("#activity-head").innerHTML = "<tr><th>提交时间</th><th>券商订单号</th><th>方向</th><th>标的</th><th>数量</th><th>成交价</th><th>状态 / 原因</th></tr>";
  $("#activity-body").innerHTML = rows.length ? [...rows].reverse().map(row => `<tr><td>${quoteTime(row.created_at)}</td><td>${row.order_id}</td><td class="${row.side.toLowerCase()}">${row.side}</td><td>${symbolLabel(row.symbol)}</td><td>${row.quantity}</td><td>${row.price == null ? "—" : number(row.price, 3)}</td><td class="status-${row.status.toLowerCase()}">${row.status}${row.reject_reason ? ` · ${row.reject_reason}` : ""}</td></tr>`).join("") : `<tr><td class="empty" colspan="7">${state.brokerTable === "filled" ? "当前券商会话还没有成交" : "当前券商会话还没有订单"}</td></tr>`;
}

async function runBacktest(event) {
  event.preventDefault(); const button = $("#run-button"); button.disabled = true; $("span", button).textContent = "正在调用交易内核…";
  try {
    const data = await api("/api/backtest", { method: "POST", body: JSON.stringify(requestPayload()) });
    renderResults(data); await refreshHistory();
    const saved = data.history ? `，已保存为 ${data.history.id}` : "";
    notice(`快速回测完成：${data.summary.bar_count} 根日 K，${data.result.metrics.trade_count} 笔成交，用时 ${data.summary.elapsed_ms} ms${saved}。`, true);
  } catch (error) { notice(error.message); }
  finally { button.disabled = false; $("span", button).textContent = "一键快速回测"; }
}

function renderBroker(data) {
  state.broker = data;
  const external = data.is_external_simulation;
  $("#broker-status").textContent = external ? "已连接" : (data.trading_session.is_open ? "交易时段" : "休市");
  $("#broker-status").classList.toggle("cyan", data.trading_session.is_open);
  $("#broker-status").title = data.trading_session.message;
  $("#broker-session-message").textContent = data.trading_session.message;
  $("#broker-market-source").textContent = `${data.market_data.source}${data.market_data.quote_time ? `（${quoteTime(data.market_data.quote_time)}）` : ""}`;
  $("#side-broker-data").textContent = data.market_data.source;
  $("#broker-heading").textContent = external ? `富途${data.broker_market}模拟盘` : "本地模拟券商";
  $("#broker-description").firstChild.textContent = external
    ? "当前订单直接提交到富途 OpenD 官方模拟账户；不会使用本地 PaperBroker 撮合。"
    : "当前使用 PaperBroker 本地模拟账户。仅在 A 股交易日的 09:30–11:30、13:00–15:00 且联网行情为当天时允许成交。";
  $("#broker-reset").disabled = external;
  const symbolInput = $("#broker-symbol");
  if (external && !symbolInput.value.toUpperCase().endsWith(`.${data.broker_market}`)) symbolInput.value = data.broker_market === "HK" ? "0700.HK" : "AAPL.US";
  if (!external && !state.bootstrap.symbols.includes(symbolInput.value)) symbolInput.value = state.bootstrap.symbols[0];
  applyBrokerLotSize();
  setMetricGrid("#broker-metrics", [
    { text: brokerMoney(data.total_equity), tone: "positive" },
    { text: brokerMoney(data.cash) },
    { text: brokerMoney(data.market_value) },
  ]);
  $("#broker-positions").innerHTML = data.positions.length ? data.positions.map(row => `<tr><td>${symbolLabel(row.symbol)}</td><td>${row.quantity}</td><td>${number(row.average_cost, 3)}</td><td>${number(row.last_price, 3)}</td><td>${brokerMoney(row.market_value)}</td><td class="${row.unrealized_pnl >= 0 ? "buy" : "sell"}">${brokerMoney(row.unrealized_pnl)}</td></tr>`).join("") : '<tr><td class="empty" colspan="6">暂无持仓</td></tr>';
  renderBrokerActivity();
}

async function refreshBrokerState(showError = false) {
  try { renderBroker(await api("/api/broker/state")); }
  catch (error) { if (showError) notice(`模拟券商刷新失败：${error.message}`); }
}

function renderAiMarket(data) {
  $("#ai-data-source").textContent = data.is_realtime_quote ? "真实行情" : "历史数据兜底";
  $("#ai-data-source").classList.toggle("cyan", data.is_realtime_quote);
  $("#ai-quote-time").textContent = quoteTime(data.quote_time);
  $("#ai-price").textContent = number(data.price, 3);
  $("#ai-return").textContent = data.return_20d == null ? "—" : percent(data.return_20d);
  $("#ai-volatility").textContent = data.annualized_volatility_60d == null ? "—" : percent(data.annualized_volatility_60d);
}

async function refreshAiMarket() {
  const symbol = $("#ai-symbol").value;
  if (!symbol) return;
  try { renderAiMarket(await api(`/api/market/snapshot?symbol=${encodeURIComponent(symbol)}`)); }
  catch (error) { notice(`行情读取失败：${error.message}`); }
}

async function analyzeSymbol(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const payload = { symbol: form.get("symbol"), api_key: form.get("api_key"), question: form.get("question") };
  const button = $("#ai-submit"); button.disabled = true; $("span", button).textContent = "DeepSeek 分析中…";
  $("#ai-answer").textContent = "正在汇总行情并等待 DeepSeek 返回，请稍候…";
  try {
    const data = await api("/api/ai/analyze", { method: "POST", body: JSON.stringify(payload) });
    renderAiMarket(data.market_context);
    $("#ai-model").textContent = `${data.model} · ${data.usage.total_tokens || 0} TOKENS`;
    $("#ai-answer").textContent = data.answer;
    notice(`${data.symbol} 的 AI 分析已完成。`, true);
  } catch (error) { $("#ai-answer").textContent = `分析失败：${error.message}`; notice(error.message); }
  finally { button.disabled = false; $("span", button).textContent = "开始分析"; }
}

function strategyName(id) {
  return state.bootstrap?.strategies.find(item => item.id === id)?.name || id;
}

async function refreshHistory() {
  try {
    const data = await api("/api/backtests");
    $("#history-location").textContent = data.persistence_enabled ? `已保存 ${data.items.length} 次` : "保存功能未启用";
    $("#history-body").innerHTML = data.items.length ? data.items.map(row => `<tr><td>${new Date(row.created_at).toLocaleString("zh-CN", { hour12: false })}</td><td>${symbolLabel(row.symbol)}</td><td>${strategyName(row.strategy)}</td><td>${row.start} → ${row.end}</td><td class="${row.total_return >= 0 ? "buy" : "sell"}">${percent(row.total_return)}</td><td class="sell">${percent(-row.max_drawdown)}</td><td>${row.trade_count}</td><td><button class="table-action" data-history-open="${row.id}">回测结果</button><button class="table-action" data-history-records="${row.id}">交易明细</button><button class="table-action danger" data-history-delete="${row.id}">删除</button></td></tr>`).join("") : '<tr><td class="empty" colspan="8">还没有已保存的回测，先运行一次快速回测</td></tr>';
  } catch (error) { $("#history-body").innerHTML = `<tr><td class="empty" colspan="8">读取失败：${error.message}</td></tr>`; }
}

async function openHistory(historyId) {
  try {
    const data = await api(`/api/backtests/${historyId}`);
    renderResults(data); navigate("backtest");
    notice(`已打开 ${data.history.created_at} 保存的回测结果。`, true);
  } catch (error) { notice(error.message); }
}

async function openHistoryRecords(historyId) {
  try {
    state.historyReport = await api(`/api/backtests/${historyId}`);
    state.historyTable = "trades"; state.historyPage = 1;
    $$('[data-history-table]').forEach(button => button.classList.toggle("active", button.dataset.historyTable === "trades"));
    $("#history-detail").classList.remove("hidden");
    $("#history-detail-title").textContent = `${symbolLabel(state.historyReport.summary.symbol)} · ${strategyName(state.historyReport.history.request.strategy)} · 交易明细`;
    renderHistoryRecords();
    $("#history-detail").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) { notice(error.message); }
}

function renderHistoryRecords() {
  if (!state.historyReport) return;
  const rows = state.historyReport.result[state.historyTable] || [];
  const pages = Math.max(1, Math.ceil(rows.length / state.historyPageSize));
  state.historyPage = Math.min(Math.max(1, state.historyPage), pages);
  const start = (state.historyPage - 1) * state.historyPageSize;
  const pageRows = rows.slice(start, start + state.historyPageSize);
  if (state.historyTable === "trades") {
    $("#history-detail-head").innerHTML = "<tr><th>成交时间</th><th>成交编号</th><th>方向</th><th>标的</th><th>数量</th><th>成交价</th><th>手续费</th><th>印花税</th></tr>";
    $("#history-detail-body").innerHTML = pageRows.length ? pageRows.map(row => `<tr><td>${shortDate(row.datetime)}</td><td>${row.trade_id}</td><td class="${row.side.toLowerCase()}">${row.side}</td><td>${symbolLabel(row.symbol)}</td><td>${row.quantity}</td><td>${number(row.price, 3)}</td><td>${money(row.commission)}</td><td>${money(row.stamp_duty)}</td></tr>`).join("") : '<tr><td class="empty" colspan="8">该回测没有成交</td></tr>';
  } else {
    $("#history-detail-head").innerHTML = "<tr><th>创建时间</th><th>订单编号</th><th>方向</th><th>标的</th><th>数量</th><th>状态</th><th>价格</th><th>拒绝原因</th></tr>";
    $("#history-detail-body").innerHTML = pageRows.length ? pageRows.map(row => `<tr><td>${shortDate(row.created_at)}</td><td>${row.order_id}</td><td class="${row.side.toLowerCase()}">${row.side}</td><td>${symbolLabel(row.symbol)}</td><td>${row.quantity}</td><td class="status-${row.status.toLowerCase()}">${row.status}</td><td>${row.price == null ? "—" : number(row.price, 3)}</td><td>${row.reject_reason || "—"}</td></tr>`).join("") : '<tr><td class="empty" colspan="8">该回测没有订单</td></tr>';
  }
  $("#history-page").textContent = `第 ${state.historyPage} / ${pages} 页 · 共 ${rows.length} 条`;
  $("#history-prev").disabled = state.historyPage <= 1;
  $("#history-next").disabled = state.historyPage >= pages;
}

async function deleteHistory(historyId) {
  if (!window.confirm("确定删除这条回测历史吗？删除后无法恢复。")) return;
  try {
    await api(`/api/backtests/${historyId}`, { method: "DELETE" });
    if (state.historyReport?.history?.id === historyId) { state.historyReport = null; $("#history-detail").classList.add("hidden"); }
    await refreshHistory(); notice("回测历史已删除。", true);
  } catch (error) { notice(error.message); }
}

async function resetBroker() {
  try {
    const data = await api("/api/broker/reset", { method: "POST", body: JSON.stringify({ initial_cash: 1_000_000 }) });
    renderBroker(data); notice("模拟券商账户已重置，资金为 100 万元。", true);
  } catch (error) { notice(error.message); }
}

async function connectBroker(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const payload = { gateway: form.get("gateway"), initial_cash: 1_000_000 };
  if (payload.gateway === "futu") Object.assign(payload, { host: form.get("host"), port: Number(form.get("port")), market: form.get("market"), account_id: form.get("account_id") });
  const button = $("#broker-connect"); button.disabled = true;
  try {
    const data = await api("/api/broker/connect", { method: "POST", body: JSON.stringify(payload) });
    renderBroker(data);
    notice(data.gateway === "futu" ? "富途 OpenD 官方模拟盘连接成功。" : "已切换到本地 PaperBroker。", true);
  } catch (error) { notice(error.message); }
  finally { button.disabled = false; }
}

async function submitBrokerOrder(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const payload = { symbol: form.get("symbol"), side: form.get("side"), order_type: form.get("order_type"), quantity: Number(form.get("quantity")) };
  if (payload.order_type === "limit") payload.price = Number(form.get("price"));
  const button = $("#broker-submit"); button.disabled = true;
  try {
    const data = await api("/api/broker/order", { method: "POST", body: JSON.stringify(payload) });
    renderBroker(data);
    const order = data.submitted_order;
    const message = order.status === "FILLED" ? `模拟订单已成交：${order.side} ${order.quantity} 股 ${order.symbol}。` : order.status === "REJECTED" ? `订单被拒绝：${order.reject_reason}` : `订单已提交：${order.order_id}，当前状态 ${order.status}。`;
    notice(message, order.status !== "REJECTED");
  } catch (error) { notice(error.message); }
  finally { button.disabled = false; }
}

async function bootstrap() {
  try {
    const data = await api("/api/bootstrap"); state.bootstrap = data;
    $("#side-backtest-data").textContent = data.data_file; $("#side-frequency").textContent = data.rules.bar_frequency.toUpperCase();
    $("#bar-count").textContent = data.bar_count.toLocaleString("zh-CN"); $("#date-range").textContent = `${data.date_min}—${data.date_max}`;
    $("#symbol-count").textContent = data.symbols.length; $("#data-warning-count").textContent = `${data.data_quality.warning_count} 条`;
    const symbolOptions = data.symbols.map(symbol => `<option value="${symbol}">${symbolLabel(symbol)}</option>`).join("");
    $("#symbol").innerHTML = symbolOptions; $("#broker-symbol-list").innerHTML = symbolOptions; $("#broker-symbol").value = data.symbols[0]; $("#ai-symbol").innerHTML = symbolOptions;
    applyBrokerLotSize();
    $("#strategy").innerHTML = data.strategies.map(strategy => `<option value="${strategy.id}">${strategy.name}</option>`).join("");
    applySymbolRange(true);
    $("#initial-cash").value = data.config.backtest.initial_cash; $("#target-weight").value = data.config.strategy.target_weight * 100;
    $("#execution-rule").textContent = data.rules.execution;
    renderStrategyFields();
    await refreshBrokerState(true);
    await refreshAiMarket();
    await refreshHistory();
  } catch (error) { notice(`初始化失败：${error.message}`); }
}

function applySymbolRange(reset = false) {
  const range = state.bootstrap?.symbol_ranges?.[$("#symbol").value];
  if (!range) return;
  $("#start").min = $("#end").min = range.date_min; $("#start").max = $("#end").max = range.date_max;
  if (reset || !$("#start").value || $("#start").value < range.date_min || $("#start").value > range.date_max) $("#start").value = range.date_min;
  if (reset || !$("#end").value || $("#end").value < range.date_min || $("#end").value > range.date_max) $("#end").value = range.date_max;
  $("#backtest-data-rule").textContent = `${state.bootstrap.data_file} · ${range.date_min} 至 ${range.date_max} · ${range.bar_count} 根腾讯前复权日 K`;
}

function applyBrokerLotSize() {
  if (state.broker?.is_external_simulation) {
    const input = $("#broker-quantity"); input.min = input.step = 1;
    $("#broker-quantity-label").childNodes[0].textContent = "数量（由富途校验每手股数）";
    return;
  }
  const lot = state.bootstrap?.lot_sizes?.[$("#broker-symbol").value] || 100;
  const input = $("#broker-quantity"); input.min = input.step = lot;
  if (Number(input.value) % lot !== 0) input.value = lot;
  $("#broker-quantity-label").childNodes[0].textContent = `数量（${lot} 股整数倍）`;
}

function init() {
  $$(".nav-item").forEach(item => item.addEventListener("click", () => navigate(item.dataset.view)));
  $$('[data-jump]').forEach(item => item.addEventListener("click", () => navigate(item.dataset.jump)));
  $("#notice button").addEventListener("click", () => $("#notice").classList.add("hidden"));
  $("#strategy").addEventListener("change", renderStrategyFields); $("#symbol").addEventListener("change", () => applySymbolRange(true)); $("#backtest-form").addEventListener("submit", runBacktest);
  $("#broker-connect-form").addEventListener("submit", connectBroker);
  $("#broker-gateway").addEventListener("change", event => $("#futu-fields").classList.toggle("hidden", event.target.value !== "futu"));
  $("#broker-form").addEventListener("submit", submitBrokerOrder); $("#broker-reset").addEventListener("click", resetBroker); $("#broker-refresh").addEventListener("click", () => refreshBrokerState(true));
  $("#broker-order-type").addEventListener("change", event => { $("#broker-price").disabled = event.target.value !== "limit"; }); $("#broker-symbol").addEventListener("change", applyBrokerLotSize);
  $("#ai-form").addEventListener("submit", analyzeSymbol); $("#ai-symbol").addEventListener("change", refreshAiMarket);
  $("#history-refresh").addEventListener("click", refreshHistory);
  $("#history-body").addEventListener("click", event => {
    const open = event.target.closest("[data-history-open]");
    const records = event.target.closest("[data-history-records]");
    const remove = event.target.closest("[data-history-delete]");
    if (open) openHistory(open.dataset.historyOpen);
    if (records) openHistoryRecords(records.dataset.historyRecords);
    if (remove) deleteHistory(remove.dataset.historyDelete);
  });
  $$('[data-history-table]').forEach(button => button.addEventListener("click", () => { $$('[data-history-table]').forEach(x => x.classList.remove("active")); button.classList.add("active"); state.historyTable = button.dataset.historyTable; state.historyPage = 1; renderHistoryRecords(); }));
  $("#history-prev").addEventListener("click", () => { state.historyPage -= 1; renderHistoryRecords(); });
  $("#history-next").addEventListener("click", () => { state.historyPage += 1; renderHistoryRecords(); });
  $$('[data-broker-table]').forEach(button => button.addEventListener("click", () => { $$('[data-broker-table]').forEach(x => x.classList.remove("active")); button.classList.add("active"); state.brokerTable = button.dataset.brokerTable; renderBrokerActivity(); }));
  setInterval(() => $("#clock").textContent = new Date().toLocaleTimeString("zh-CN", { hour12: false }), 1000);
  const requested = location.hash.slice(1); if (titles[requested]) navigate(requested);
  if (location.protocol === "file:") {
    notice("页面样式已加载，但回测功能需要 Python 服务。请在仓库根目录运行：PYTHONPATH=src python3 -m quant_demo.web，然后访问 http://127.0.0.1:8000");
    return;
  }
  bootstrap();
}

document.addEventListener("DOMContentLoaded", init);
