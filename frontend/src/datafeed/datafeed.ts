/**
 * Datafeed 层：向后端 REST 取历史、经 SocketClient 订阅实时。
 * 接口形态与 TradingView Datafeed 规范保持一致（onReady / resolveSymbol /
 * getBars / subscribeBars / unsubscribeBars），便于将来直接对接 Charting Library。
 * 后端不可达时自动进入演示模式（内置数据快照）。
 */
import { api, type Bar, type SymbolInfo } from '../api'
import { backendAvailable, demo } from '../demo'
import { socket } from './socket'

export const SUPPORTED_RESOLUTIONS = ['1m', '5m', '15m', '1h', '4h', '1d', '1w']

export const datafeed = {
  async search(query: string) {
    if (!(await backendAvailable())) return demo.search(query)
    const { symbols } = await api.search(query)
    return symbols
  },

  async resolveSymbol(symbol: string): Promise<SymbolInfo> {
    if (!(await backendAvailable())) return demo.resolve(symbol)
    return api.symbolInfo(symbol)
  },

  /** 返回 [from, to]（Unix 秒）区间内、按时间升序的历史 bar。 */
  async getBars(
    symbolInfo: SymbolInfo,
    resolution: string,
    from: number,
    to: number,
    countback = 500,
  ): Promise<{ bars: Bar[]; noData: boolean }> {
    if (!(await backendAvailable())) {
      const all = await demo.bars(symbolInfo.symbol)
      const bars = all.filter((b) => b.time >= from * 1000 && b.time <= to * 1000)
      return { bars, noData: bars.length === 0 }
    }
    const resp = await api.history({
      symbol: symbolInfo.symbol,
      interval: resolution,
      from: Math.floor(from),
      to: Math.ceil(to),
      countback,
    })
    return { bars: resp.bars, noData: resp.noData }
  },

  async subscribeBars(
    symbolInfo: SymbolInfo,
    resolution: string,
    onTick: (bar: Bar) => void,
    subscriberUID: string,
    lastBar: Bar | null,
  ): Promise<void> {
    if (!(await backendAvailable())) return // 演示模式无实时推送
    socket.subscribeOnStream(symbolInfo, resolution, onTick, subscriberUID, lastBar)
  },

  async unsubscribeBars(subscriberUID: string): Promise<void> {
    if (!(await backendAvailable())) return
    socket.unsubscribeFromStream(subscriberUID)
  },
}
