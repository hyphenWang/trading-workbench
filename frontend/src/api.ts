/** 后端 API 客户端与类型定义。 */

export interface Bar {
  time: number // UTC 毫秒
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface SymbolInfo {
  symbol: string // 全名 BINANCE:BTCUSDT
  ticker: string
  provider: string
  name: string
  description: string
  exchange: string
  market: string
  type: string
  session: string
  timezone: string
  pricescale: number
  minmov: number
  has_intraday: boolean
  supported_resolutions: string[]
  data_status: string
  volume_precision: number
}

export interface SearchHit {
  symbol: string
  name: string
  exchange: string
  provider: string
  type: string
}

export interface StrategyParamSpec {
  key: string
  label: string
  type: 'int' | 'float'
  default: number
}

export interface StrategySpec {
  name: string
  label: string
  description: string
  supports_short: boolean
  params: StrategyParamSpec[]
}

export interface TradeRow {
  entry_time: number
  exit_time: number
  side: 'long' | 'short'
  entry_price: number
  exit_price: number
  bars: number
  pnl: number
  return_pct: number
}

export interface BacktestResult {
  symbol: string
  interval: string
  strategy: string
  params: Record<string, number>
  metrics: Record<string, number | null>
  equity: [number, number][]
  trades: TradeRow[]
  bar_count: number
  from: number
  to: number
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, init)
  if (!resp.ok) {
    let detail = `${resp.status}`
    try {
      const body = await resp.json()
      detail = body.detail ?? detail
    } catch { /* keep status */ }
    throw new Error(String(detail))
  }
  return resp.json() as Promise<T>
}

export const api = {
  search: (query: string) =>
    request<{ symbols: SearchHit[] }>(`/api/symbols?query=${encodeURIComponent(query)}&limit=30`),

  symbolInfo: (symbol: string) =>
    request<SymbolInfo>(`/api/symbol?symbol=${encodeURIComponent(symbol)}`),

  history: (p: { symbol: string; interval: string; from: number; to: number; countback?: number; backtest?: boolean }) => {
    const q = new URLSearchParams({
      symbol: p.symbol,
      interval: p.interval,
      from: String(p.from),
      to: String(p.to),
    })
    if (p.countback) q.set('countback', String(p.countback))
    if (p.backtest) q.set('backtest', 'true')
    return request<{ bars: Bar[]; noData: boolean; next_time: number | null }>(`/api/history?${q}`)
  },

  strategies: () => request<{ strategies: StrategySpec[] }>('/api/strategies'),

  backtest: (body: unknown) =>
    request<BacktestResult>('/api/backtest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
}
