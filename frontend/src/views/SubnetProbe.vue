<template>
  <div class="subnet-probe">
    <el-card>
      <template #header>
        <div class="card-header">
          <div>
            <h2 style="margin: 0">子网存活快速探测</h2>
            <div class="sub-title">
              临时工具：批量 ping 检测网段里是否还有存活 IP，只做 ICMP 探测，不写入 IPAM。
            </div>
          </div>
        </div>
      </template>

      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="支持每行一个网段（如 10.1.0.0/24）或单个 IP（按 /32 处理），可用空格、逗号分隔，# 开头为注释；重复网段会自动去重。"
        style="margin-bottom: 12px"
      />

      <el-input
        v-model="subnetText"
        type="textarea"
        :rows="8"
        resize="vertical"
        placeholder="10.60.0.0/24&#10;10.60.1.0/24&#10;10.61.0.0/24"
        :disabled="isRunning"
      />

      <div class="parse-line">
        <el-text v-if="parsing" type="info">正在识别…</el-text>
        <template v-else>
          <el-text type="primary">
            识别到 {{ parsedCount }} 个网段 / 共 {{ totalHosts }} 个待探测 IP
          </el-text>
          <el-text v-if="parseError" type="danger" style="margin-left: 12px">{{ parseError }}</el-text>
        </template>
      </div>

      <el-alert
        v-if="invalidLines.length"
        type="warning"
        :closable="false"
        show-icon
        style="margin-top: 8px"
        :title="`有 ${invalidLines.length} 行无法识别，已忽略`"
      >
        <div class="invalid-list">{{ invalidLines.slice(0, 10).join('、') }}{{ invalidLines.length > 10 ? ' 等' : '' }}</div>
      </el-alert>

      <el-divider content-position="left">扫描参数</el-divider>

      <el-form label-width="110px" :disabled="isRunning">
        <el-row :gutter="16">
          <el-col :xs="24" :sm="12" :md="6">
            <el-form-item label="并发数">
              <el-input-number v-model="concurrency" :min="10" :max="500" :step="10" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :md="6">
            <el-form-item label="超时(秒)">
              <el-input-number v-model="timeout" :min="0.2" :max="5" :step="0.1" :precision="1" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :md="6">
            <el-form-item label="模式">
              <el-radio-group v-model="mode">
                <el-radio-button label="fast">快速</el-radio-button>
                <el-radio-button label="full">完整</el-radio-button>
              </el-radio-group>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :md="6">
            <el-form-item label="网关优先">
              <el-switch v-model="gatewayFirst" :disabled="isRunning || mode === 'full'" />
              <el-text type="info" size="small" style="margin-left: 8px">仅快速模式</el-text>
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>

      <el-text type="info" size="small">
        快速模式：网段内一旦发现存活 IP 即停止该网段剩余探测（只回答"有没有"）；完整模式：扫完整个网段，给出精确存活数量（慢很多）。
      </el-text>

      <div class="actions">
        <el-button type="primary" :loading="starting" :disabled="isRunning || !parsedCount" @click="handleStart">
          <el-icon><Search /></el-icon>
          <span>开始扫描</span>
        </el-button>
        <el-button type="danger" plain :disabled="!isRunning" :loading="cancelling" @click="handleCancel">
          <el-icon><CircleClose /></el-icon>
          <span>停止</span>
        </el-button>
        <el-button :disabled="!results.length" @click="handleExport">
          <el-icon><Download /></el-icon>
          <span>导出 Excel</span>
        </el-button>
      </div>
    </el-card>

    <el-card v-if="status || results.length" style="margin-top: 16px">
      <template #header>
        <div class="card-header">
          <h3 style="margin: 0">扫描进度</h3>
          <el-tag :type="statusTagType" size="small">{{ statusText }}</el-tag>
        </div>
      </template>

      <el-progress
        :percentage="progressPercent"
        :status="progressStatus"
        :stroke-width="18"
        text-inside
      />

      <div class="progress-line">
        <span>已探测网段：{{ summary.checked_subnets }} / {{ summary.total_subnets }}</span>
        <span>已发出 ping：{{ summary.pings_sent }}</span>
        <span>已用时：{{ formatDuration(elapsedSeconds) }}</span>
        <span>预计剩余：{{ etaSeconds === null ? '—' : formatDuration(etaSeconds) }}</span>
      </div>

      <el-alert v-if="statusMessage" type="info" :closable="false" show-icon :title="statusMessage" style="margin-top: 8px" />
    </el-card>

    <el-row v-if="status || results.length" :gutter="16" style="margin-top: 16px">
      <el-col :xs="12" :sm="6">
        <el-card class="stat-card">
          <el-statistic title="总网段" :value="summary.total_subnets" />
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card class="stat-card">
          <el-statistic title="有存活" :value="summary.alive_subnets" />
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card class="stat-card">
          <el-statistic title="无响应" :value="summary.dead_subnets" />
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card class="stat-card">
          <el-statistic title="存活 IP 总数" :value="summary.alive_hosts" />
        </el-card>
      </el-col>
    </el-row>

    <el-card v-if="results.length" style="margin-top: 16px">
      <template #header>
        <div class="card-header">
          <h3 style="margin: 0">汇总结果</h3>
          <div class="filters">
            <el-select v-model="statusFilter" style="width: 140px">
              <el-option label="全部状态" value="all" />
              <el-option label="有存活" value="alive" />
              <el-option label="无响应" value="dead" />
              <el-option label="出错" value="error" />
            </el-select>
            <el-input v-model="keyword" placeholder="搜索网段" clearable style="width: 200px" />
          </div>
        </div>
      </template>

      <el-table :data="filteredResults" stripe style="width: 100%" max-height="560">
        <el-table-column prop="subnet" label="网段" min-width="140" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag v-if="row.error" type="danger" size="small">出错</el-tag>
            <el-tag v-else-if="row.has_live" type="success" size="small">有存活</el-tag>
            <el-tag v-else type="info" size="small">无响应</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="alive_count" label="存活 IP 数" width="110" align="right" />
        <el-table-column label="存活 IP" min-width="220">
          <template #default="{ row }">
            <span v-if="!row.alive_count">—</span>
            <span v-else>
              {{ aliveText(row) }}
              <el-tag v-if="row.truncated" type="warning" size="small" style="margin-left: 6px">已截断</el-tag>
            </span>
          </template>
        </el-table-column>
        <el-table-column label="探测 IP 数" width="120" align="right">
          <template #default="{ row }">{{ row.probed_hosts }} / {{ row.total_hosts }}</template>
        </el-table-column>
        <el-table-column label="耗时(ms)" width="110" align="right">
          <template #default="{ row }">{{ Number(row.duration_ms || 0).toFixed(0) }}</template>
        </el-table-column>
        <el-table-column label="备注" min-width="140">
          <template #default="{ row }">
            <el-text v-if="row.error" type="danger">{{ row.error }}</el-text>
            <span v-else>—</span>
          </template>
        </el-table-column>
      </el-table>

      <div class="table-foot">
        共 {{ filteredResults.length }} 条（总计 {{ results.length }} 条）
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { CircleClose, Download, Search } from '@element-plus/icons-vue'
import {
  subnetProbeApi,
  type ProbeMode,
  type ProbeStatus,
  type SubnetProbeEntry,
  type SubnetProbeSummary,
  type SubnetProbeStatusResult
} from '@/api/subnetProbe'
import { exportMultiSheetExcel } from '@/utils/export'

const subnetText = ref('')
const concurrency = ref(200)
const timeout = ref(1.0)
const mode = ref<ProbeMode>('fast')
const gatewayFirst = ref(true)

const parsing = ref(false)
const parseError = ref('')
const invalidLines = ref<string[]>([])
const parsedCount = ref(0)
const totalHosts = ref(0)

const taskId = ref<string | null>(null)
const status = ref<ProbeStatus | null>(null)
const statusMessage = ref('')
const progressPercent = ref(0)
const elapsedSeconds = ref(0)
const etaSeconds = ref<number | null>(null)
const starting = ref(false)
const cancelling = ref(false)
const results = ref<SubnetProbeEntry[]>([])

const statusFilter = ref<'all' | 'alive' | 'dead' | 'error'>('all')
const keyword = ref('')

const EMPTY_SUMMARY: SubnetProbeSummary = {
  total_subnets: 0,
  checked_subnets: 0,
  alive_subnets: 0,
  dead_subnets: 0,
  alive_hosts: 0,
  pings_sent: 0
}
const summary = ref<SubnetProbeSummary>({ ...EMPTY_SUMMARY })

const isRunning = computed(() => status.value === 'running')

const statusText = computed(() => {
  switch (status.value) {
    case 'running':
      return '扫描中'
    case 'completed':
      return '已完成'
    case 'cancelled':
      return '已停止'
    case 'failed':
      return '失败'
    default:
      return '未开始'
  }
})

const statusTagType = computed(() => {
  switch (status.value) {
    case 'running':
      return 'warning'
    case 'completed':
      return 'success'
    case 'cancelled':
      return 'info'
    case 'failed':
      return 'danger'
    default:
      return 'info'
  }
})

const progressStatus = computed(() => {
  if (status.value === 'completed') return 'success'
  if (status.value === 'failed') return 'exception'
  return undefined
})

const filteredResults = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  return results.value.filter((row) => {
    if (statusFilter.value === 'alive' && !(row.has_live && !row.error)) return false
    if (statusFilter.value === 'dead' && (row.has_live || row.error)) return false
    if (statusFilter.value === 'error' && !row.error) return false
    if (kw && !row.subnet.toLowerCase().includes(kw)) return false
    return true
  })
})

let parseTimer: ReturnType<typeof setTimeout> | null = null
let pollTimer: ReturnType<typeof setInterval> | null = null

watch(subnetText, () => {
  if (parseTimer) clearTimeout(parseTimer)
  parseTimer = setTimeout(() => { void runParse() }, 400)
})

function formatDuration(seconds: number | null | undefined): string {
  const value = Math.max(0, Math.floor(Number(seconds) || 0))
  const h = Math.floor(value / 3600)
  const m = Math.floor((value % 3600) / 60)
  const s = value % 60
  if (h > 0) return `${h}小时${m}分${s}秒`
  if (m > 0) return `${m}分${s}秒`
  return `${s}秒`
}

function aliveText(row: SubnetProbeEntry): string {
  const ips = (row.alive_ips || []).map((item) => item.ip)
  const shown = ips.slice(0, 8).join('、')
  return ips.length > 8 ? `${shown} 等 ${ips.length} 个` : shown
}

async function runParse() {
  const text = subnetText.value.trim()
  if (!text) {
    parsing.value = false
    parseError.value = ''
    invalidLines.value = []
    parsedCount.value = 0
    totalHosts.value = 0
    return
  }
  parsing.value = true
  try {
    const data = await subnetProbeApi.parse(text)
    parsedCount.value = data.subnets.length
    totalHosts.value = data.total_hosts
    invalidLines.value = data.invalid || []
    parseError.value = ''
  } catch (error) {
    parsedCount.value = 0
    totalHosts.value = 0
    invalidLines.value = []
    parseError.value = (error as Error).message || '识别失败'
  } finally {
    parsing.value = false
  }
}

function stopPolling() {
  if (pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function applyStatus(snapshot: SubnetProbeStatusResult) {
  status.value = snapshot.status
  statusMessage.value = snapshot.message || ''
  progressPercent.value = Math.max(0, Math.min(100, Number(snapshot.progress_percent) || 0))
  elapsedSeconds.value = Number(snapshot.elapsed_seconds) || 0
  etaSeconds.value = snapshot.eta_seconds === undefined ? null : snapshot.eta_seconds
  summary.value = snapshot.summary || { ...EMPTY_SUMMARY }
}

async function loadResult(id: string) {
  try {
    const data = await subnetProbeApi.result(id)
    results.value = data.results || []
  } catch (error) {
    ElMessage.error((error as Error).message || '获取结果失败')
  }
}

function startPolling(id: string) {
  stopPolling()
  pollTimer = setInterval(() => { void pollOnce(id) }, 1500)
}

async function pollOnce(id: string) {
  try {
    const snapshot = await subnetProbeApi.status(id)
    applyStatus(snapshot)
    if (snapshot.status !== 'running') {
      stopPolling()
      await loadResult(id)
    }
  } catch (error) {
    // Task table lives in memory: a backend reload wipes it, so stop polling on 404
    stopPolling()
    status.value = 'failed'
    statusMessage.value = (error as Error).message || '任务已丢失'
    ElMessage.error(statusMessage.value)
  }
}

async function handleStart() {
  if (parseTimer) {
    clearTimeout(parseTimer)
    parseTimer = null
  }
  await runParse()
  if (!parsedCount.value) {
    ElMessage.error(parseError.value || '没有可扫描的网段')
    return
  }
  starting.value = true
  try {
    const started = await subnetProbeApi.start({
      subnets: subnetText.value,
      mode: mode.value,
      concurrency: concurrency.value,
      timeout: timeout.value,
      gateway_first: gatewayFirst.value
    })
    taskId.value = started.task_id
    results.value = []
    summary.value = { ...EMPTY_SUMMARY }
    applyStatus({
      task_id: started.task_id,
      status: started.status,
      mode: started.mode,
      progress_percent: 0,
      summary: {
        total_subnets: started.total_subnets,
        checked_subnets: 0,
        alive_subnets: 0,
        dead_subnets: 0,
        alive_hosts: 0,
        pings_sent: 0
      },
      elapsed_seconds: 0,
      eta_seconds: null
    })
    ElMessage.success(`已开始扫描 ${started.total_subnets} 个网段`)
    startPolling(started.task_id)
  } catch (error) {
    ElMessage.error((error as Error).message || '启动扫描失败')
  } finally {
    starting.value = false
  }
}

async function handleCancel() {
  if (!taskId.value) return
  cancelling.value = true
  try {
    const snapshot = await subnetProbeApi.cancel(taskId.value)
    applyStatus(snapshot)
    stopPolling()
    await loadResult(taskId.value)
    ElMessage.info('已停止扫描')
  } catch (error) {
    ElMessage.error((error as Error).message || '停止失败')
  } finally {
    cancelling.value = false
  }
}

async function handleExport() {
  if (!results.value.length) return
  const rows = filteredResults.value
  const summarySheet = rows.map((row) => ({
    网段: row.subnet,
    状态: row.error ? '出错' : row.has_live ? '有存活' : '无响应',
    '存活 IP 数': row.alive_count,
    存活IP: (row.alive_ips || []).map((item) => item.ip).join(' '),
    '探测 IP 数': row.probed_hosts,
    '网段 IP 总数': row.total_hosts,
    '是否截断': row.truncated ? '是' : '否',
    '耗时(ms)': Number(row.duration_ms || 0).toFixed(0),
    备注: row.error || ''
  }))

  const detailSheet: Record<string, any>[] = []
  for (const row of rows) {
    for (const item of row.alive_ips || []) {
      detailSheet.push({
        网段: row.subnet,
        '存活 IP': item.ip,
        '响应时间(ms)': item.response_time_ms === null || item.response_time_ms === undefined
          ? ''
          : Number(item.response_time_ms).toFixed(1)
      })
    }
  }

  const isFiltered = rows.length !== results.value.length
  const name = `子网存活探测_${statusText.value}${isFiltered ? '_已筛选' : ''}`
  try {
    await exportMultiSheetExcel(
      [
        { name: '网段汇总', data: summarySheet },
        { name: '存活 IP 明细', data: detailSheet }
      ],
      name
    )
  } catch (error) {
    ElMessage.error((error as Error).message || '导出失败')
  }
}

onMounted(async () => {
  try {
    const running = await subnetProbeApi.running()
    if (!running?.task_id) return
    taskId.value = running.task_id
    const snapshot = await subnetProbeApi.status(running.task_id)
    applyStatus(snapshot)
    startPolling(running.task_id)
    ElMessage.info('已接管正在运行的扫描任务')
  } catch {
    // 接管失败不影响手动新开任务
  }
})

onBeforeUnmount(() => {
  if (parseTimer) clearTimeout(parseTimer)
  stopPolling()
})
</script>

<style scoped>
.subnet-probe {
  max-width: 1500px;
  margin: 0 auto;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.sub-title {
  color: #909399;
  font-size: 13px;
  margin-top: 4px;
}

.parse-line {
  margin-top: 8px;
  min-height: 22px;
}

.invalid-list {
  word-break: break-all;
  font-size: 12px;
}

.actions {
  margin-top: 16px;
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.progress-line {
  margin-top: 12px;
  display: flex;
  gap: 24px;
  flex-wrap: wrap;
  color: #606266;
  font-size: 13px;
}

.stat-card {
  text-align: center;
}

.filters {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.table-foot {
  margin-top: 10px;
  color: #909399;
  font-size: 12px;
}
</style>
