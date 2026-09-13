const API_BASE = import.meta.env.VITE_API_BASE || '/api'

export async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail || `API ${response.status}: ${response.statusText}`)
  }
  return response.json()
}

export const api = {
  health: () => request('/health'),
  config: () => request('/config'),
  runBacktest: (payload) => request('/backtest/run', { method: 'POST', body: JSON.stringify(payload) }),
  latest: () => request('/backtest/latest'),
  metrics: () => request('/backtest/metrics'),
  equity: () => request('/backtest/equity'),
  trades: () => request('/backtest/trades'),
  orders: () => request('/backtest/orders'),
}
