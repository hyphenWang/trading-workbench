/**
 * 演示模式：本地后端不可达时（如 GitHub Pages 静态部署），自动回退到
 * public/demo/ 内置的历史数据快照，让访客依然能看到完整图表。
 * 本地正常启动后端时不会进入此模式（实时行情、回测均可用）。
 */
import type { Bar, SearchHit, SymbolInfo } from './api'

let _backendCheck: Promise<boolean> | null = null

/** 探测本地后端是否可达（只探测一次，结果缓存）。 */
export function backendAvailable(): Promise<boolean> {
  if (!_backendCheck) {
    _backendCheck = fetch('/api/strategies', { signal: AbortSignal.timeout(3000) })
      .then((r) => r.ok)
      .catch(() => false)
  }
  return _backendCheck
}

interface DemoEntry {
  info: SymbolInfo
  bars: Bar[]
}

interface DemoCatalogItem {
  file: string
  symbol: string
  ticker: string
  name: string
  description: string
  exchange: string
  market: SymbolInfo['market']
  type: string
  timezone: string
}

const CATALOG: DemoCatalogItem[] = [
  {
    file: 'BINANCE_BTCUSDT_1d.json', symbol: 'BINANCE:BTCUSDT', ticker: 'BTCUSDT',
    name: 'BTCUSDT', description: 'BTC / USDT（演示快照）', exchange: 'BINANCE',
    market: 'crypto', type: 'crypto', timezone: 'Etc/UTC',
  },
  {
    file: 'CN_600519_1d.json', symbol: 'CN:600519', ticker: '600519',
    name: '贵州茅台', description: 'A股（演示快照）', exchange: 'SSE',
    market: 'cn', type: 'stock', timezone: 'Asia/Shanghai',
  },
  {
    file: 'YAHOO_AAPL_1d.json', symbol: 'YAHOO:AAPL', ticker: 'AAPL',
    name: 'AAPL', description: '美股（演示快照）', exchange: 'YAHOO',
    market: 'us', type: 'stock', timezone: 'America/New_York',
  },
]

let _cache: Promise<Record<string, DemoEntry>> | null = null

function loadAll(): Promise<Record<string, DemoEntry>> {
  if (!_cache) {
    _cache = (async () => {
      const out: Record<string, DemoEntry> = {}
      for (const c of CATALOG) {
        const data = await fetch(`${import.meta.env.BASE_URL}demo/${c.file}`)
        if (!data.ok) throw new Error(`演示数据加载失败: ${c.file}`)
        const json = (await data.json()) as { bars: Bar[] }
        out[c.symbol] = {
          info: {
            symbol: c.symbol, ticker: c.ticker, provider: 'DEMO', name: c.name,
            description: c.description, exchange: c.exchange, market: c.market,
            type: c.type, session: '24x7', timezone: c.timezone,
            pricescale: 100, minmov: 1, has_intraday: false,
            supported_resolutions: ['1d'], data_status: 'endofday', volume_precision: 2,
          },
          bars: json.bars,
        }
      }
      return out
    })()
  }
  return _cache
}

export const demo = {
  async search(query: string): Promise<SearchHit[]> {
    const all = await loadAll()
    const q = query.trim().toLowerCase()
    return Object.values(all)
      .filter((e) => !q || e.info.symbol.toLowerCase().includes(q) || e.info.name.toLowerCase().includes(q))
      .map((e) => ({
        symbol: e.info.symbol, name: e.info.name,
        exchange: e.info.exchange, provider: 'DEMO', type: e.info.type,
      }))
  },

  async resolve(symbol: string): Promise<SymbolInfo> {
    const all = await loadAll()
    const hit = all[symbol]
    if (!hit) throw new Error(`演示模式仅内置: BTCUSDT / 600519 / AAPL（其他品种请启动本地后端）`)
    return hit.info
  },

  async bars(symbol: string): Promise<Bar[]> {
    const all = await loadAll()
    return all[symbol]?.bars ?? []
  },
}
