<template>
  <div class="alarms-view">
    <el-card>
      <template #header>
        <div class="card-header">
          <h2>告警管理 / Alarms</h2>
          <div class="header-actions">
            <el-button @click="loadAlarms" :loading="loading">
              <el-icon><Refresh /></el-icon>
              刷新
            </el-button>
          </div>
        </div>
      </template>

      <!-- Filters -->
      <div class="filters-bar">
        <el-select
          v-model="filters.severity"
          placeholder="严重级别"
          clearable
          @change="handleFilterChange"
          style="width: 150px; margin-right: 10px;"
        >
          <el-option label="严重 (Critical)" value="critical" />
          <el-option label="错误 (Error)" value="error" />
          <el-option label="警告 (Warning)" value="warning" />
          <el-option label="信息 (Info)" value="info" />
        </el-select>

        <el-select
          v-model="filters.status"
          placeholder="状态"
          clearable
          @change="handleFilterChange"
          style="width: 150px; margin-right: 10px;"
        >
          <el-option label="活跃 (Active)" value="active" />
          <el-option label="已确认 (Acknowledged)" value="acknowledged" />
          <el-option label="已解决 (Resolved)" value="resolved" />
          <el-option label="自动解决 (Auto-Resolved)" value="auto_resolved" />
        </el-select>

        <el-select
          v-model="filters.source_type"
          placeholder="来源类型"
          clearable
          @change="handleFilterChange"
          style="width: 150px;"
        >
          <el-option label="交换机 (Switch)" value="switch" />
          <el-option label="批次 (Batch)" value="batch" />
          <el-option label="采集 (Collection)" value="collection" />
          <el-option label="系统 (System)" value="system" />
        </el-select>
      </div>

      <!-- Alarms Table -->
      <el-table
        :data="alarms"
        v-loading="loading"
        stripe
        style="width: 100%; margin-top: 16px;"
      >
        <!-- Severity -->
        <el-table-column prop="severity" label="严重级别" width="110">
          <template #default="{ row }">
            <el-tag :type="getSeverityTagType(row.severity)" size="small" effect="dark">
              {{ getSeverityLabel(row.severity) }}
            </el-tag>
          </template>
        </el-table-column>

        <!-- Title -->
        <el-table-column prop="title" label="标题" min-width="250">
          <template #default="{ row }">
            <div style="cursor: pointer;" @click="showAlarmDetails(row)">
              <strong>{{ row.title }}</strong>
              <el-icon style="margin-left: 4px;"><InfoFilled /></el-icon>
            </div>
          </template>
        </el-table-column>

        <!-- Source -->
        <el-table-column label="来源" width="200">
          <template #default="{ row }">
            <div>
              <el-tag type="info" size="small">{{ getSourceTypeLabel(row.source_type) }}</el-tag>
              <div v-if="row.source_name" style="font-size: 12px; color: #909399; margin-top: 2px;">
                {{ row.source_name }}
              </div>
            </div>
          </template>
        </el-table-column>

        <!-- Occurrence Count -->
        <el-table-column prop="occurrence_count" label="次数" width="80" align="center">
          <template #default="{ row }">
            <el-badge :value="row.occurrence_count" :max="99" type="danger" v-if="row.occurrence_count > 1" />
            <span v-else>{{ row.occurrence_count }}</span>
          </template>
        </el-table-column>

        <!-- Status -->
        <el-table-column prop="status" label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="getStatusTagType(row.status)" size="small">
              {{ getStatusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>

        <!-- Created At -->
        <el-table-column prop="created_at" label="创建时间" width="180">
          <template #default="{ row }">
            <div style="font-size: 12px;">
              {{ formatDateTime(row.created_at) }}
            </div>
            <div v-if="row.occurrence_count > 1" style="font-size: 11px; color: #909399;">
              最近: {{ formatRelativeTime(row.last_occurrence_at) }}
            </div>
          </template>
        </el-table-column>

        <!-- Actions -->
        <el-table-column label="操作" width="240" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.status === 'active'"
              size="small"
              @click="acknowledgeAlarm(row.id)"
              :loading="actionLoading === row.id"
            >
              确认
            </el-button>
            <el-button
              v-if="row.status === 'active' || row.status === 'acknowledged'"
              size="small"
              type="success"
              @click="resolveAlarm(row.id)"
              :loading="actionLoading === row.id"
            >
              解决
            </el-button>
            <el-button
              size="small"
              type="info"
              @click="showAlarmDetails(row)"
            >
              详情
            </el-button>
            <el-button
              size="small"
              type="danger"
              @click="deleteAlarm(row.id)"
              :loading="actionLoading === row.id"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- Pagination -->
      <div class="pagination-container">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :page-sizes="[20, 50, 100, 200]"
          :total="totalAlarms"
          layout="total, sizes, prev, pager, next, jumper"
          @size-change="handlePageSizeChange"
          @current-change="handlePageChange"
        />
      </div>

      <el-empty v-if="!loading && alarms.length === 0" description="暂无告警" />
    </el-card>

    <!-- Alarm Details Dialog -->
    <el-dialog
      v-model="showDetailsDialog"
      title="告警详情"
      width="600px"
    >
      <div v-if="selectedAlarm">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="严重级别">
            <el-tag :type="getSeverityTagType(selectedAlarm.severity)">
              {{ getSeverityLabel(selectedAlarm.severity) }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="getStatusTagType(selectedAlarm.status)">
              {{ getStatusLabel(selectedAlarm.status) }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="标题">{{ selectedAlarm.title }}</el-descriptions-item>
          <el-descriptions-item label="消息">{{ selectedAlarm.message }}</el-descriptions-item>
          <el-descriptions-item label="来源类型">
            {{ getSourceTypeLabel(selectedAlarm.source_type) }}
          </el-descriptions-item>
          <el-descriptions-item label="来源名称" v-if="selectedAlarm.source_name">
            {{ selectedAlarm.source_name }}
          </el-descriptions-item>
          <el-descriptions-item label="发生次数">{{ selectedAlarm.occurrence_count }}</el-descriptions-item>
          <el-descriptions-item label="创建时间">
            {{ formatDateTime(selectedAlarm.created_at) }}
          </el-descriptions-item>
          <el-descriptions-item label="最近发生" v-if="selectedAlarm.last_occurrence_at">
            {{ formatDateTime(selectedAlarm.last_occurrence_at) }}
          </el-descriptions-item>
          <el-descriptions-item label="确认时间" v-if="selectedAlarm.acknowledged_at">
            {{ formatDateTime(selectedAlarm.acknowledged_at) }}
            <span v-if="selectedAlarm.acknowledged_by"> (by {{ selectedAlarm.acknowledged_by }})</span>
          </el-descriptions-item>
          <el-descriptions-item label="解决时间" v-if="selectedAlarm.resolved_at">
            {{ formatDateTime(selectedAlarm.resolved_at) }}
            <span v-if="selectedAlarm.resolved_by"> (by {{ selectedAlarm.resolved_by }})</span>
          </el-descriptions-item>
        </el-descriptions>

        <div v-if="selectedAlarm.details" style="margin-top: 16px;">
          <h4>详细信息</h4>
          <pre style="background: #f5f5f5; padding: 12px; border-radius: 4px; font-size: 12px; max-height: 300px; overflow-y: auto;">{{ JSON.stringify(selectedAlarm.details, null, 2) }}</pre>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, InfoFilled } from '@element-plus/icons-vue'
import { alarmsApi, type Alarm } from '@/api/alarms'

const alarms = ref<Alarm[]>([])
const loading = ref(false)
const actionLoading = ref<number | null>(null)
const currentPage = ref(1)
const pageSize = ref(100)
const totalAlarms = ref(0)
const showDetailsDialog = ref(false)
const selectedAlarm = ref<Alarm | null>(null)

const filters = ref({
  severity: '',
  status: '',
  source_type: ''
})

let refreshInterval: number | null = null

const loadAlarms = async () => {
  loading.value = true
  try {
    const params = {
      skip: (currentPage.value - 1) * pageSize.value,
      limit: pageSize.value,
      severity: filters.value.severity || undefined,
      status: filters.value.status || undefined,
      source_type: filters.value.source_type || undefined
    }
    const result = await alarmsApi.list(params)
    alarms.value = result.items
    totalAlarms.value = result.total
  } catch (error) {
    ElMessage.error('加载告警失败')
  } finally {
    loading.value = false
  }
}

const acknowledgeAlarm = async (id: number) => {
  actionLoading.value = id
  try {
    await alarmsApi.acknowledge(id)
    ElMessage.success('告警已确认')
    await loadAlarms()
  } catch (error) {
    ElMessage.error('确认告警失败')
  } finally {
    actionLoading.value = null
  }
}

const resolveAlarm = async (id: number) => {
  actionLoading.value = id
  try {
    await alarmsApi.resolve(id)
    ElMessage.success('告警已解决')
    await loadAlarms()
  } catch (error) {
    ElMessage.error('解决告警失败')
  } finally {
    actionLoading.value = null
  }
}

const deleteAlarm = async (id: number) => {
  try {
    await ElMessageBox.confirm(
      '确定要删除此告警吗？此操作不可恢复！',
      '确认删除',
      {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )

    actionLoading.value = id
    await alarmsApi.delete(id)
    ElMessage.success('告警已删除')
    await loadAlarms()
  } catch (error: any) {
    if (error !== 'cancel') {
      ElMessage.error('删除告警失败')
    }
  } finally {
    actionLoading.value = null
  }
}

const showAlarmDetails = (alarm: Alarm) => {
  selectedAlarm.value = alarm
  showDetailsDialog.value = true
}

const handleFilterChange = () => {
  currentPage.value = 1
  loadAlarms()
}

const handlePageChange = (page: number) => {
  currentPage.value = page
  loadAlarms()
}

const handlePageSizeChange = (size: number) => {
  pageSize.value = size
  currentPage.value = 1
  loadAlarms()
}

const getSeverityTagType = (severity: string) => {
  const types: Record<string, any> = {
    critical: 'danger',
    error: 'warning',
    warning: 'warning',
    info: 'info'
  }
  return types[severity] || 'info'
}

const getSeverityLabel = (severity: string) => {
  const labels: Record<string, string> = {
    critical: '严重',
    error: '错误',
    warning: '警告',
    info: '信息'
  }
  return labels[severity] || severity
}

const getStatusTagType = (status: string) => {
  const types: Record<string, any> = {
    active: 'danger',
    acknowledged: 'warning',
    resolved: 'success',
    auto_resolved: 'info'
  }
  return types[status] || 'info'
}

const getStatusLabel = (status: string) => {
  const labels: Record<string, string> = {
    active: '活跃',
    acknowledged: '已确认',
    resolved: '已解决',
    auto_resolved: '自动解决'
  }
  return labels[status] || status
}

const getSourceTypeLabel = (sourceType: string) => {
  const labels: Record<string, string> = {
    switch: '交换机',
    batch: '批次',
    collection: '采集',
    system: '系统'
  }
  return labels[sourceType] || sourceType
}

const formatDateTime = (dateStr: string) => {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
}

const formatRelativeTime = (dateStr: string) => {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)

  if (diffMins < 1) return '刚刚'
  if (diffMins < 60) return `${diffMins}分钟前`
  if (diffMins < 1440) return `${Math.floor(diffMins / 60)}小时前`
  return `${Math.floor(diffMins / 1440)}天前`
}

onMounted(() => {
  loadAlarms()

  // Auto-refresh every 30 seconds
  refreshInterval = window.setInterval(() => {
    loadAlarms()
  }, 30000)
})

onUnmounted(() => {
  if (refreshInterval) {
    clearInterval(refreshInterval)
  }
})
</script>

<style scoped>
.alarms-view {
  max-width: 1600px;
  margin: 0 auto;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-actions {
  display: flex;
  gap: 10px;
}

.card-header h2 {
  margin: 0;
  color: #303133;
}

.filters-bar {
  display: flex;
  gap: 10px;
  margin-bottom: 16px;
  align-items: center;
}

.pagination-container {
  display: flex;
  justify-content: center;
  margin-top: 20px;
  padding: 10px 0;
}
</style>
