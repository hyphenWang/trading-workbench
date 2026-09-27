import { defineStore } from 'pinia'
import type { SymbolInfo } from '../api'

export interface WatchItem {
  symbol: string
  name: string
}

const WATCH_KEY = 'wb.watchlist.v1'

const DEFAULT_WATCHLIST: WatchItem[] = [
  { symbol: 'BINANCE:BTCUSDT', name: 'BTCUSDT' },
  { symbol: 'BINANCE:ETHUSDT', name: 'ETHUSDT' },
  { symbol: 'CN:600519', name: '贵州茅台' },
  { symbol: 'YAHOO:AAPL', name: 'AAPL' },
  { symbol: 'IDX:000300', name: '沪深300' },
  { symbol: 'FUT:RB0', name: '螺纹钢主力' },
]

export const useWorkbench = defineStore('workbench', {
  state: () => ({
    symbol: 'BINANCE:BTCUSDT',
    resolution: '1d',
    symbolInfo: null as SymbolInfo | null,
    wsStatus: 'connecting' as 'connecting' | 'connected' | 'disconnected',
    watchlist: [] as WatchItem[],
  }),
  actions: {
    setSymbol(symbol: string) {
      this.symbol = symbol
    },
    setResolution(res: string) {
      this.resolution = res
    },
    initWatchlist() {
      try {
        const raw = localStorage.getItem(WATCH_KEY)
        const parsed = raw ? (JSON.parse(raw) as WatchItem[]) : null
        this.watchlist =
          Array.isArray(parsed) && parsed.every((it) => it && it.symbol)
            ? parsed
            : [...DEFAULT_WATCHLIST]
      } catch {
        this.watchlist = [...DEFAULT_WATCHLIST]
      }
      this.persistWatchlist()
    },
    addCurrent() {
      const symbol = this.symbol
      if (!symbol || this.watchlist.some((it) => it.symbol === symbol)) return
      this.watchlist.unshift({ symbol, name: this.symbolInfo?.name || symbol })
      this.persistWatchlist()
    },
    removeWatch(symbol: string) {
      this.watchlist = this.watchlist.filter((it) => it.symbol !== symbol)
      this.persistWatchlist()
    },
    persistWatchlist() {
      try {
        localStorage.setItem(WATCH_KEY, JSON.stringify(this.watchlist))
      } catch { /* 存储已满等异常忽略 */ }
    },
  },
})
