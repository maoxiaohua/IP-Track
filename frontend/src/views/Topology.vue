<template>
  <div class="topology-page">
    <el-card>
      <template #header>
        <div class="card-header">
          <div>
            <h2 style="margin: 0">网络拓扑</h2>
            <div class="sub-title">
              仅依据 LLDP / CDP 邻居事实建链；未纳管对端显示为未知节点，采集失败与不支持分别统计。
            </div>
          </div>
          <div class="header-actions">
            <el-tag v-if="!authStore.isLoggedIn" type="info" effect="plain">只读访客</el-tag>
            <el-tooltip :content="authStore.isLoggedIn ? '为所有在线交换机入队采集（离线设备已跳过）' : '访客只读，请登录后采集'" placement="top">
              <span>
                <el-button type="primary" :loading="collecting" :disabled="!authStore.isLoggedIn" @click="handleCollect">
                  <template #icon><el-icon><Refresh /></el-icon></template>
                  采集拓扑
                </el-button>
              </span>
            </el-tooltip>
            <el-tooltip :content="authStore.isLoggedIn ? '用已采集的邻居事实重算链路' : '访客只读，请登录后操作'" placement="top">
              <span>
                <el-button :loading="deriving" :disabled="!authStore.isLoggedIn" @click="handleDerive">
                  <template #icon><el-icon><Connection /></el-icon></template>
                  重算链路
                </el-button>
              </span>
            </el-tooltip>
            <el-button :loading="loadingGraph" @click="loadAll">
              <template #icon><el-icon><Refresh /></el-icon></template>
              刷新
            </el-button>
          </div>
        </div>
      </template>

      <el-row :gutter="12" class="coverage-row">
        <el-col :xs="12" :sm="8" :md="3">
          <el-statistic title="交换机" :value="coverage.switches_total" />
        </el-col>
        <el-col :xs="12" :sm="8" :md="3">
          <el-statistic title="已采集" :value="coverage.collected" />
        </el-col>
        <el-col :xs="12" :sm="8" :md="3">
          <el-statistic title="成功" :value="coverage.success" />
        </el-col>
        <el-col :xs="12" :sm="8" :md="3">
          <el-statistic title="部分成功" :value="coverage.partial" />
        </el-col>
        <el-col :xs="12" :sm="8" :md="3">
          <el-statistic title="不支持" :value="coverage.unsupported" />
        </el-col>
        <el-col :xs="12" :sm="8" :md="3">
          <el-statistic title="失败" :value="coverage.failed" />
        </el-col>
        <el-col :xs="12" :sm="8" :md="3">
          <el-statistic title="链路" :value="coverage.links.total || 0" />
        </el-col>
        <el-col :xs="12" :sm="8" :md="3">
          <el-statistic title="未知节点" :value="coverage.unknown_nodes" />
        </el-col>
      </el-row>

      <el-alert
        v-if="graphTruncated"
        type="warning"
        :closable="false"
        show-icon
        style="margin-bottom: 12px"
        title="链路数量超过单次绘图上限，图中已截断；请点击交换机节点后使用“以此为中心查看”。"
      />

      <div class="toolbar">
        <el-select v-model="filters.status" placeholder="全部状态" clearable style="width: 180px" @change="handleFilterChange">
          <el-option label="双向确认" value="confirmed" />
          <el-option label="单向（对端未纳管）" value="one_sided" />
          <el-option label="未解析" value="unresolved" />
          <el-option label="过期" value="stale" />
        </el-select>
        <el-select
          v-model="filters.switchStatus"
          placeholder="全部采集状态"
          clearable
          style="width: 180px"
          @change="handleCollectionFilterChange"
        >
          <el-option label="仅看采集成功" value="success" />
          <el-option label="部分成功" value="partial" />
          <el-option label="不支持" value="unsupported" />
          <el-option label="采集失败" value="failed" />
        </el-select>
        <el-select v-model="filters.deviceScope" style="width: 200px" @change="handleFilterChange">
          <el-option label="全部设备" value="" />
          <el-option label="仅网络设备（隐藏 PC/服务器/话机）" value="network" />
        </el-select>
        <el-input
          v-model="filters.keyword"
          placeholder="搜索设备名 / 端口 / 管理 IP"
          clearable
          style="width: 280px"
          @keyup.enter="handleFilterChange"
          @clear="handleFilterChange"
        />
        <el-button @click="handleFilterChange">查询</el-button>
        <el-button v-if="focusedSwitchId" type="warning" plain @click="clearFocus">取消聚焦</el-button>
      </div>

      <TopologyGraph
        :nodes="filteredGraphNodes"
        :links="filteredGraphLinks"
        :truncated="graphTruncated"
        :selected-id="selectedNode?.id || null"
        height="620px"
        @node-click="handleNodeClick"
      />
    </el-card>

    <el-card style="margin-top: 16px">
      <template #header>
        <div class="card-header">
          <h3 style="margin: 0">链路明细</h3>
          <el-text type="info">共 {{ linkTotal }} 条</el-text>
        </div>
      </template>
      <el-table :data="links" size="small" v-loading="loadingLinks">
        <el-table-column label="状态" width="150" #default="{ row }">
          <el-tag :type="statusTagType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
        </el-table-column>
        <el-table-column label="置信度" width="90" prop="confidence" />
        <el-table-column label="A 端" min-width="200" #default="{ row }">
          {{ row.a_sys_name || row.a_mgmt_ip || '未知' }}
          <el-text type="info" size="small">{{ row.a_port_name || '-' }}</el-text>
        </el-table-column>
        <el-table-column label="B 端" min-width="200" #default="{ row }">
          {{ row.b_sys_name || row.b_mgmt_ip || '未知' }}
          <el-text type="info" size="small">{{ row.b_port_name || '-' }}</el-text>
        </el-table-column>
        <el-table-column label="证据" width="100" prop="evidence" />
        <el-table-column label="聚合" width="80" #default="{ row }">
          <el-tag v-if="row.is_lag" size="small" type="success">LAG</el-tag>
          <span v-else>-</span>
        </el-table-column>
        <el-table-column label="最近发现" width="180" #default="{ row }">
          {{ formatTime(row.last_seen) }}
        </el-table-column>
      </el-table>
      <el-pagination
        v-model:current-page="filters.page"
        v-model:page-size="filters.pageSize"
        :total="linkTotal"
        :page-sizes="[20, 50, 100]"
        layout="total, prev, pager, next, sizes"
        style="margin-top: 12px"
        @current-change="loadLinks"
        @size-change="handleFilterChange"
      />
    </el-card>

    <el-drawer v-model="drawerVisible" :title="drawerTitle" size="520px">
      <template v-if="selectedNode">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="类型">
            {{ selectedNode.kind === 'switch' ? '已纳管交换机' : '未纳管节点' }}
          </el-descriptions-item>
          <el-descriptions-item label="名称">{{ selectedNode.label }}</el-descriptions-item>
          <el-descriptions-item label="管理 IP">{{ selectedNode.mgmt_ip || '-' }}</el-descriptions-item>
          <el-descriptions-item v-if="selectedNode.kind === 'switch'" label="厂商">{{ selectedNode.vendor || '-' }}</el-descriptions-item>
          <el-descriptions-item v-if="selectedNode.kind === 'switch'" label="采集状态">
            {{ selectedNode.collection_status || '未采集' }}
          </el-descriptions-item>
          <el-descriptions-item v-if="selectedNode.kind === 'switch'" label="最近采集">
            {{ formatTime(selectedNode.last_collection_at) }}
          </el-descriptions-item>
          <el-descriptions-item v-if="selectedNode.kind === 'unknown'" label="设备类别">{{ deviceClassLabel(selectedNode.device_class) }}</el-descriptions-item>
          <el-descriptions-item v-if="selectedNode.kind === 'unknown'" label="置信度">
            {{ selectedNode.device_confidence != null ? `${selectedNode.device_confidence}%` : '-' }}
          </el-descriptions-item>
          <el-descriptions-item v-if="selectedNode.kind === 'unknown'" label="判定依据">
            {{ selectedNode.device_reasons && selectedNode.device_reasons.length ? selectedNode.device_reasons.join('；') : '-' }}
          </el-descriptions-item>
          <el-descriptions-item v-if="selectedNode.kind === 'unknown'" label="节点键">{{ selectedNode.id }}</el-descriptions-item>
          <el-descriptions-item label="链路数">{{ selectedNode.degree }}</el-descriptions-item>
        </el-descriptions>

        <div class="drawer-actions">
          <el-button v-if="selectedNode.kind === 'switch'" type="primary" plain @click="focusSelected">
            以此为中心查看
          </el-button>
          <el-button v-if="selectedNode.kind === 'switch'" @click="openSwitchDetail">打开交换机详情</el-button>
        </div>

        <template v-if="selectedNode.kind === 'switch'">
          <el-tabs v-model="drawerTab">
            <el-tab-pane label="邻居" name="neighbors">
              <el-empty v-if="!neighbors.length" description="该交换机暂无已采集的邻居" :image-size="60" />
              <el-table v-else :data="neighbors" size="small">
                <el-table-column label="协议" width="70" prop="protocol" />
                <el-table-column label="本端" min-width="120" #default="{ row }">
                  {{ row.local_port_id || row.local_port_desc || row.local_if_index }}
                </el-table-column>
                <el-table-column label="远端" min-width="160" #default="{ row }">
                  {{ row.remote_sys_name || row.remote_chassis_id || '-' }}
                  <el-text type="info" size="small">{{ row.remote_port_id || row.remote_port_desc || '-' }}</el-text>
                </el-table-column>
                <el-table-column label="远端管理 IP" width="140" prop="remote_mgmt_addr" />
              </el-table>
            </el-tab-pane>
            <el-tab-pane label="接口" name="interfaces">
              <el-empty v-if="!interfaces.length" description="该交换机暂无已采集的接口" :image-size="60" />
              <el-table v-else :data="interfaces" size="small">
                <el-table-column label="接口" min-width="140" #default="{ row }">
                  {{ row.if_name || row.if_descr || row.if_index }}
                </el-table-column>
                <el-table-column label="描述" min-width="120" prop="if_alias" />
                <el-table-column label="状态" width="110" #default="{ row }">
                  {{ row.admin_status || '-' }} / {{ row.oper_status || '-' }}
                </el-table-column>
                <el-table-column label="速率(Mbps)" width="100" prop="speed_mbps" />
              </el-table>
            </el-tab-pane>
          </el-tabs>
        </template>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Connection, Refresh } from '@element-plus/icons-vue'
import TopologyGraph from '@/components/TopologyGraph.vue'
import { useAuthStore } from '@/stores/auth'
import {
  TOPOLOGY_LINK_STATUS_LABEL,
  collectTopology,
  deriveTopologyLinks,
  getTopologyGraph,
  getTopologyInterfaces,
  getTopologyLinks,
  getTopologyNeighbors,
  getTopologyStatus,
  type TopologyCoverage,
  type TopologyInterface,
  type TopologyLink,
  type TopologyNeighbor,
  type TopologyNode
} from '@/api/topology'

// 采集是异步队列任务，入队后延迟刷新一次，让用户不用手动点刷新。
const COLLECT_REFRESH_DELAY_MS = 6000

const router = useRouter()
const authStore = useAuthStore()

const emptyCoverage = (): TopologyCoverage => ({
  switches_total: 0,
  switches_enabled: 0,
  auto_collect: 0,
  collected: 0,
  not_collected: 0,
  success: 0,
  partial: 0,
  unsupported: 0,
  failed: 0,
  links: {},
  unknown_nodes: 0
})

const coverage = ref<TopologyCoverage>(emptyCoverage())
const graphNodes = ref<TopologyNode[]>([])
const graphLinks = ref<TopologyLink[]>([])
const graphTruncated = ref(false)
const links = ref<TopologyLink[]>([])
const linkTotal = ref(0)

const loadingGraph = ref(false)
const loadingLinks = ref(false)
const collecting = ref(false)
const deriving = ref(false)

const focusedSwitchId = ref<number | null>(null)
const selectedNode = ref<TopologyNode | null>(null)
const drawerVisible = ref(false)
const drawerTab = ref('neighbors')
const neighbors = ref<TopologyNeighbor[]>([])
const interfaces = ref<TopologyInterface[]>([])

const filters = reactive({
  status: '',
  switchStatus: '',
  deviceScope: '',
  keyword: '',
  page: 1,
  pageSize: 50
})

// 非网络设备（PC / 服务器 / 话机）：LLDP capability 或系统描述识别出来的终端。
const NON_NETWORK_CLASSES = ['host', 'phone']

// 与后端 _device_class 的取值一一对应，避免详情里直接暴露英文枚举。
const DEVICE_CLASS_LABEL: Record<string, string> = {
  switch: '交换机（LLDP 桥）',
  router: '路由器',
  'wlan-ap': '无线 AP',
  phone: 'IP 话机',
  host: 'PC / 服务器',
  hub: '集线器（重复器）',
  unknown: '未识别'
}

const deviceClassLabel = (value: string | null) => DEVICE_CLASS_LABEL[value || ''] || '未识别'

const isNetworkNode = (node: TopologyNode) =>
  node.kind === 'switch' || !NON_NETWORK_CLASSES.includes(node.device_class || '')

const filteredGraphNodes = computed(() =>
  filters.deviceScope === 'network' ? graphNodes.value.filter(isNetworkNode) : graphNodes.value
)

const filteredGraphLinks = computed(() => {
  if (filters.deviceScope !== 'network') return graphLinks.value
  const visible = new Set(filteredGraphNodes.value.map((node) => node.id))
  return graphLinks.value.filter(
    (link) => visible.has(link.source) && visible.has(link.target)
  )
})

const drawerTitle = computed(() => selectedNode.value?.label || '节点详情')

const statusLabel = (status: string) => TOPOLOGY_LINK_STATUS_LABEL[status] || status

const statusTagType = (status: string) => {
  switch (status) {
    case 'confirmed':
      return 'success'
    case 'one_sided':
      return 'warning'
    case 'unresolved':
      return 'danger'
    default:
      return 'info'
  }
}

const formatTime = (value: string | null) => {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

const errorDetail = (error: any, fallback: string) =>
  error?.response?.data?.detail || fallback

const loadGraph = async (focusSwitchId?: number | null) => {
  loadingGraph.value = true
  try {
    const params: { focus_switch_id?: number; depth?: number; switch_status?: string } =
      focusSwitchId ? { focus_switch_id: focusSwitchId, depth: 2 } : {}
    if (filters.switchStatus) params.switch_status = filters.switchStatus
    const { data } = await getTopologyGraph(params)
    graphNodes.value = data.nodes || []
    graphLinks.value = data.links || []
    graphTruncated.value = !!data.truncated
    if (data.coverage) coverage.value = data.coverage
  } catch (error: any) {
    ElMessage.error(errorDetail(error, '加载拓扑图失败'))
  } finally {
    loadingGraph.value = false
  }
}

const loadLinks = async () => {
  loadingLinks.value = true
  try {
    const { data } = await getTopologyLinks({
      status: filters.status || undefined,
      q: filters.keyword.trim() || undefined,
      page: filters.page,
      page_size: filters.pageSize
    })
    links.value = data.items || []
    linkTotal.value = data.total || 0
  } catch (error: any) {
    ElMessage.error(errorDetail(error, '加载链路失败'))
  } finally {
    loadingLinks.value = false
  }
}

const loadCoverage = async () => {
  try {
    const { data } = await getTopologyStatus()
    coverage.value = data
  } catch (error) {
    // 覆盖统计失败不应阻断图与表格，静默保留上一次结果。
  }
}

const loadAll = async () => {
  await Promise.all([loadGraph(focusedSwitchId.value), loadLinks(), loadCoverage()])
}

const handleFilterChange = () => {
  filters.page = 1
  loadLinks()
}

const handleCollectionFilterChange = () => {
  loadGraph(focusedSwitchId.value)
}

const handleCollect = async () => {
  if (!authStore.isLoggedIn) {
    ElMessage.warning('访客只读，请先登录再采集拓扑')
    return
  }
  collecting.value = true
  try {
    const { data } = await collectTopology()
    const skipped = Number(data.skipped || 0)
    if (data.queued > 0) {
      ElMessage.success(
        skipped > 0
          ? `已为 ${data.queued} 台在线交换机入队采集（${skipped} 台正在采集中，已跳过），稍后自动刷新`
          : `已为 ${data.queued} 台在线交换机入队采集，稍后自动刷新`
      )
      window.setTimeout(() => { loadAll() }, COLLECT_REFRESH_DELAY_MS)
    } else {
      ElMessage.info(data.message || '没有需要采集的在线交换机（离线设备已跳过）')
    }
  } catch (error: any) {
    ElMessage.error(errorDetail(error, '触发拓扑采集失败'))
  } finally {
    collecting.value = false
  }
}

const handleDerive = async () => {
  if (!authStore.isLoggedIn) {
    ElMessage.warning('访客只读，请先登录再重算链路')
    return
  }
  deriving.value = true
  try {
    await deriveTopologyLinks()
    ElMessage.success('链路已重新计算')
    await loadAll()
  } catch (error: any) {
    ElMessage.error(errorDetail(error, '重算链路失败'))
  } finally {
    deriving.value = false
  }
}

const loadSelectedDetails = async (node: TopologyNode) => {
  neighbors.value = []
  interfaces.value = []
  if (node.kind !== 'switch') return
  try {
    const [neighborRes, interfaceRes] = await Promise.all([
      getTopologyNeighbors({ switch_id: node.switch_id, limit: 500 }),
      getTopologyInterfaces({ switch_id: node.switch_id, limit: 1000 })
    ])
    neighbors.value = neighborRes.data || []
    interfaces.value = interfaceRes.data || []
  } catch (error: any) {
    ElMessage.error(errorDetail(error, '加载节点详情失败'))
  }
}

const handleNodeClick = async (node: TopologyNode) => {
  selectedNode.value = node
  drawerVisible.value = true
  drawerTab.value = 'neighbors'
  await loadSelectedDetails(node)
}

const focusSelected = async () => {
  if (selectedNode.value?.kind !== 'switch') return
  focusedSwitchId.value = selectedNode.value.switch_id
  await loadGraph(focusedSwitchId.value)
}

const clearFocus = async () => {
  focusedSwitchId.value = null
  await loadGraph(null)
}

const openSwitchDetail = () => {
  if (selectedNode.value?.kind !== 'switch') return
  router.push(`/switches/${selectedNode.value.switch_id}`)
}

onMounted(() => {
  loadAll()
})
</script>

<style scoped>
.topology-page {
  padding: 20px;
  background-color: #f5f7fa;
  min-height: 100vh;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.sub-title {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.coverage-row {
  margin-bottom: 12px;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.drawer-actions {
  display: flex;
  gap: 8px;
  margin: 12px 0;
}
</style>
