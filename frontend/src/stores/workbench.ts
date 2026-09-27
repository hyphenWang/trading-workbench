import { defineStore } from 'pinia'
import type { SymbolInfo } from '../api'

export const useWorkbench = defineStore('workbench', {
  state: () => ({
    symbol: 'BINANCE:BTCUSDT',
    resolution: '1d',
    symbolInfo: null as SymbolInfo | null,
    wsStatus: 'connecting' as 'connecting' | 'connected' | 'disconnected',
  }),
  actions: {
    setSymbol(symbol: string) {
      this.symbol = symbol
    },
    setResolution(res: string) {
      this.resolution = res
    },
  },
})
