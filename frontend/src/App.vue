<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { socket } from './datafeed/socket'
import { backendAvailable } from './demo'
import SymbolSearch from './components/SymbolSearch.vue'
import ChartView from './components/ChartView.vue'
import BacktestPanel from './components/BacktestPanel.vue'
import Watchlist from './components/Watchlist.vue'
import { useWorkbench } from './stores/workbench'

const store = useWorkbench()
const demoMode = ref(false)

onMounted(async () => {
  store.initWatchlist()
  demoMode.value = !(await backendAvailable())
  if (demoMode.value) return // 演示模式：无后端，不建立实时连接
  socket.connect()
  socket.onStatus((s) => (store.wsStatus = s))
})
</script>

<template>
  <div class="layout">
    <header class="header">
      <div class="brand">本地<span>交易</span>工作台</div>
      <SymbolSearch />
      <div style="display: flex; gap: 4px;" v-if="store.symbolInfo">
        <button
          v-for="res in store.symbolInfo.supported_resolutions"
          :key="res"
          :class="{ active: res === store.resolution }"
          @click="store.setResolution(res)"
        >{{ res }}</button>
      </div>
      <div style="flex: 1"></div>
      <div
        v-if="!demoMode"
        style="display: flex; align-items: center; gap: 6px; color: var(--text-dim); font-size: 11px;"
      >
        <span
          class="ws-dot"
          :class="{ on: store.wsStatus === 'connected', off: store.wsStatus === 'disconnected' }"
        ></span>
        {{ store.wsStatus === 'connected' ? '实时已连接' : store.wsStatus === 'connecting' ? '连接中' : '实时已断开' }}
      </div>
    </header>
    <div v-if="demoMode" class="demo-banner">
      演示模式：未检测到本地后端，正在展示内置历史数据快照（BTCUSDT / 600519 / AAPL）。
      在本地运行 `uv run uvicorn app.main:app` 并刷新，即可解锁全部市场与实时行情、回测。
    </div>
    <main class="main" :class="{ 'with-banner': demoMode }">
      <Watchlist />
      <ChartView />
      <BacktestPanel />
    </main>
  </div>
</template>
