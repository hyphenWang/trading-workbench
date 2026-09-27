/**
 * 图表控制器：驱动 Lightweight Charts。
 * 职责：历史数据加载（含向左滚动加载更早数据）、实时 bar 更新、周期/品种切换。
 * 数据全部来自 datafeed 层，图表不感知任何具体数据源。
 */
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type LogicalRange,
  type UTCTimestamp,
} from 'lightweight-charts'
import { datafeed } from './datafeed/datafeed'
import { socket } from './datafeed/socket'
import type { Bar, SymbolInfo } from './api'

const INTERVAL_MS: Record<string, number> = {
  '1m': 60_000, '5m': 300_000, '15m': 900_000, '1h': 3_600_000,
  '4h': 14_400_000, '1d': 86_400_000, '1w': 604_800_000,
}

const toSec = (ms: number) => Math.floor(ms / 1000) as UTCTimestamp

export class ChartController {
  private chart: IChartApi | null = null
  private candle: ISeriesApi<'Candlestick'> | null = null
  private volume: ISeriesApi<'Histogram'> | null = null
  private bars: Bar[] = []
  private info: SymbolInfo | null = null
  private resolution = '1d'
  private uid = ''
  private loading = false
  private hasMore = true
  private container: HTMLElement | null = null

  init(container: HTMLElement): void {
    this.container = container
    this.chart = createChart(container, {
      layout: {
        background: { type: ColorType.Solid, color: '#131722' },
        textColor: '#787b86',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: '#1e222d' },
        horzLines: { color: '#1e222d' },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#2a2e39' },
      timeScale: {
        borderColor: '#2a2e39',
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 5,
      },
      autoSize: true,
    })
    this.candle = this.chart.addSeries(CandlestickSeries, {
      upColor: '#26a69a', downColor: '#ef5350', borderVisible: false,
      wickUpColor: '#26a69a', wickDownColor: '#ef5350',
    })
    this.volume = this.chart.addSeries(HistogramSeries, {
      priceScaleId: '',
      priceFormat: { type: 'volume' },
      lastValueVisible: false,
      priceLineVisible: false,
    })
    this.volume.priceScale().applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } })
    this.chart.timeScale().subscribeVisibleLogicalRangeChange((range) => this.maybeLoadOlder(range))
  }

  async setSymbol(symbol: string, resolution: string): Promise<SymbolInfo> {
    if (this.uid) datafeed.unsubscribeBars(this.uid)
    this.uid = ''
    this.bars = []
    this.hasMore = true
    const info = await datafeed.resolveSymbol(symbol)
    // 当前周期不被新品种支持时，回退到其默认周期
    const res = info.supported_resolutions.includes(resolution)
      ? resolution
      : info.supported_resolutions.includes('1d')
        ? '1d'
        : info.supported_resolutions[info.supported_resolutions.length - 1]
    this.info = info
    this.resolution = res

    const precision = Math.max(0, Math.round(Math.log10(info.pricescale)))
    this.candle!.applyOptions({
      priceFormat: { type: 'price', precision, minMove: 1 / info.pricescale },
    })
    // 日线/周线不显示时刻（避免时区折算出的 16:00 之类干扰）
    this.chart!.timeScale().applyOptions({
      timeVisible: res.endsWith('m') || res.endsWith('h'),
    })

    const now = Math.floor(Date.now() / 1000)
    const { bars } = await datafeed.getBars(info, res, now - 600 * 86_400, now, 500)
    if (!bars.length) throw new Error(`「${info.name}」没有返回任何历史数据`)
    this.bars = bars
    this.setData()
    this.chart!.timeScale().scrollToRealTime()

    // 实时订阅：与文章一致的 PubSub 模式
    this.uid = `chart-${symbol}|${res}`
    datafeed.subscribeBars(info, res, this.onTick, this.uid, bars[bars.length - 1])
    return { ...info, supported_resolutions: info.supported_resolutions }
  }

  get currentResolution(): string {
    return this.resolution
  }

  private onTick = (bar: Bar): void => {
    if (!this.bars.length) return
    const last = this.bars[this.bars.length - 1]
    if (bar.time === last.time) {
      this.bars[this.bars.length - 1] = bar
    } else if (bar.time > last.time) {
      this.bars.push(bar)
    } else {
      return
    }
    this.updateLastPoint()
  }

  private setData(): void {
    this.candle!.setData(
      this.bars.map((b) => ({
        time: toSec(b.time),
        open: b.open, high: b.high, low: b.low, close: b.close,
      })),
    )
    this.volume!.setData(
      this.bars.map((b) => ({
        time: toSec(b.time),
        value: b.volume,
        color: b.close >= b.open ? 'rgba(38,166,154,0.5)' : 'rgba(239,83,80,0.5)',
      })),
    )
  }

  private updateLastPoint(): void {
    const b = this.bars[this.bars.length - 1]
    this.candle!.update({
      time: toSec(b.time), open: b.open, high: b.high, low: b.low, close: b.close,
    })
    this.volume!.update({
      time: toSec(b.time), value: b.volume,
      color: b.close >= b.open ? 'rgba(38,166,154,0.5)' : 'rgba(239,83,80,0.5)',
    })
  }

  /** 向左滚动到边缘时加载更早的历史。 */
  private async maybeLoadOlder(range: LogicalRange | null): Promise<void> {
    if (!range || this.loading || !this.hasMore || !this.info || this.bars.length < 2) return
    if (range.from > 10) return
    this.loading = true
    try {
      const first = this.bars[0]
      const step = INTERVAL_MS[this.resolution] ?? 86_400_000
      const span = Math.round((range.to - range.from) * step)
      const fromMs = first.time - span * 2
      const toMs = first.time - step
      const { bars } = await datafeed.getBars(
        this.info, this.resolution, Math.floor(fromMs / 1000), Math.floor(toMs / 1000), 500,
      )
      if (!bars.length) {
        this.hasMore = false
        return
      }
      const known = new Set(this.bars.map((b) => b.time))
      const fresh = bars.filter((b) => !known.has(b.time))
      if (!fresh.length) return
      this.bars = [...fresh, ...this.bars]
      const added = fresh.length
      const before = range
      this.setData()
      // 保持视口在原位置，不因追加数据而跳动
      this.chart!.timeScale().setVisibleLogicalRange({
        from: before.from + added,
        to: before.to + added,
      })
    } catch {
      this.hasMore = false
    } finally {
      this.loading = false
    }
  }

  destroy(): void {
    if (this.uid) datafeed.unsubscribeBars(this.uid)
    this.uid = ''
    socket.unsubscribeAll()
    this.chart?.remove()
    this.chart = null
    this.container = null
  }
}
