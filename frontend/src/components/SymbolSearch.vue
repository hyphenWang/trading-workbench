<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import type { SearchHit } from '../api'
import { datafeed } from '../datafeed/datafeed'
import { useWorkbench } from '../stores/workbench'

const store = useWorkbench()
const query = ref('')
const results = ref<SearchHit[]>([])
const open = ref(false)
let timer: number | undefined

async function search(q: string) {
  try {
    results.value = await datafeed.search(q)
    open.value = q.length > 0 && results.value.length > 0
  } catch {
    results.value = []
    open.value = false
  }
}

function onInput() {
  window.clearTimeout(timer)
  timer = window.setTimeout(() => {
    // 输入框内容就是当前品种（刚选中/初始状态）时不弹列表，避免遮挡图表
    if (query.value.trim() === store.symbol) {
      open.value = false
      return
    }
    search(query.value.trim())
  }, 250)
}

function pick(hit: SearchHit) {
  store.setSymbol(hit.symbol)
  query.value = hit.symbol
  open.value = false
}

function onBlur() {
  // 延迟关闭，允许 click 命中
  window.setTimeout(() => (open.value = false), 200)
}

onMounted(async () => {
  // 预取热门品种列表，但不弹出下拉
  try {
    results.value = await datafeed.search('')
  } catch { /* 忽略预取失败 */ }
})
watch(() => store.symbol, (s) => (query.value = s), { immediate: true })
</script>

<template>
  <div class="search-wrap">
    <input
      v-model="query"
      class="search-input"
      placeholder="搜索品种：BTCUSDT / AAPL / 600519 / RB0 ..."
      @input="onInput"
      @focus="onInput"
      @blur="onBlur"
    />
    <div v-if="open && results.length" class="search-results">
      <div v-for="hit in results" :key="hit.symbol" class="search-item" @mousedown.prevent="pick(hit)">
        <span class="sym">{{ hit.symbol }}</span>
        <span class="desc">{{ hit.name }}</span>
      </div>
    </div>
  </div>
</template>
