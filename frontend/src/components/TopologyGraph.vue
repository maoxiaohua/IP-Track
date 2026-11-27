<template>
  <Chart :option="option" :height="height" @chart-click="handleClick" @nodes-moved="handleNodesMoved" />
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import Chart from './Chart.vue'
import type { TopologyNode, TopologyLink } from '@/api/topology'

interface Props {
  nodes: TopologyNode[]
  links: TopologyLink[]
  truncated?: boolean
  selectedId?: string | null
  height?: string
}

const props = withDefaults(defineProps<Props>(), {
  truncated: false,
  selectedId: null,
  height: '640px'
})

const emit = defineEmits<{
  (e: 'node-click', node: TopologyNode): void
}>()

// 规模阈值：超过后只降级展示，不改变真实数据。
const HIDE_LABEL_OVER = 300
const DISABLE_ANIMATION_OVER = 800

// 布局常量：仅控制画布间距，与具体网络环境无关。
const LAYER_GAP_X = 80 // 相邻层之间的水平留白
const ROW_GAP_Y = 30 // 同层节点之间的垂直留白
const COMP_GAP = 80 // 连通分量之间 / 主图与孤立区之间的留白
const GRAPH_PADDING = 40 // 画布四周留白
const PACK_ASPECT = 1.8 // 分量装箱的目标宽高比
const VIEW_WIDTH = 1000 // 初始适配的参考视口
const VIEW_HEIGHT = 560
const MIN_ZOOM = 0.7 // 初始缩放下限（可 roam 继续缩放）

interface Positioned {
  node: TopologyNode
  x: number
  y: number
}

interface LayoutComponent {
  positions: Map<string, [number, number]>
  width: number
  height: number
  offsetX: number
  offsetY: number
}

interface LayoutResult {
  positions: Map<string, Positioned>
  width: number
  height: number
  center: [number, number]
  zoom: number
}

// 用户手动拖动的节点坐标：优先级高于自动分层布局，避免点击/双击节点后被重置。
const userPositions = ref<Record<string, [number, number]>>({})

const handleNodesMoved = (positions: Record<string, [number, number]>) => {
  userPositions.value = { ...userPositions.value, ...positions }
}

// 图数据被整体替换（刷新 / 聚焦 / 取消聚焦 / 筛选）时丢弃旧拖动坐标，避免落到新布局的错误位置。
watch([() => props.nodes, () => props.links], () => {
  userPositions.value = {}
})

// 节点尺寸：布局间距与 symbolSize 共用，避免两处公式漂移。
function nodeSize(node: TopologyNode): [number, number] {
  if (node.kind === 'switch') {
    return [Math.min(180, 60 + node.label.length * 9), 38]
  }
  return [34, 34]
}

/**
 * 自动布局（纯前端预计算，避免 force 布局在数百节点时卡死）：
 * - 仅有连线的节点参与主图：按连通分量 BFS 分层，层号即 x 方向；
 * - 层内做 2 轮往返重心排序减少连线交叉；
 * - 层/行间距按节点实际尺寸计算，分量按高度降序做 shelf 装箱；
 * - 未连线（degree=0）设备排在主图下方，独立网格区展示，不参与主图缩放。
 */
function computeLayout(nodes: TopologyNode[], links: TopologyLink[]): LayoutResult {
  const positions = new Map<string, Positioned>()
  const result: LayoutResult = {
    positions,
    width: VIEW_WIDTH,
    height: VIEW_HEIGHT,
    center: [VIEW_WIDTH / 2, VIEW_HEIGHT / 2],
    zoom: 1
  }
  if (nodes.length === 0) return result

  const nodeById = new Map<string, TopologyNode>()
  for (const node of nodes) nodeById.set(node.id, node)
  const labelOf = (id: string) => nodeById.get(id)?.label || id
  const sizeOf = (id: string): [number, number] => {
    const node = nodeById.get(id)
    return node ? nodeSize(node) : [34, 34]
  }

  const adjacency = new Map<string, string[]>()
  for (const node of nodes) adjacency.set(node.id, [])
  for (const link of links) {
    const from = adjacency.get(link.source)
    const to = adjacency.get(link.target)
    if (from && to) {
      from.push(link.target)
      to.push(link.source)
    }
  }

  const connected: TopologyNode[] = []
  const isolated: TopologyNode[] = []
  for (const node of nodes) {
    if ((adjacency.get(node.id) || []).length > 0) connected.push(node)
    else isolated.push(node)
  }

  // 1) 每个连通分量以度数最高节点为根 BFS 分层（度数 → 交换机 → 名称 → id 依次决胜）。
  const roots = [...connected].sort((a, b) => {
    const degreeA = (adjacency.get(a.id) || []).length
    const degreeB = (adjacency.get(b.id) || []).length
    if (degreeB !== degreeA) return degreeB - degreeA
    if (a.kind !== b.kind) return a.kind === 'switch' ? -1 : 1
    const byLabel = a.label.localeCompare(b.label)
    return byLabel !== 0 ? byLabel : a.id.localeCompare(b.id)
  })

  const visited = new Set<string>()
  const components: LayoutComponent[] = []
  for (const root of roots) {
    if (visited.has(root.id)) continue

    const depth = new Map<string, number>()
    const layers: string[][] = []
    depth.set(root.id, 0)
    visited.add(root.id)
    const queue: string[] = [root.id]
    for (let head = 0; head < queue.length; head += 1) {
      const current = queue[head]
      const currentDepth = depth.get(current) || 0
      if (!layers[currentDepth]) layers[currentDepth] = []
      layers[currentDepth].push(current)
      for (const neighbor of adjacency.get(current) || []) {
        if (visited.has(neighbor)) continue
        visited.add(neighbor)
        depth.set(neighbor, currentDepth + 1)
        queue.push(neighbor)
      }
    }

    for (const layer of layers) {
      layer.sort((a, b) => {
        const byLabel = labelOf(a).localeCompare(labelOf(b))
        return byLabel !== 0 ? byLabel : a.localeCompare(b)
      })
    }

    // 2) 2 轮往返重心排序：无参照邻居的节点保持原相对位置。
    const orderOf = (layer: string[]): Map<string, number> => {
      const index = new Map<string, number>()
      layer.forEach((id, i) => index.set(id, i))
      return index
    }
    const sortByBarycenter = (layer: string[], reference: Map<string, number>) => {
      const base = orderOf(layer)
      const weight = new Map<string, number>()
      for (const id of layer) {
        let sum = 0
        let count = 0
        for (const neighbor of adjacency.get(id) || []) {
          const index = reference.get(neighbor)
          if (index === undefined) continue
          sum += index
          count += 1
        }
        weight.set(id, count > 0 ? sum / count : base.get(id) || 0)
      }
      layer.sort((a, b) => {
        const diff = (weight.get(a) || 0) - (weight.get(b) || 0)
        return diff !== 0 ? diff : (base.get(a) || 0) - (base.get(b) || 0)
      })
    }
    for (let round = 0; round < 2; round += 1) {
      for (let d = 1; d < layers.length; d += 1) sortByBarycenter(layers[d], orderOf(layers[d - 1]))
      for (let d = layers.length - 2; d >= 0; d -= 1) sortByBarycenter(layers[d], orderOf(layers[d + 1]))
    }

    // 3) 层间距按该层节点最大宽度计算，同层按实际高度逐个累加并垂直居中。
    const layerWidth = layers.map((layer) => Math.max(...layer.map((id) => sizeOf(id)[0])))
    const layerHeight = layers.map((layer) => {
      const sum = layer.reduce((acc, id) => acc + sizeOf(id)[1], 0)
      return sum + Math.max(layer.length - 1, 0) * ROW_GAP_Y
    })
    const layerX: number[] = []
    layers.forEach((_, d) => {
      layerX[d] = d === 0
        ? layerWidth[0] / 2
        : layerX[d - 1] + layerWidth[d - 1] / 2 + LAYER_GAP_X + layerWidth[d] / 2
    })

    const localPositions = new Map<string, [number, number]>()
    let minX = Infinity
    let minY = Infinity
    let maxX = -Infinity
    let maxY = -Infinity
    layers.forEach((layer, d) => {
      let cursorY = -layerHeight[d] / 2
      for (const id of layer) {
        const [width, height] = sizeOf(id)
        const cx = layerX[d]
        const cy = cursorY + height / 2
        cursorY += height + ROW_GAP_Y
        localPositions.set(id, [cx, cy])
        minX = Math.min(minX, cx - width / 2)
        maxX = Math.max(maxX, cx + width / 2)
        minY = Math.min(minY, cy - height / 2)
        maxY = Math.max(maxY, cy + height / 2)
      }
    })
    const normalized = new Map<string, [number, number]>()
    localPositions.forEach(([x, y], id) => normalized.set(id, [x - minX, y - minY]))
    components.push({ positions: normalized, width: maxX - minX, height: maxY - minY, offsetX: 0, offsetY: 0 })
  }

  // 4) 分量按高度降序做 shelf 装箱，避免只纵向堆叠把画布拉成一条细线。
  let mainWidth = 0
  let mainHeight = 0
  if (components.length > 0) {
    const totalArea = components.reduce((sum, comp) => sum + comp.width * comp.height, 0)
    const widest = Math.max(...components.map((comp) => comp.width))
    const targetWidth = Math.max(widest, Math.sqrt(totalArea * PACK_ASPECT))
    const ordered = [...components].sort((a, b) => b.height - a.height)
    let cursorX = 0
    let cursorY = 0
    let rowHeight = 0
    for (const comp of ordered) {
      if (cursorX > 0 && cursorX + comp.width > targetWidth) {
        cursorX = 0
        cursorY += rowHeight + COMP_GAP
        rowHeight = 0
      }
      comp.offsetX = cursorX
      comp.offsetY = cursorY
      cursorX += comp.width + COMP_GAP
      rowHeight = Math.max(rowHeight, comp.height)
      mainWidth = Math.max(mainWidth, cursorX - COMP_GAP)
    }
    mainHeight = cursorY + rowHeight
  }

  // 5) 未连线设备：主图下方独立网格区（按名称排序，列数按目标宽高比推算）。
  let isolatedWidth = 0
  let isolatedHeight = 0
  let isolatedOffsetY = 0
  if (isolated.length > 0) {
    isolated.sort((a, b) => {
      const byLabel = a.label.localeCompare(b.label)
      return byLabel !== 0 ? byLabel : a.id.localeCompare(b.id)
    })
    const maxWidth = Math.max(...isolated.map((node) => nodeSize(node)[0]))
    const maxHeight = Math.max(...isolated.map((node) => nodeSize(node)[1]))
    const cellWidth = maxWidth + 40
    const cellHeight = maxHeight + 24
    const cols = Math.min(
      isolated.length,
      Math.max(1, Math.round(Math.sqrt((isolated.length * cellHeight) / cellWidth * PACK_ASPECT)))
    )
    const rows = Math.ceil(isolated.length / cols)
    isolatedWidth = cols * cellWidth
    isolatedHeight = rows * cellHeight
    isolatedOffsetY = components.length > 0 ? mainHeight + 2 * COMP_GAP : 0
    isolated.forEach((node, index) => {
      const row = Math.floor(index / cols)
      const col = index % cols
      positions.set(node.id, {
        node,
        x: col * cellWidth + cellWidth / 2 + GRAPH_PADDING,
        y: isolatedOffsetY + row * cellHeight + cellHeight / 2 + GRAPH_PADDING
      })
    })
  }

  for (const comp of components) {
    comp.positions.forEach(([x, y], id) => {
      const node = nodeById.get(id)
      if (!node) return
      positions.set(id, {
        node,
        x: x + comp.offsetX + GRAPH_PADDING,
        y: y + comp.offsetY + GRAPH_PADDING
      })
    })
  }

  // 6) series 的 width/height 取整张画布（含节点尺寸与留白），使数据坐标 ≈ 画布像素；
  //    初始只对准主图并等比缩放，孤立区需要向下平移查看。
  const hasMain = components.length > 0
  const fullWidth = Math.max(mainWidth, isolatedWidth) + GRAPH_PADDING * 2
  const fullHeight = Math.max(mainHeight, isolatedOffsetY + isolatedHeight) + GRAPH_PADDING * 2
  const focusWidth = hasMain ? mainWidth : isolatedWidth
  const focusHeight = hasMain ? mainHeight : isolatedHeight
  const fit = Math.min(
    focusWidth > 0 ? VIEW_WIDTH / focusWidth : 1,
    focusHeight > 0 ? VIEW_HEIGHT / focusHeight : 1,
    1
  )

  return {
    positions,
    width: fullWidth,
    height: fullHeight,
    center: hasMain
      ? [GRAPH_PADDING + mainWidth / 2, GRAPH_PADDING + mainHeight / 2]
      : [GRAPH_PADDING + isolatedWidth / 2, GRAPH_PADDING + isolatedHeight / 2],
    zoom: Math.min(Math.max(fit, MIN_ZOOM), 1)
  }
}

const nodeColor = (node: TopologyNode): string => {
  if (node.kind === 'unknown') return '#e6a23c'
  switch (node.collection_status) {
    case 'failed':
      return '#f56c6c'
    case 'unsupported':
      return '#909399'
    case 'partial':
      return '#e6a23c'
    case 'success':
      return '#409eff'
    default:
      return '#c0c4cc'
  }
}

const linkStyle = (link: TopologyLink) => {
  const width = link.is_lag ? 3 : 1.5
  switch (link.status) {
    case 'confirmed':
      return { type: 'solid', width, color: '#67c23a' }
    case 'one_sided':
      return { type: 'dashed', width, color: '#409eff' }
    case 'unresolved':
      return { type: [4, 4] as number[], width, color: '#f56c6c' }
    case 'stale':
      return { type: 'dotted', width, color: '#c0c4cc' }
    default:
      return { type: 'solid', width, color: '#909399' }
  }
}

const option = computed(() => {
  const showLabel = props.nodes.length <= HIDE_LABEL_OVER
  const animate = props.nodes.length <= DISABLE_ANIMATION_OVER
  const layout = computeLayout(props.nodes, props.links)

  const data = props.nodes.map((node) => {
    const position = layout.positions.get(node.id)
    const moved = userPositions.value[node.id]
    const isSelected = props.selectedId === node.id
    const isSwitch = node.kind === 'switch'
    const unknownClass = node.kind === 'unknown' ? node.device_class : null
    // 终端（PC/话机）只降透明度，不隐藏；unknown 始终可见。
    const isTerminal = unknownClass === 'host' || unknownClass === 'phone'
    const [nodeWidth, nodeHeight] = nodeSize(node)
    const labelStyle: Record<string, unknown> = {
      show: showLabel,
      color: isSwitch ? '#ffffff' : '#303133',
      fontSize: 12,
      formatter: node.label
    }
    if (isSwitch) {
      labelStyle.width = Math.max(nodeWidth - 10, 20)
      labelStyle.overflow = 'truncate'
      labelStyle.ellipsis = '…'
    }
    const statusText = node.kind === 'switch' ? `采集状态：${node.collection_status || '未采集'}` : '未纳管设备'
    return {
      id: node.id,
      name: node.id,
      value: node.label,
      x: moved?.[0] ?? position?.x ?? 0,
      y: moved?.[1] ?? position?.y ?? 0,
      symbol: isSwitch ? 'roundRect' : 'diamond',
      symbolSize: [nodeWidth, nodeHeight],
      itemStyle: {
        color: nodeColor(node),
        borderColor: isSelected ? '#303133' : isSwitch ? '#ffffff' : '#e6a23c',
        borderWidth: isSelected ? 3 : isSwitch ? 1 : 2,
        borderType: isSwitch ? 'solid' : 'dashed',
        opacity: isSwitch ? 1 : isTerminal ? 0.45 : 0.9
      },
      label: labelStyle,
      tooltip: {
        formatter: [
          `<b>${node.label}</b>`,
          node.kind === 'switch' ? `管理 IP：${node.mgmt_ip || '-'}` : `未知节点：${node.id}`,
          node.kind === 'switch' ? `厂商：${node.vendor || '-'}` : null,
          node.kind === 'unknown'
            ? `设备类别：${unknownClass || '未识别'}${node.device_confidence != null ? `（置信度 ${node.device_confidence}%）` : ''}`
            : null,
          node.kind === 'unknown' && node.device_reasons?.length
            ? `判定依据：${node.device_reasons.join('；')}`
            : null,
          statusText,
          `邻居/链路数：${node.degree}`
        ].filter(Boolean).join('<br/>')
      },
      topologyNode: node
    }
  })

  const links = props.links.map((link) => {
    const style = linkStyle(link)
    return {
      source: link.source,
      target: link.target,
      lineStyle: {
        type: style.type,
        width: style.width,
        color: style.color,
        curveness: 0
      },
      tooltip: {
        formatter: [
          `${link.a_port_name || '-'} ↔ ${link.b_port_name || '-'}`,
          `状态：${link.status}（置信度 ${link.confidence}）`,
          `证据：${link.evidence || '-'}`,
          link.conflict_reason ? `冲突：${link.conflict_reason}` : null
        ].filter(Boolean).join('<br/>')
      }
    }
  })

  return {
    animation: animate,
    tooltip: { trigger: 'item' },
    series: [
      {
        type: 'graph',
        layout: 'none',
        roam: true,
        draggable: true,
        width: layout.width,
        height: layout.height,
        center: layout.center,
        zoom: layout.zoom,
        // 缩放时节点与位置同比缩放，任何倍率下都不会出现「间距变小而节点不变大」的重叠。
        nodeScaleRatio: 1,
        data,
        links,
        emphasis: { focus: 'adjacency' },
        lineStyle: { opacity: 0.8 }
      }
    ],
    graphic: props.nodes.length === 0
      ? [{ type: 'text', left: 'center', top: 'middle', style: { text: '暂无拓扑数据，请先采集拓扑', fill: '#909399', fontSize: 14 } }]
      : []
  }
})

const handleClick = (params: any) => {
  if (params?.dataType !== 'node' || !params?.data?.topologyNode) return
  emit('node-click', params.data.topologyNode as TopologyNode)
}
</script>
