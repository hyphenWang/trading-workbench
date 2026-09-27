<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { ChartController } from '../chartApi'
import { useWorkbench } from '../stores/workbench'

const store = useWorkbench()
const container = ref<HTMLElement | null>(null)
const error = ref('')
let controller: ChartController | null = null

async function load() {
  if (!controller) return
  error.value = ''
  try {
    const info = await controller.setSymbol(store.symbol, store.resolution)
    store.symbolInfo = info
    if (store.resolution !== controller.currentResolution) {
      store.setResolution(controller.currentResolution)
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

onMounted(() => {
  if (!container.value) return
  controller = new ChartController()
  controller.init(container.value)
  load()
})

onUnmounted(() => {
  controller?.destroy()
  controller = null
})

watch(() => store.symbol, load)
watch(() => store.resolution, (res, prev) => {
  // 由 setSymbol 内部触发的周期回退不再重新加载，避免死循环
  if (res !== prev && controller && res !== controller.currentResolution) load()
})
</script>

<template>
  <div class="chart-area">
    <div ref="container" class="chart-container"></div>
    <div v-if="error" class="chart-error">加载失败：{{ error }}（若是加密货币/美股，请检查后端代理设置）</div>
  </div>
</template>
