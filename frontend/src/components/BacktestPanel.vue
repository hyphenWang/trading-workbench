<script setup lang="ts">
import {
  AreaSeries, ColorType, createChart,
  type IChartApi, type UTCTimestamp,
} from 'lightweight-charts'
import { onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { api, type BacktestResult, type StrategySpec } from '../api'
import { backendAvailable } from '../demo'
import { useWorkbench } from '../stores/workbench'

const store = useWorkbench()
const demoMode = ref(true) // 探测完成后更新；默认按演示模式处理避免误发请求
const strategies = ref<StrategySpec[]>([])
const selected = ref('')
const params = reactive<Record<string, number>>({})
const feePct = ref(0.1) // 以 % 展示，内部转小数
const slipPct = ref(0.0)
const allowShort = ref(false)
const loading = ref(false)
const error = ref('')
const result = ref<BacktestResult | null>(null)

const METRIC_LABELS: Record<string, string> = {
  total_return_pct: '总收益',
  cagr_pct: '年化收益',
  ann_vol_pct: '年化波动',
  sharpe: '夏普比率',
  sortino: '索提诺',
  max_drawdown_pct: '最大回撤',
  win_rate_pct: '胜率',
  profit_factor: '盈亏比',
  n_trades: '交易次数',
  avg_trade_ret_pct: '平均单笔',
  exposure_pct: '持仓占比',
  buy_hold_pct: '买入持有',
}
const PCT_METRICS = new Set([
  'total_return_pct', 'cagr_pct', 'ann_vol_pct', 'max_drawdown_pct',
  'win_rate_pct', 'exposure_pct', 'avg_trade_ret_pct', 'buy_hold_pct',
])

const equityEl = ref<HTMLElement | null>(null)
let equityChart: IChartApi | null = null

onMounted(async () => {
  if (await backendAvailable()) {
    const resp = await api.strategies()
    strategies.value = resp.strategies
    selectStrategy(resp.strategies[0]?.name ?? '')
    demoMode.value = false
  }
})

function selectStrategy(name: string) {
  selected.value = name
  const spec = strategies.value.find((s) => s.name === name)
  for (const k of Object.keys(params)) delete params[k]
  for (const p of spec?.params ?? []) params[p.key] = p.default
}

async function run() {
  if (!selected.value) return
  if (demoMode.value) {
    error.value = '演示模式下不支持回测：请在本地启动后端（uv run uvicorn app.main:app）后刷新页面。'
    return
  }
  loading.value = true
  error.value = ''
  try {
    result.value = await api.backtest({
      symbol: store.symbol,
      interval: store.resolution,
      strategy: selected.value,
      params: { ...params },
      fee: feePct.value / 100,
      slippage: slipPct.value / 100,
      allow_short: allowShort.value,
    })
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
    result.value = null
  } finally {
    loading.value = false
  }
}

function renderEquity() {
  if (!equityEl.value) return
  equityChart?.remove()
  equityChart = createChart(equityEl.value, {
    layout: { background: { type: ColorType.Solid, color: '#0f1218' }, textColor: '#787b86', fontSize: 10 },
    grid: { vertLines: { color: '#1a1e29' }, horzLines: { color: '#1a1e29' } },
    rightPriceScale: { borderVisible: false },
    timeScale: { borderVisible: false, timeVisible: true, secondsVisible: false },
    autoSize: true,
  })
  const series = equityChart.addSeries(AreaSeries, {
    lineColor: '#2962ff', topColor: 'rgba(41,98,255,0.35)', bottomColor: 'rgba(41,98,255,0)',
    priceFormat: { type: 'volume' },
  })
  const pts = (result.value?.equity ?? []).map(([ms, v]) => ({
    time: Math.floor(ms / 1000) as UTCTimestamp, value: v,
  }))
  series.setData(pts)
  equityChart.timeScale().fitContent()
}

function cls(v: number | null | undefined): string {
  if (v == null) return ''
  return v > 0 ? 'pos' : v < 0 ? 'neg' : ''
}

function fmtDate(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10)
}

watch(result, () => renderEquity(), { flush: 'post' })
watch(() => store.symbol, () => (result.value = null))
onBeforeUnmount(() => equityChart?.remove())
</script>

<template>
  <div class="side-panel">
    <div>
      <p class="section-title">策略回测</p>
      <template v-if="demoMode">
        <p class="hint">
          当前为静态演示（GitHub Pages）：仅展示图表与内置历史数据。
          完整系统请在本地运行——后端 `uv run uvicorn app.main:app` + 前端 `npm run dev`，
          即可解锁全市场数据、实时行情与本回测面板。
        </p>
      </template>
      <template v-else>
      <div class="form-row">
        <label>策略</label>
        <select :value="selected" @change="selectStrategy(($event.target as HTMLSelectElement).value)">
          <option v-for="s in strategies" :key="s.name" :value="s.name">{{ s.label }}</option>
        </select>
      </div>
      <div class="form-row" v-for="p in strategies.find((s) => s.name === selected)?.params ?? []" :key="p.key">
        <label>{{ p.label }}</label>
        <input type="number" :step="p.type === 'int' ? 1 : 0.1" v-model.number="params[p.key]" />
      </div>
      <div class="form-row">
        <label>手续费 (单边%)</label>
        <input type="number" step="0.01" min="0" v-model.number="feePct" />
      </div>
      <div class="form-row">
        <label>滑点 (单边%)</label>
        <input type="number" step="0.01" min="0" v-model.number="slipPct" />
      </div>
      <div class="form-row">
        <label>允许做空</label>
        <input type="checkbox" v-model="allowShort" />
      </div>
      <button style="width: 100%; padding: 7px;" :disabled="loading" @click="run">
        {{ loading ? '回测中...' : `回测 ${store.symbol} · ${store.resolution}` }}
      </button>
      <div v-if="error" style="color: var(--down); margin-top: 8px; font-size: 12px;">{{ error }}</div>
      </template>
    </div>

    <template v-if="result">
      <div>
        <p class="section-title">绩效报告（{{ result.bar_count }} 根K线）</p>
        <div class="metric-grid">
          <div v-for="(label, key) in METRIC_LABELS" :key="key" class="metric">
            <div class="label">{{ label }}</div>
            <div class="value" :class="cls(result.metrics[key] as number | null)">
              {{ result.metrics[key] ?? '—' }}{{ PCT_METRICS.has(key) && result.metrics[key] != null ? '%' : '' }}
            </div>
          </div>
        </div>
      </div>
      <div>
        <p class="section-title">资金曲线</p>
        <div ref="equityEl" class="equity-box"></div>
      </div>
      <div v-if="result.trades.length">
        <p class="section-title">交易明细（最近 {{ Math.min(result.trades.length, 30) }} 笔）</p>
        <table class="trades-table">
          <thead>
            <tr><th>开仓日</th><th>平仓日</th><th>方向</th><th>收益</th><th>盈亏</th></tr>
          </thead>
          <tbody>
            <tr v-for="(t, i) in [...result.trades].reverse().slice(0, 30)" :key="i">
              <td>{{ fmtDate(t.entry_time) }}</td>
              <td>{{ fmtDate(t.exit_time) }}</td>
              <td>{{ t.side === 'long' ? '多' : '空' }}</td>
              <td :class="cls(t.return_pct)">{{ t.return_pct.toFixed(2) }}%</td>
              <td :class="cls(t.pnl)">{{ t.pnl.toFixed(0) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
    <p v-else class="hint">
      选择策略与参数后点击「回测」。信号在收盘确认、下一根开盘成交，已计入手续费与滑点；
      指标含 Sharpe / 最大回撤 / 胜率 / 盈亏比 / 资金曲线与逐笔明细。
    </p>
  </div>
</template>
