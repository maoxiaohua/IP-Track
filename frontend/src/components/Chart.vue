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
  (e: 'nodes-moved', positions: Record<string, [number, number]>): void
}>()

const chartRef = ref<HTMLElement>()
let chartInstance: echarts.ECharts | null = null
let resizeObserver: ResizeObserver | null = null
let pressStart: { x: number; y: number } | null = null

// 读取 graph 系列各节点当前布局坐标（节点拖动后 echarts 只更新 series data 的 layout，不回写 option）。
const readNodePositions = (): Record<string, [number, number]> => {
  const positions: Record<string, [number, number]> = {}
  const model = (chartInstance as any)?.getModel?.()
  const data = model?.getSeriesByIndex?.(0)?.getData?.()
  if (!data) return positions
  for (let i = 0; i < data.count(); i += 1) {
    const raw = data.getRawDataItem(i)
    const id = raw?.id ?? data.getName(i)
    const layout = data.getItemLayout(i)
    if (id && Array.isArray(layout) && Number.isFinite(layout[0]) && Number.isFinite(layout[1])) {
      positions[id] = [layout[0], layout[1]]
    }
  }
  return positions
}

const initChart = () => {
  if (!chartRef.value) return

  chartInstance = echarts.init(chartRef.value)
  chartInstance.setOption(props.option)
  chartInstance.on('click', (params: any) => {
    emit('chart-click', params)
  })
  chartInstance.on('mousedown', (params: any) => {
    pressStart = params?.dataType === 'node'
      ? { x: params.event?.offsetX ?? 0, y: params.event?.offsetY ?? 0 }
      : null
  })
  chartInstance.getZr().on('mouseup', (event: any) => {
    if (!pressStart) return
    const moved = Math.hypot(
      (event?.offsetX ?? 0) - pressStart.x,
      (event?.offsetY ?? 0) - pressStart.y
    )
    pressStart = null
    if (moved < 3) return
    emit('nodes-moved', readNodePositions())
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
