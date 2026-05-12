<template>
  <div ref="chartRef" :style="{ width: width, height: height }"></div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch, onUnmounted } from 'vue'
import * as echarts from 'echarts'

interface Props {
  option: any
  width?: string
  height?: string
}

const props = withDefaults(defineProps<Props>(), {
  width: '100%',
  height: '400px'
})

const emit = defineEmits<{
  (e: 'chart-click', params: any): void
}>()

const chartRef = ref<HTMLElement>()
let chartInstance: echarts.ECharts | null = null
let resizeObserver: ResizeObserver | null = null

const initChart = () => {
  if (!chartRef.value) return

  chartInstance = echarts.init(chartRef.value)
  chartInstance.setOption(props.option)
  chartInstance.on('click', (params: any) => {
    emit('chart-click', params)
  })

  resizeObserver = new ResizeObserver(() => {
    chartInstance?.resize()
  })
  resizeObserver.observe(chartRef.value)
}

const updateChart = () => {
  if (chartInstance && props.option) {
    chartInstance.setOption(props.option, true)
  }
}

watch(() => props.option, updateChart, { deep: true })

onMounted(() => {
  initChart()
})

onUnmounted(() => {
  resizeObserver?.disconnect()
  chartInstance?.dispose()
})
</script>

<style scoped>
div {
  min-height: 200px;
}
</style>
