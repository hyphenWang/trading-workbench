<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api'
import { backendAvailable } from '../demo'
import { useWorkbench } from '../stores/workbench'

const store = useWorkbench()
const prices = ref<Record<string, { close: number | null; chg: number | null }>>({})
const refreshing = ref(false)
let timer: number | undefined

async function refresh() {
  if (refreshing.value) return
  if (!(await backendAvailable())) return // 演示模式不取价
  refreshing.value = true
  try {
    const items = store.watchlist.slice(0, 15)
    const to = Math.floor(Date.now() / 1000)
    const from = to - 14 * 86_400
    const results = await Promise.allSettled(
      items.map((it) => api.history({ symbol: it.symbol, interval: '1d', from, to, countback: 2 })),
    )
    const map: Record<string, { close: number | null; chg: number | null }> = {}
    results.forEach((r, i) => {
      const s = items[i].symbol
      if (r.status === 'fulfilled' && r.value.bars.length >= 1) {
        const b = r.value.bars
        const close = b[b.length - 1].close
        const prev = b.length >= 2 ? b[b.length - 2].close : null
        map[s] = {
          close,
          chg: prev ? (close / prev - 1) * 100 : null,
        }
      } else {
        map[s] = { close: null, chg: null }
      }
    })
    prices.value = map
  } finally {
    refreshing.value = false
  }
}

function fmtClose(v: number | null): string {
  if (v == null) return '—'
  return v.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}

onMounted(() => {
  refresh()
  timer = window.setInterval(refresh, 60_000)
})
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<template>
  <aside class="watch-panel">
    <div class="watch-head">
      <span>自选列表</span>
      <button class="watch-add" title="把当前品种加入自选" @click="store.addCurrent()">＋</button>
    </div>
    <ul class="watch-list">
      <li
        v-for="it in store.watchlist"
        :key="it.symbol"
        :class="{ active: it.symbol === store.symbol }"
        @click="store.setSymbol(it.symbol)"
      >
        <div class="watch-main">
          <span class="watch-name" :title="it.symbol">{{ it.name }}</span>
          <span class="watch-symbol">{{ it.symbol }}</span>
        </div>
        <div class="watch-quote">
          <span class="watch-close">{{ fmtClose(prices[it.symbol]?.close ?? null) }}</span>
          <span
            v-if="prices[it.symbol]?.chg != null"
            class="watch-chg"
            :class="prices[it.symbol].chg! >= 0 ? 'pos' : 'neg'"
          >{{ prices[it.symbol].chg! >= 0 ? '+' : '' }}{{ prices[it.symbol].chg!.toFixed(2) }}%</span>
        </div>
        <button
          class="watch-remove"
          title="从自选移除"
          @click.stop="store.removeWatch(it.symbol)"
        >×</button>
      </li>
    </ul>
    <p v-if="!store.watchlist.length" class="hint" style="padding: 0 10px;">
      列表为空：搜索或打开一个品种后点右上角 ＋ 加入。
    </p>
  </aside>
</template>
