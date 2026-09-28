<script setup lang="ts">
/**
 * 专业图表视图：基于 KLineChart v10（开源 Apache-2.0）。
 * 通过 v10 DataLoader 协议对接现有 datafeed（REST 历史 + PubSub 实时），
 * 提供画线工具与内置指标（MA/EMA/BOLL/VOL/MACD/RSI/KDJ）。
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import {
  dispose, getSupportedIndicators, getSupportedOverlays, init,
  type Chart, type KLineData, type Period,
  type DataLoaderGetBarsParams, type DataLoaderSubscribeBarParams,
} from 'klinecharts'
import { datafeed } from '../datafeed/datafeed'
import type { Bar } from '../api'
import { useWorkbench } from '../stores/workbench'

const store = useWorkbench()
const container = ref<HTMLElement | null>(null)
const error = ref('')
const chartRef = ref<Chart | null>(null)
const infoRef = ref<Awaited<ReturnType<typeof datafeed.resolveSymbol>> | null>(null)
const activeIndicators = ref<string[]>([])
let uid = ''
let lastBars: Bar[] = []
let currentResolution = '1d'
let el: HTMLElement | null = null

const RESOLUTION_PERIOD: Record<string, Period> = {
  '1m': { type: 'minute', span: 1 },
  '5m': { type: 'minute', span: 5 },
  '15m': { type: 'minute', span: 15 },
  '1h': { type: 'hour', span: 1 },
  '4h': { type: 'hour', span: 4 },
  '1d': { type: 'day', span: 1 },
  '1w': { type: 'week', span: 1 },
}

const toKlcBar = (b: Bar): KLineData => ({
  timestamp: b.time, open: b.open, high: b.high, low: b.low, close: b.close, volume: b.volume,
})

const INDICATORS = [
  { name: 'MA', label: 'MA' },
  { name: 'EMA', label: 'EMA' },
  { name: 'BOLL', label: 'BOLL' },
  { name: 'VOL', label: 'VOL' },
  { name: 'MACD', label: 'MACD' },
  { name: 'RSI', label: 'RSI' },
  { name: 'KDJ', label: 'KDJ' },
].filter((i) => getSupportedIndicators().includes(i.name))

const DRAW_TOOLS = [
  { name: 'segment', label: '线段' },
  { name: 'rayLine', label: '射线' },
  { name: 'horizontalStraightLine', label: '水平线' },
  { name: 'verticalStraightLine', label: '垂直线' },
  { name: 'rect', label: '矩形' },
  { name: 'parallelogram', label: '平行四边形' },
  { name: 'fibonacciLine', label: '斐波那契' },
  { name: 'priceChannelLine', label: '价格通道' },
].filter((t) => getSupportedOverlays().includes(t.name))

// ---------- v10 DataLoader：对接现有 datafeed ----------

async function getBarsImpl({ type, timestamp, callback }: DataLoaderGetBarsParams) {
  const info = infoRef.value
  if (!info) {
    callback([])
    return
  }
  try {
    const now = Math.floor(Date.now() / 1000)
    if (type === 'init') {
      const { bars } = await datafeed.getBars(info, currentResolution, now - 600 * 86_400, now, 500)
      lastBars = bars
      callback(bars.map(toKlcBar), bars.length >= 500)
    } else if (type === 'backward') {
      // timestamp = 当前最左一根的时间（毫秒），取更早的一段
      const toSec = Math.floor((timestamp ?? Date.now()) / 1000) - 1
      const { bars } = await datafeed.getBars(info, currentResolution, toSec - 500 * 86_400, toSec, 500)
      callback(bars.map(toKlcBar), bars.length >= 500)
    } else if (type === 'forward') {
      const fromSec = Math.floor((timestamp ?? now * 1000) / 1000) + 1
      const { bars } = await datafeed.getBars(info, currentResolution, fromSec, now, 500)
      callback(bars.map(toKlcBar), false)
    } else {
      callback([])
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
    callback([], false)
  }
}

function subscribeBarImpl({ callback }: DataLoaderSubscribeBarParams) {
  const info = infoRef.value
  if (!info) return
  uid = `klc-${info.symbol}|${currentResolution}`
  datafeed.subscribeBars(
    info,
    currentResolution,
    (bar: Bar) => callback(toKlcBar(bar)),
    uid,
    lastBars.length ? lastBars[lastBars.length - 1] : null,
  )
}

function unsubscribeBarImpl() {
  if (uid) {
    datafeed.unsubscribeBars(uid)
    uid = ''
  }
}

// ---------- 品种/周期切换 ----------

async function switchTo(symbol: string, resolution: string) {
  const chart = chartRef.value
  if (!chart) return
  error.value = ''
  try {
    const info = await datafeed.resolveSymbol(symbol)
    infoRef.value = info
    if (uid) datafeed.unsubscribeBars(uid)
    uid = ''
    currentResolution = info.supported_resolutions.includes(resolution)
      ? resolution
      : info.supported_resolutions.includes('1d')
        ? '1d'
        : info.supported_resolutions[info.supported_resolutions.length - 1]
    if (currentResolution !== resolution) store.setResolution(currentResolution)
    const pricePrecision = Math.max(0, Math.round(Math.log10(info.pricescale)))
    chart.setSymbol({ ticker: info.symbol, pricePrecision, volumePrecision: 2 })
    chart.setPeriod(RESOLUTION_PERIOD[currentResolution])
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

// ---------- 工具栏 ----------

// 主图指标叠在蜡烛图窗格上；VOL/MACD/RSI/KDJ 走独立子窗格
const MAIN_PANE = 'candle_pane'
const MAIN_PANE_INDICATORS = new Set(['MA', 'EMA', 'BOLL'])

function toggleIndicator(name: string) {
  const chart = chartRef.value
  if (!chart) return
  if (activeIndicators.value.includes(name)) {
    chart.removeIndicator({ name })
    activeIndicators.value = activeIndicators.value.filter((x) => x !== name)
  } else {
    const id = MAIN_PANE_INDICATORS.has(name)
      ? chart.createIndicator({ name, paneId: MAIN_PANE })
      : chart.createIndicator(name)
    if (id) activeIndicators.value.push(name)
  }
}

function startDraw(name: string) {
  chartRef.value?.createOverlay({ name })
}

function clearDrawings() {
  chartRef.value?.removeOverlay()
}

function onResize() {
  chartRef.value?.resize()
}

onMounted(() => {
  if (!container.value) return
  el = container.value
  const chart = init(container.value, {
    styles: {
      grid: { horizontal: { color: '#1e222d' }, vertical: { color: '#1e222d' } },
      candle: {
        bar: {
          upColor: '#26a69a', downColor: '#ef5350', noChangeColor: '#888888',
          upBorderColor: '#26a69a', downBorderColor: '#ef5350', noChangeBorderColor: '#888888',
          upWickColor: '#26a69a', downWickColor: '#ef5350', noChangeWickColor: '#888888',
        },
      },
      xAxis: {
        axisLine: { color: '#2a2e39' },
        tickLine: { color: '#2a2e39' },
        tickText: { color: '#787b86' },
      },
      yAxis: {
        axisLine: { color: '#2a2e39' },
        tickLine: { color: '#2a2e39' },
        tickText: { color: '#787b86' },
      },
      separator: { color: '#2a2e39' },
    },
  })
  if (!chart) {
    error.value = 'KLineChart 初始化失败'
    return
  }
  chartRef.value = chart
  chart.setDataLoader({
    getBars: getBarsImpl,
    subscribeBar: subscribeBarImpl,
    unsubscribeBar: unsubscribeBarImpl,
  })
  // 默认指标：成交量窗格 + 主图 MA（叠在蜡烛上）
  const volId = chart.createIndicator('VOL')
  const maId = chart.createIndicator({ name: 'MA', paneId: MAIN_PANE })
  if (volId) activeIndicators.value.push('VOL')
  if (maId) activeIndicators.value.push('MA')
  window.addEventListener('resize', onResize)
  switchTo(store.symbol, store.resolution)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  if (uid) datafeed.unsubscribeBars(uid)
  uid = ''
  chartRef.value?.removeOverlay()
  if (el) dispose(el)
  chartRef.value = null
  el = null
})

defineExpose({
  async reload() {
    await switchTo(store.symbol, store.resolution)
  },
})
</script>

<template>
  <div class="chart-area">
    <div class="kline-toolbar">
      <div class="kline-group">
        <span class="kline-group-label">指标</span>
        <button
          v-for="ind in INDICATORS"
          :key="ind.name"
          :class="{ active: activeIndicators.includes(ind.name) }"
          @click="toggleIndicator(ind.name)"
        >{{ ind.label }}</button>
      </div>
      <div class="kline-group">
        <span class="kline-group-label">画线</span>
        <button v-for="tool in DRAW_TOOLS" :key="tool.name" @click="startDraw(tool.name)">
          {{ tool.label }}
        </button>
        <button @click="clearDrawings">清除画线</button>
      </div>
      <span class="hint" style="margin-left: auto;">选中工具后在图上点击落点绘制</span>
    </div>
    <div ref="container" class="kline-container"></div>
    <div v-if="error" class="chart-error">加载失败：{{ error }}</div>
  </div>
</template>
