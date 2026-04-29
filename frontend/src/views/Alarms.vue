<template>
  <div class="alarms-view">
    <el-card>
      <template #header>
        <div class="card-header">
          <h2>告警管理 / Alarms</h2>
          <div class="header-actions">
            <el-button type="info" plain @click="loadAlarms" :loading="loading">
              <el-icon><Refresh /></el-icon>
              刷新
            </el-button>
          </div>
        </div>
      </template>

      <div class="summary-grid">
        <el-card shadow="never" class="summary-card">
          <div class="summary-label">活跃告警</div>
          <div class="summary-value danger">{{ alarmStats?.total_active ?? 0 }}</div>
        </el-card>
        <el-card shadow="never" class="summary-card">
          <div class="summary-label">已确认</div>
          <div class="summary-value warning">{{ alarmStats?.total_acknowledged ?? 0 }}</div>
        </el-card>
        <el-card shadow="never" class="summary-card">
          <div class="summary-label">已解决</div>
          <div class="summary-value success">{{ alarmStats?.total_resolved ?? 0 }}</div>
        </el-card>
        <el-card shadow="never" class="summary-card">
          <div class="summary-label">当前页 Stale 交换机告警</div>
          <div class="summary-value info">{{ staleSwitchAlarmCount }}</div>
        </el-card>
      </div>

      <div class="quick-focus-bar">
        <div class="quick-focus-left">
          <span class="quick-focus-title">当前页快速聚焦</span>
          <el-button
            size="small"
            :type="quickFocus.onlySwitch ? 'primary' : 'default'"
            @click="quickFocus.onlySwitch = !quickFocus.onlySwitch"
          >
            仅交换机
          </el-button>
          <el-button
            size="small"
            :type="quickFocus.onlyStale ? 'warning' : 'default'"
            @click="quickFocus.onlyStale = !quickFocus.onlyStale"
          >
            仅 Stale
          </el-button>
          <el-button
            size="small"
            :type="quickFocus.onlyOffline ? 'danger' : 'default'"
            @click="quickFocus.onlyOffline = !quickFocus.onlyOffline"
          >
            仅离线
          </el-button>
        </div>
        <el-input
          v-model="quickFocus.keyword"
          clearable
          size="small"
          placeholder="按标题/来源/消息搜索当前页"
          style="width: 280px;"
        />
      </div>

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
        :data="displayedAlarms"
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
              <el-button
                v-if="row.source_type === 'switch' && row.source_id"
                type="primary"
                link
                size="small"
                style="padding: 0; margin-top: 2px;"
                @click="openSwitchDetail(row.source_id)"
              >
                打开交换机
              </el-button>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="当前设备状态" width="180">
          <template #default="{ row }">
            <div v-if="row.source_type === 'switch' && row.source_id" class="switch-state-stack">
              <el-tag
                v-if="row.current_freshness_status"
                :type="row.current_freshness_status === 'stale' ? 'warning' : 'success'"
                size="small"
              >
                {{ row.current_freshness_status === 'stale' ? 'Stale' : 'Fresh' }}
              </el-tag>
              <el-tag
                v-if="row.current_switch_is_reachable !== undefined && row.current_switch_is_reachable !== null"
                :type="row.current_switch_is_reachable ? 'success' : 'danger'"
                size="small"
              >
                {{ row.current_switch_is_reachable ? '在线' : '离线' }}
              </el-tag>
              <div
                v-if="row.current_switch_collection_status"
                class="switch-state-meta"
                :title="row.current_switch_collection_message || row.current_freshness_warning || ''"
              >
                {{ row.current_switch_collection_status }}
              </div>
            </div>
            <span v-else style="color: #909399;">-</span>
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

      <el-empty
        v-if="!loading && displayedAlarms.length === 0"
        :description="alarms.length === 0 ? '暂无告警' : '当前页没有符合快速聚焦条件的告警'"
      />
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
          <el-descriptions-item label="当前交换机状态" v-if="selectedAlarm.source_type === 'switch' && selectedAlarm.source_id">
            <el-space wrap>
              <el-tag
                v-if="selectedAlarm.current_freshness_status"
                :type="selectedAlarm.current_freshness_status === 'stale' ? 'warning' : 'success'"
              >
                {{ selectedAlarm.current_freshness_status === 'stale' ? 'Stale' : 'Fresh' }}
              </el-tag>
              <el-tag
                v-if="selectedAlarm.current_switch_is_reachable !== undefined && selectedAlarm.current_switch_is_reachable !== null"
                :type="selectedAlarm.current_switch_is_reachable ? 'success' : 'danger'"
              >
                {{ selectedAlarm.current_switch_is_reachable ? '在线' : '离线' }}
              </el-tag>
              <el-tag v-if="selectedAlarm.current_switch_collection_status" type="info">
                {{ selectedAlarm.current_switch_collection_status }}
              </el-tag>
            </el-space>
            <div v-if="selectedAlarm.current_switch_collection_message" style="margin-top: 8px;">
              {{ selectedAlarm.current_switch_collection_message }}
            </div>
            <div v-else-if="selectedAlarm.current_freshness_warning" style="margin-top: 8px;">
              {{ selectedAlarm.current_freshness_warning }}
            </div>
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

        <div v-if="selectedAlarm.source_type === 'switch' && selectedAlarm.source_id" style="margin-top: 16px;">
          <el-button type="primary" @click="openSwitchDetail(selectedAlarm.source_id)">
            打开交换机详情
          </el-button>
        </div>
      </div>
    </el-dialog>

    <el-card class="group-panel-card">
      <template #header>
        <div class="card-header">
          <h2>交换机聚合视图 / Fault Panel</h2>
          <div class="header-actions">
            <el-button type="info" plain @click="loadSwitchGroups" :loading="switchGroupsLoading">
              <el-icon><Refresh /></el-icon>
              刷新聚合
            </el-button>
          </div>
        </div>
      </template>

      <el-table
        :data="displayedSwitchGroups"
        v-loading="switchGroupsLoading"
        stripe
        style="width: 100%;"
      >
        <el-table-column label="交换机" min-width="220">
          <template #default="{ row }">
            <div class="group-switch-cell">
              <el-button type="primary" link @click="openSwitchDetail(row.switch_id)">
                {{ row.switch_name }}
              </el-button>
              <div class="group-switch-meta">{{ row.switch_ip || '-' }}</div>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="当前状态" width="180">
          <template #default="{ row }">
            <div class="switch-state-stack">
              <el-tag
                v-if="row.current_freshness_status"
                :type="row.current_freshness_status === 'stale' ? 'warning' : 'success'"
                size="small"
              >
                {{ row.current_freshness_status === 'stale' ? 'Stale' : 'Fresh' }}
              </el-tag>
              <el-tag
                v-if="row.current_switch_is_reachable !== undefined && row.current_switch_is_reachable !== null"
                :type="row.current_switch_is_reachable ? 'success' : 'danger'"
                size="small"
              >
                {{ row.current_switch_is_reachable ? '在线' : '离线' }}
              </el-tag>
              <div
                v-if="row.current_switch_collection_status"
                class="switch-state-meta"
                :title="row.current_switch_collection_message || row.current_freshness_warning || ''"
              >
                {{ row.current_switch_collection_status }}
              </div>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="Open" width="80" align="center">
          <template #default="{ row }">
            <el-tag type="danger">{{ row.open_count }}</el-tag>
          </template>
        </el-table-column>

        <el-table-column label="ACK" width="80" align="center">
          <template #default="{ row }">
            <el-tag type="warning">{{ row.acknowledged_count }}</el-tag>
          </template>
        </el-table-column>

        <el-table-column label="Resolved" width="90" align="center">
          <template #default="{ row }">
            <el-tag type="success">{{ row.resolved_count }}</el-tag>
          </template>
        </el-table-column>

        <el-table-column label="累计出现次数" width="110" align="center">
          <template #default="{ row }">
            {{ row.total_occurrences }}
          </template>
        </el-table-column>

        <el-table-column label="最新事件" width="180">
          <template #default="{ row }">
            {{ formatDateTime(row.latest_event_at) }}
          </template>
        </el-table-column>

        <el-table-column label="最新告警" min-width="280">
          <template #default="{ row }">
            <div class="group-latest-title">{{ row.latest_alarm_title || '-' }}</div>
            <div class="group-latest-message">{{ row.latest_alarm_message || '-' }}</div>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" @click="openSwitchTimeline(row)">
              时间线
            </el-button>
            <el-button size="small" type="info" @click="openSwitchDetail(row.switch_id)">
              详情
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty
        v-if="!switchGroupsLoading && displayedSwitchGroups.length === 0"
        description="暂无交换机聚合告警"
      />
    </el-card>

    <el-drawer
      v-model="showTimelineDrawer"
      :title="selectedTimeline?.switch_name ? `${selectedTimeline.switch_name} 故障时间线` : '故障时间线'"
      size="45%"
    >
      <div v-if="selectedTimeline" class="timeline-panel">
        <div class="timeline-summary">
          <el-space wrap>
            <el-tag type="danger">Open {{ selectedTimeline.open_count }}</el-tag>
            <el-tag type="warning">ACK {{ selectedTimeline.acknowledged_count }}</el-tag>
            <el-tag type="success">Resolved {{ selectedTimeline.resolved_count }}</el-tag>
            <el-tag
              v-if="selectedTimeline.current_freshness_status"
              :type="selectedTimeline.current_freshness_status === 'stale' ? 'warning' : 'success'"
            >
              {{ selectedTimeline.current_freshness_status === 'stale' ? 'Stale' : 'Fresh' }}
            </el-tag>
            <el-tag
              v-if="selectedTimeline.current_switch_is_reachable !== undefined && selectedTimeline.current_switch_is_reachable !== null"
              :type="selectedTimeline.current_switch_is_reachable ? 'success' : 'danger'"
            >
              {{ selectedTimeline.current_switch_is_reachable ? '在线' : '离线' }}
            </el-tag>
          </el-space>
          <div v-if="selectedTimeline.current_switch_collection_message" class="timeline-summary-text">
            {{ selectedTimeline.current_switch_collection_message }}
          </div>
          <div v-else-if="selectedTimeline.current_freshness_warning" class="timeline-summary-text">
            {{ selectedTimeline.current_freshness_warning }}
          </div>
        </div>

        <div class="timeline-actions">
          <el-button type="primary" @click="openSwitchDetail(selectedTimeline.switch_id)">
            打开交换机详情
          </el-button>
        </div>

        <el-empty
          v-if="selectedTimeline.events.length === 0"
          description="该交换机当前没有可展示的告警时间线事件"
        />

        <el-timeline v-else>
          <el-timeline-item
            v-for="event in selectedTimeline.events"
            :key="`${event.event_type}-${event.alarm_id}-${event.timestamp}`"
            :timestamp="formatDateTime(event.timestamp)"
            :type="getTimelineItemType(event)"
          >
            <div class="timeline-event-card">
              <div class="timeline-event-header">
                <el-space wrap>
                  <el-tag size="small" :type="getSeverityTagType(event.severity)">{{ getSeverityLabel(event.severity) }}</el-tag>
                  <el-tag size="small" :type="getTimelineEventTagType(event.event_type)">{{ getTimelineEventLabel(event.event_type) }}</el-tag>
                  <el-tag size="small" type="info">Alarm #{{ event.alarm_id }}</el-tag>
                </el-space>
              </div>
              <div class="timeline-event-title">{{ event.title }}</div>
              <div class="timeline-event-message">{{ event.message }}</div>
              <div v-if="event.note" class="timeline-event-note">{{ event.note }}</div>
              <div v-if="event.actor" class="timeline-event-meta">操作人: {{ event.actor }}</div>
              <div class="timeline-event-meta">累计次数: {{ event.occurrence_count }}</div>
            </div>
          </el-timeline-item>
        </el-timeline>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, InfoFilled } from '@element-plus/icons-vue'
import {
  alarmsApi,
  type Alarm,
  type AlarmStats,
  type SwitchAlarmGroup,
  type SwitchAlarmTimeline,
  type SwitchAlarmTimelineEvent,
} from '@/api/alarms'

const router = useRouter()
const alarms = ref<Alarm[]>([])
const alarmStats = ref<AlarmStats | null>(null)
const switchGroups = ref<SwitchAlarmGroup[]>([])
const switchGroupsLoading = ref(false)
const loading = ref(false)
const actionLoading = ref<number | null>(null)
const currentPage = ref(1)
const pageSize = ref(100)
const totalAlarms = ref(0)
const showDetailsDialog = ref(false)
const selectedAlarm = ref<Alarm | null>(null)
const showTimelineDrawer = ref(false)
const selectedTimeline = ref<SwitchAlarmTimeline | null>(null)

const filters = ref({
  severity: '',
  status: '',
  source_type: ''
})
const quickFocus = ref({
  onlySwitch: false,
  onlyStale: false,
  onlyOffline: false,
  keyword: ''
})

let refreshInterval: number | null = null

const staleSwitchAlarmCount = computed(() =>
  alarms.value.filter(alarm =>
    alarm.source_type === 'switch' &&
    alarm.current_freshness_status === 'stale'
  ).length
)

const displayedSwitchGroups = computed(() => {
  const keyword = quickFocus.value.keyword.trim().toLowerCase()

  return switchGroups.value.filter((group) => {
    if (quickFocus.value.onlySwitch === false && quickFocus.value.onlyStale === false && quickFocus.value.onlyOffline === false && !keyword) {
      return true
    }

    if (quickFocus.value.onlyStale && group.current_freshness_status !== 'stale') {
      return false
    }

    if (quickFocus.value.onlyOffline && group.current_switch_is_reachable !== false) {
      return false
    }

    if (!keyword) {
      return true
    }

    const haystack = [
      group.switch_name,
      group.switch_ip,
      group.latest_alarm_title,
      group.latest_alarm_message,
      group.current_switch_collection_message
    ]
      .filter(Boolean)
      .join(' ')
      .toLowerCase()

    return haystack.includes(keyword)
  })
})

const displayedAlarms = computed(() => {
  const keyword = quickFocus.value.keyword.trim().toLowerCase()

  return alarms.value.filter((alarm) => {
    if (quickFocus.value.onlySwitch && alarm.source_type !== 'switch') {
      return false
    }

    if (quickFocus.value.onlyStale && alarm.current_freshness_status !== 'stale') {
      return false
    }

    if (quickFocus.value.onlyOffline && alarm.current_switch_is_reachable !== false) {
      return false
    }

    if (!keyword) {
      return true
    }

    const haystack = [
      alarm.title,
      alarm.message,
      alarm.source_name,
      alarm.current_switch_collection_message
    ]
      .filter(Boolean)
      .join(' ')
      .toLowerCase()

    return haystack.includes(keyword)
  })
})

const loadAlarmStats = async () => {
  try {
    alarmStats.value = await alarmsApi.getStats()
  } catch (error) {
    console.error('Failed to load alarm stats:', error)
  }
}

const loadSwitchGroups = async () => {
  switchGroupsLoading.value = true
  try {
    const response = await alarmsApi.getSwitchGroups(200)
    switchGroups.value = response.items
  } catch (error) {
    ElMessage.error('加载交换机聚合告警失败')
  } finally {
    switchGroupsLoading.value = false
  }
}

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
    await loadAlarmStats()
    await loadSwitchGroups()
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

const openSwitchDetail = (switchId: number) => {
  router.push(`/switches/${switchId}`)
}

const openSwitchTimeline = async (group: SwitchAlarmGroup) => {
  try {
    selectedTimeline.value = await alarmsApi.getSwitchTimeline(group.switch_id, 300)
    showTimelineDrawer.value = true
  } catch (error) {
    ElMessage.error('加载交换机时间线失败')
  }
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

const formatDateTime = (dateStr?: string | null) => {
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

const formatRelativeTime = (dateStr?: string | null) => {
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

const getTimelineEventLabel = (eventType: string) => {
  const labels: Record<string, string> = {
    created: '创建',
    reoccurred: '重复发生',
    acknowledged: '确认',
    resolved: '解决',
    auto_resolved: '自动恢复'
  }
  return labels[eventType] || eventType
}

const getTimelineEventTagType = (eventType: string) => {
  const types: Record<string, string> = {
    created: 'danger',
    reoccurred: 'warning',
    acknowledged: 'info',
    resolved: 'success',
    auto_resolved: 'success'
  }
  return types[eventType] || 'info'
}

const getTimelineItemType = (event: SwitchAlarmTimelineEvent) => {
  if (event.event_type === 'resolved' || event.event_type === 'auto_resolved') {
    return 'success'
  }
  if (event.event_type === 'acknowledged') {
    return 'primary'
  }
  if (event.severity === 'critical' || event.severity === 'error') {
    return 'danger'
  }
  if (event.severity === 'warning') {
    return 'warning'
  }
  return 'info'
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

.summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.summary-card {
  border-radius: 10px;
}

.summary-label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 8px;
}

.summary-value {
  font-size: 28px;
  font-weight: 700;
  line-height: 1;
}

.summary-value.danger {
  color: #f56c6c;
}

.summary-value.warning {
  color: #e6a23c;
}

.summary-value.success {
  color: #67c23a;
}

.summary-value.info {
  color: #409eff;
}

.card-header h2 {
  margin: 0;
  color: #303133;
}

.quick-focus-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.quick-focus-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.quick-focus-title {
  font-size: 12px;
  color: #909399;
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

.switch-state-stack {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.switch-state-meta {
  font-size: 11px;
  color: #909399;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.group-panel-card {
  margin-top: 20px;
}

.group-switch-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.group-switch-meta {
  font-size: 11px;
  color: #909399;
}

.group-latest-title {
  font-weight: 600;
  color: #303133;
}

.group-latest-message {
  margin-top: 4px;
  font-size: 12px;
  color: #606266;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.timeline-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.timeline-summary {
  background: #f8fafc;
  border: 1px solid #e5eaf3;
  border-radius: 10px;
  padding: 16px;
}

.timeline-summary-text {
  margin-top: 10px;
  font-size: 13px;
  color: #606266;
}

.timeline-actions {
  display: flex;
  justify-content: flex-end;
}

.timeline-event-card {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 10px;
  padding: 12px 14px;
}

.timeline-event-header {
  margin-bottom: 8px;
}

.timeline-event-title {
  font-weight: 700;
  color: #303133;
}

.timeline-event-message {
  margin-top: 6px;
  font-size: 13px;
  color: #606266;
  line-height: 1.5;
}

.timeline-event-note {
  margin-top: 8px;
  font-size: 12px;
  color: #e6a23c;
}

.timeline-event-meta {
  margin-top: 6px;
  font-size: 12px;
  color: #909399;
}
</style>
