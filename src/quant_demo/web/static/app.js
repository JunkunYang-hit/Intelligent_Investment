const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const state = { bootstrap: null, result: null, table: "trades", simTimer: null };
const titles = { overview: "策略作战总览", backtest: "历史回测实验室", simulation: "市场模拟控制台", activity: "交易审计记录" };
const strategyFields = {
  dual_moving_average: [["short_window", "短均线周期", 5, 1], ["long_window", "长均线周期", 20, 2]],
  rsi: [["period", "RSI 周期", 14, 1], ["oversold", "超卖阈值", 30, 0], ["overbought", "超买阈值", 70, 1]],
  macd: [["fast_period", "快线周期", 12, 1], ["slow_period", "慢线周期", 26, 2], ["signal_period", "信号周期", 9, 1]],
  bollinger: [["period", "计算周期", 20, 2], ["std_multiplier", "标准差倍数", 2, 0.1]],
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
function percent(value) { return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(2)}%`; }
function number(value, digits = 2) { return Number(value || 0).toFixed(digits); }
function shortDate(value) { return value ? value.slice(0, 10) : "—"; }

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  let body;
  try { body = await response.json(); } catch { throw new Error("服务返回了无法解析的响应"); }
  if (!response.ok) throw new Error(body.error || `请求失败（${response.status}）`);
  return body;
}

function renderStrategyFields() {
  const fields = strategyFields[$("#strategy").value] || [];
  $("#strategy-fields").innerHTML = fields.map(([name, label, value, min]) => `<label>${label}<input type="number" name="${name}" value="${value}" min="${min}" step="${name.includes("multiplier") ? ".1" : "1"}"></label>`).join("");
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

function metricTone(value, inverse = false) { return (inverse ? value <= 0 : value >= 0) ? "positive" : "negative"; }

function renderResults(data) {
  state.result = data;
  const m = data.result.metrics;
  const metrics = [
    { text: percent(m.total_return), tone: metricTone(m.total_return) },
    { text: percent(-m.max_drawdown), tone: m.max_drawdown < .15 ? "positive" : "negative" },
    { text: number(m.sharpe_ratio), tone: metricTone(m.sharpe_ratio) },
    { text: percent(m.win_rate), tone: "positive" },
  ];
  setMetricGrid("#result-metrics", metrics);
  setMetricGrid("#overview-metrics", [metrics[0], metrics[1], metrics[2], { text: String(m.trade_count), tone: "positive", small: `${m.closed_trade_count} 个完整持仓周期` }]);
  $("#result-period").textContent = `${data.summary.symbol} · ${data.summary.start} → ${data.summary.end} · ${data.summary.bar_count} BAR`;
  $("#snapshot-id").textContent = `SNAPSHOT ${data.summary.snapshot_id.toUpperCase()}`;
  drawChart(data.result.equity_curve, data.benchmark_curve);
  renderActivity();
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
  svg.innerHTML = `<defs><linearGradient id="areaGradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#23e6c1" stop-opacity=".16"/><stop offset="1" stop-color="#23e6c1" stop-opacity="0"/></linearGradient></defs>${grid}<path class="area" d="${area}"/><path class="benchmark-line" d="${bPath}"/><path class="strategy-line" d="${sPath}"/>`;
}

function renderActivity() {
  const result = state.result?.result;
  if (!result) return;
  const rows = result[state.table];
  if (state.table === "trades") {
    $("#activity-head").innerHTML = "<tr><th>成交时间</th><th>成交编号</th><th>方向</th><th>标的</th><th>数量</th><th>成交价</th><th>手续费</th><th>印花税</th></tr>";
    $("#activity-body").innerHTML = rows.length ? [...rows].reverse().map(row => `<tr><td>${shortDate(row.datetime)}</td><td>${row.trade_id}</td><td class="${row.side.toLowerCase()}">${row.side}</td><td>${row.symbol}</td><td>${row.quantity}</td><td>${number(row.price, 3)}</td><td>${money(row.commission)}</td><td>${money(row.stamp_duty)}</td></tr>`).join("") : '<tr><td class="empty" colspan="8">本次回测没有成交</td></tr>';
  } else {
    $("#activity-head").innerHTML = "<tr><th>创建时间</th><th>订单编号</th><th>方向</th><th>标的</th><th>数量</th><th>状态</th><th>价格</th><th>拒绝原因</th></tr>";
    $("#activity-body").innerHTML = rows.length ? [...rows].reverse().map(row => `<tr><td>${shortDate(row.created_at)}</td><td>${row.order_id}</td><td class="${row.side.toLowerCase()}">${row.side}</td><td>${row.symbol}</td><td>${row.quantity}</td><td class="status-${row.status.toLowerCase()}">${row.status}</td><td>${row.price == null ? "—" : number(row.price, 3)}</td><td>${row.reject_reason || "—"}</td></tr>`).join("") : '<tr><td class="empty" colspan="8">本次回测没有订单</td></tr>';
  }
}

async function runBacktest(event) {
  event.preventDefault(); const button = $("#run-button"); button.disabled = true; $("span", button).textContent = "正在调用交易内核…";
  try {
    const data = await api("/api/backtest", { method: "POST", body: JSON.stringify(requestPayload()) });
    renderResults(data); notice(`回测完成：${data.summary.bar_count} 根有效日 K，${data.result.metrics.trade_count} 笔成交。`, true);
  } catch (error) { notice(error.message); }
  finally { button.disabled = false; $("span", button).textContent = "运行完整回测"; }
}

function renderSimulation(data) {
  $("#sim-status").textContent = data.complete ? "COMPLETE" : data.running ? "RUNNING" : "PAUSED";
  $("#sim-status").classList.toggle("cyan", data.running);
  $("#sim-date").textContent = shortDate(data.current_date);
  $("#sim-price").textContent = data.current_close == null ? "等待首根 Bar" : `${data.symbol} / CLOSE ${number(data.current_close, 3)}`;
  $("#sim-progress").style.width = `${data.progress * 100}%`;
  $("#sim-progress-copy").textContent = `${data.index} / ${data.total} BAR`;
  const a = data.account;
  setMetricGrid("#sim-metrics", [{ text: money(a.total_equity), tone: "positive" }, { text: money(a.cash) }, { text: money(a.market_value) }, { text: money(a.total_fees) }]);
  const events = [...data.orders.map(item => ({ ...item, type: "ORDER", at: item.created_at })), ...data.trades.map(item => ({ ...item, type: "TRADE", at: item.datetime }))].sort((a, b) => a.at.localeCompare(b.at)).slice(-20).reverse();
  $("#sim-events").innerHTML = events.length ? events.map(item => `<div class="event"><time>${shortDate(item.at)}</time><b>${item.type}</b><span class="${item.side.toLowerCase()}">${item.side} ${item.quantity} ${item.symbol}</span><small>${item.type === "TRADE" ? `@ ${number(item.price, 3)}` : item.status}</small></div>`).join("") : '<p class="empty">策略预热中，尚无订单事件</p>';
  $("#sim-step").disabled = data.complete;
  if (data.complete) pauseSimulation();
}

async function simulationStep(showError = true) {
  try { renderSimulation(await api("/api/simulation/step", { method: "POST", body: "{}" })); }
  catch (error) { pauseSimulation(); if (showError) notice(error.message); }
}

async function startSimulation() {
  pauseSimulation();
  try {
    const data = await api("/api/simulation/start", { method: "POST", body: JSON.stringify(requestPayload()) });
    renderSimulation(data); $("#sim-pause").disabled = false; $("#sim-step").disabled = false;
    state.simTimer = setInterval(() => simulationStep(false), 90);
  } catch (error) { notice(error.message); }
}

function pauseSimulation() { if (state.simTimer) clearInterval(state.simTimer); state.simTimer = null; $("#sim-pause").disabled = true; }

async function bootstrap() {
  try {
    const data = await api("/api/bootstrap"); state.bootstrap = data;
    $("#side-data").textContent = data.data_file; $("#side-frequency").textContent = data.rules.bar_frequency.toUpperCase();
    $("#bar-count").textContent = data.bar_count.toLocaleString("zh-CN"); $("#date-range").textContent = `${data.date_min.slice(0, 4)}—${data.date_max.slice(0, 4)}`;
    $("#data-score").textContent = "100"; $("#data-meter").style.width = "100%";
    $("#symbol").innerHTML = data.symbols.map(symbol => `<option>${symbol}</option>`).join("");
    $("#strategy").innerHTML = data.strategies.map(strategy => `<option value="${strategy.id}">${strategy.name}</option>`).join("");
    $("#start").min = $("#end").min = data.date_min; $("#start").max = $("#end").max = data.date_max;
    $("#start").value = data.date_min; $("#end").value = data.date_max;
    $("#initial-cash").value = data.config.backtest.initial_cash; $("#target-weight").value = data.config.strategy.target_weight * 100;
    $("#execution-rule").textContent = data.rules.execution; renderStrategyFields();
  } catch (error) { notice(`初始化失败：${error.message}`); }
}

function init() {
  $$(".nav-item").forEach(item => item.addEventListener("click", () => navigate(item.dataset.view)));
  $$('[data-jump]').forEach(item => item.addEventListener("click", () => navigate(item.dataset.jump)));
  $("#notice button").addEventListener("click", () => $("#notice").classList.add("hidden"));
  $("#strategy").addEventListener("change", renderStrategyFields); $("#backtest-form").addEventListener("submit", runBacktest);
  $("#sim-start").addEventListener("click", startSimulation); $("#sim-pause").addEventListener("click", pauseSimulation); $("#sim-step").addEventListener("click", () => simulationStep());
  $$("[data-table]").forEach(button => button.addEventListener("click", () => { $$("[data-table]").forEach(x => x.classList.remove("active")); button.classList.add("active"); state.table = button.dataset.table; renderActivity(); }));
  setInterval(() => $("#clock").textContent = new Date().toLocaleTimeString("zh-CN", { hour12: false }), 1000);
  const requested = location.hash.slice(1); if (titles[requested]) navigate(requested);
  if (location.protocol === "file:") {
    notice("页面样式已加载，但回测功能需要 Python 服务。请在仓库根目录运行：PYTHONPATH=src python3 -m quant_demo.web，然后访问 http://127.0.0.1:8000");
    return;
  }
  bootstrap();
}

document.addEventListener("DOMContentLoaded", init);
