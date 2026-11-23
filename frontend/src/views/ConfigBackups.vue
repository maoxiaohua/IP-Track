<template>
  <div class="config-backups-page">
    <!-- 全局设置 -->
    <el-card>
      <template #header>
        <div class="card-header">
          <div>
            <h2 style="margin: 0">配置备份</h2>
            <div class="sub-title">
              只读抓取交换机 running-config；内容未变化时不新增版本。备份失败会保留记录和原因。
            </div>
          </div>
          <div class="header-actions">
            <el-tag v-if="!authStore.isLoggedIn" type="info" effect="plain">只读访客</el-tag>
            <el-button :loading="loading" @click="loadAll">
              <template #icon><el-icon><Refresh /></el-icon></template>
              刷新
            </el-button>
          </div>
        </div>
      </template>

      <el-form :inline="true" class="settings-form" @submit.prevent>
        <el-form-item label="全局默认间隔（分钟）">
          <el-input-number
            v-model="globalForm.interval_minutes"
            :min="5"
            :max="43200"
            :step="30"
            :disabled="!authStore.isLoggedIn"
          />
        </el-form-item>
        <el-form-item label="每台保留版本数">
          <el-input-number
            v-model="globalForm.retention_versions"
            :min="1"
            :max="200"
            :disabled="!authStore.isLoggedIn"
          />
        </el-form-item>
        <el-form-item>
          <el-tooltip
            :content="authStore.isLoggedIn ? '保存后立即对新备份生效，已有记录不会被回填' : '访客只读，请登录后修改'"
            placement="top"
          >
            <span>
              <el-button
                type="primary"
                :loading="savingSettings"
                :disabled="!authStore.isLoggedIn"
                @click="saveGlobalSettings"
              >
                保存全局设置
              </el-button>
            </span>
          </el-tooltip>
        </el-form-item>
      </el-form>

      <div v-if="presetEntries.length" class="preset-hint">
        内置厂商预设：
        <el-tag
          v-for="preset in presetEntries"
          :key="preset.vendor"
          size="small"
          effect="plain"
          class="preset-tag"
        >
          {{ preset.vendor }} → {{ preset.device_type }} · {{ preset.command }}
        </el-tag>
      </div>
    </el-card>

    <!-- 交换机备份状态 -->
    <el-card class="table-card">
      <template #header>
        <div class="card-header">
          <div class="card-title">
            交换机备份状态
            <el-tag size="small" effect="plain">{{ filteredItems.length }} / {{ overview.length }}</el-tag>
          </div>
          <div class="header-actions">
            <el-tooltip
              :content="selectedRows.length ? `把 ${selectedRows.length} 台交换机的最近成功备份打包成 ZIP` : '请先在下方勾选交换机'"
              placement="top"
            >
              <span>
                <el-button
                  type="primary"
                  plain
                  :loading="batchDownloading"
                  :disabled="!selectedRows.length"
                  @click="handleBatchDownload"
                >
                  <template #icon><el-icon><FolderOpened /></el-icon></template>
                  批量下载{{ selectedRows.length ? `（${selectedRows.length}）` : '' }}
                </el-button>
              </span>
            </el-tooltip>
            <el-select v-model="statusFilter" style="width: 150px" @change="loadOverview">
              <el-option label="全部状态" value="" />
              <el-option label="成功" value="success" />
              <el-option label="失败" value="failed" />
              <el-option label="备份中" value="running" />
              <el-option label="未备份" value="never" />
            </el-select>
            <el-input
              v-model="keyword"
              placeholder="搜索名称 / IP / 厂商"
              clearable
              style="width: 220px"
            />
          </div>
        </div>
      </template>

      <el-table
        ref="overviewTable"
        v-loading="loading"
        :data="filteredItems"
        row-key="switch_id"
        stripe
        empty-text="没有匹配的交换机"
        @selection-change="handleSelectionChange"
      >
        <el-table-column type="selection" width="46" />
        <el-table-column label="交换机" min-width="180">
          <template #default="{ row }">
            <div class="switch-cell">
              <el-link type="primary" :underline="false" @click="openHistory(row)">{{ row.name }}</el-link>
              <span class="cell-sub">{{ row.ip_address || '—' }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="厂商 / 型号" min-width="140">
          <template #default="{ row }">
            <div class="switch-cell">
              <span>{{ row.vendor || '—' }}</span>
              <span class="cell-sub">{{ row.model || '—' }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="备份状态" min-width="150">
          <template #default="{ row }">
            <div class="switch-cell">
              <el-tooltip :content="row.message || statusLabel(row.status)" placement="top">
                <el-tag :type="statusTagType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
              </el-tooltip>
              <el-tag v-if="row.backup_unreachable" type="warning" size="small">网络不可达 · 计划已暂停</el-tag>
              <span v-if="row.message" class="cell-sub" :title="row.message">{{ row.message }}</span>
              <span v-else-if="!row.supported" class="cell-sub" :title="row.unsupported_reason || ''">
                {{ row.unsupported_reason || '缺少可用驱动或命令' }}
              </span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="上次备份" min-width="160">
          <template #default="{ row }">
            <div class="switch-cell">
              <span>{{ formatTime(row.last_backup_at) }}</span>
              <span v-if="row.last_duration_ms != null" class="cell-sub">耗时 {{ formatDuration(row.last_duration_ms) }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="上次成功" min-width="160">
          <template #default="{ row }">{{ formatTime(row.last_success_at) }}</template>
        </el-table-column>
        <el-table-column label="版本数" width="88" align="center">
          <template #default="{ row }">{{ row.version_count }}</template>
        </el-table-column>
        <el-table-column label="大小" width="96">
          <template #default="{ row }">{{ formatBytes(row.last_success_size) }}</template>
        </el-table-column>
        <el-table-column label="备份间隔" width="110">
          <template #default="{ row }">
            <div class="switch-cell">
              <span>{{ formatInterval(row.interval_minutes) }}</span>
              <span class="cell-sub">{{ row.backup_interval_minutes ? '单台设置' : '全局默认' }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="330" fixed="right">
          <template #default="{ row }">
            <div class="row-actions">
              <el-tooltip
                :content="runTooltip(row)"
                placement="top"
              >
                <span>
                  <el-button
                    type="primary"
                    link
                    size="small"
                    :loading="runningSwitchId === row.switch_id"
                    :disabled="!canRun(row)"
                    @click="handleRun(row)"
                  >
                    立即备份
                  </el-button>
                </span>
              </el-tooltip>
              <el-button link size="small" @click="openHistory(row)">历史</el-button>
              <el-button
                link
                size="small"
                :disabled="!row.last_success_id"
                @click="handleDownload(row.last_success_id, row)"
              >
                下载最新
              </el-button>
              <el-button
                link
                size="small"
                :disabled="!row.last_success_id"
                @click="handleViewLatest(row)"
              >
                查看
              </el-button>
              <el-button link size="small" @click="openSwitchSettings(row)">设置</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 版本历史 -->
    <el-dialog v-model="historyVisible" :title="historyTitle" width="1180px" destroy-on-close>
      <template #header>
        <span class="history-dialog-title">
          <el-link
            v-if="currentSwitch"
            type="primary"
            :underline="false"
            @click="goSwitchDetail(currentSwitch.switch_id)"
          >{{ currentSwitch.name }}</el-link>
          <span v-else>备份历史</span>
          <span class="history-dialog-title-suffix" v-if="currentSwitch"> · 备份历史</span>
        </span>
      </template>
      <div class="dialog-toolbar">
        <el-space>
          <el-select v-model="historyStatus" style="width: 150px" @change="loadHistoryPage(1)">
            <el-option label="全部记录" value="" />
            <el-option label="仅成功" value="success" />
            <el-option label="仅失败" value="failed" />
          </el-select>
          <el-button
            :disabled="successVersions.length < 2"
            @click="openDiffDialog"
          >
            版本对比
          </el-button>
        </el-space>
        <el-button :loading="historyLoading" @click="loadHistoryPage(historyPage)">
          <template #icon><el-icon><Refresh /></el-icon></template>
          刷新
        </el-button>
      </div>

      <el-table v-loading="historyLoading" :data="historyItems" size="small" max-height="460" empty-text="暂无备份记录">
        <el-table-column label="开始时间" min-width="160">
          <template #default="{ row }">{{ formatTime(row.started_at) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="触发" width="90">
          <template #default="{ row }">{{ row.trigger_source === 'manual' ? '手动' : '定时' }}</template>
        </el-table-column>
        <el-table-column label="大小" width="96">
          <template #default="{ row }">{{ formatBytes(row.size_bytes) }}</template>
        </el-table-column>
        <el-table-column label="耗时" width="96">
          <template #default="{ row }">{{ formatDuration(row.duration_ms) }}</template>
        </el-table-column>
        <el-table-column label="命令" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">{{ row.command || '—' }}</template>
        </el-table-column>
        <el-table-column label="说明" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">{{ row.message || '—' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button
              link
              size="small"
              :disabled="!row.sha256"
              @click="handleViewRecord(row)"
            >
              查看
            </el-button>
            <el-button
              link
              size="small"
              :disabled="!row.sha256"
              @click="handleDownload(row.id, currentSwitch || {})"
            >
              下载
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        class="dialog-pagination"
        layout="total, prev, pager, next"
        :total="historyTotal"
        :current-page="historyPage"
        :page-size="historyPageSize"
        @current-change="loadHistoryPage"
      />
    </el-dialog>

    <!-- 配置正文 -->
    <el-dialog v-model="contentVisible" :title="contentTitle" width="1000px" destroy-on-close>
      <div v-loading="contentLoading">
        <div v-if="contentMeta" class="content-meta">
          <el-tag size="small" effect="plain">#{{ contentMeta.id }}</el-tag>
          <span>{{ formatTime(contentMeta.started_at) }}</span>
          <span>{{ formatBytes(contentMeta.size_bytes) }}</span>
          <span class="mono">{{ contentMeta.sha256 }}</span>
          <el-button
            link
            type="primary"
            size="small"
            @click="handleDownload(contentMeta.id, currentSwitch || {})"
          >
            下载
          </el-button>
        </div>
        <pre class="config-content">{{ contentText || '（空）' }}</pre>
      </div>
    </el-dialog>

    <!-- 版本对比 -->
    <el-dialog v-model="diffVisible" title="配置版本对比" width="1100px" destroy-on-close>
      <div class="dialog-toolbar">
        <el-space>
          <el-select v-model="diffFromId" placeholder="旧版本" style="width: 300px">
            <el-option
              v-for="ver in successVersions"
              :key="ver.id"
              :label="versionLabel(ver)"
              :value="ver.id"
            />
          </el-select>
          <span>→</span>
          <el-select v-model="diffToId" placeholder="新版本" style="width: 300px">
            <el-option
              v-for="ver in successVersions"
              :key="ver.id"
              :label="versionLabel(ver)"
              :value="ver.id"
            />
          </el-select>
        </el-space>
        <el-button type="primary" :loading="diffLoading" @click="loadDiff">对比</el-button>
      </div>
      <el-alert
        v-if="diffResult?.truncated"
        type="warning"
        :closable="false"
        show-icon
        title="差异过大已截断显示"
        class="diff-alert"
      />
      <div v-loading="diffLoading" class="diff-box">
        <div v-if="!diffResult" class="diff-empty">选择两个成功版本后点击「对比」</div>
        <div v-else-if="!diffLines.length" class="diff-empty">两个版本内容完全一致</div>
        <pre v-else class="diff-content"><div v-for="line in diffLines" :key="line.key" :class="line.cls">{{ line.text || ' ' }}</div></pre>
      </div>
    </el-dialog>

    <!-- 单台设置 -->
    <el-dialog v-model="switchSettingsVisible" :title="switchSettingsTitle" width="560px" destroy-on-close>
      <el-form label-width="130px" label-position="right">
        <el-form-item label="启用备份">
          <el-switch v-model="switchForm.backup_enabled" :disabled="!authStore.isLoggedIn" />
        </el-form-item>
        <el-form-item label="备份间隔（分钟）">
          <el-input-number
            v-model="switchForm.backup_interval_minutes"
            :min="5"
            :max="43200"
            :step="30"
            :placeholder="`留空使用全局 ${globalForm.interval_minutes} 分钟`"
            :disabled="!authStore.isLoggedIn"
          />
        </el-form-item>
        <el-form-item label="设备驱动">
          <el-input
            v-model="switchForm.backup_device_type"
            placeholder="留空自动匹配，例如 cisco_ios"
            :disabled="!authStore.isLoggedIn"
          />
        </el-form-item>
        <el-form-item label="备份命令">
          <el-input
            v-model="switchForm.backup_config_command"
            placeholder="留空使用厂商预设，例如 show running-config"
            :disabled="!authStore.isLoggedIn"
          />
        </el-form-item>
        <el-form-item label="生效结果">
          <div v-if="switchSettingsResult" class="switch-cell">
            <span v-if="switchSettingsResult.resolved_command">
              {{ switchSettingsResult.resolved_device_type }} · {{ switchSettingsResult.resolved_command }}
            </span>
            <span v-else class="warn-text">
              {{ switchSettingsResult.unsupported_reason || '暂无可用驱动/命令，请手动填写上面两项' }}
            </span>
          </div>
          <span v-else class="cell-sub">保存后显示实际使用的驱动和命令</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="switchSettingsVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="savingSwitchSettings"
          :disabled="!authStore.isLoggedIn"
          @click="saveSwitchSettings"
        >
          保存
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh, FolderOpened } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import {
  downloadBackup,
  downloadBackupsBatch,
  fetchBackupContent,
  fetchBackupDiff,
  fetchBackupGlobalSettings,
  fetchBackupHistory,
  fetchBackupOverview,
  runBackupNow,
  updateBackupGlobalSettings,
  updateSwitchBackupSettings
} from '@/api/configBackups'
import type {
  BackupDiffResponse,
  BackupOverviewItem,
  BackupRecord,
  BackupStatus,
  BackupVersionContent,
  SwitchBackupSettingsResponse
} from '@/api/configBackups'

const authStore = useAuthStore()

const STATUS_META: Record<BackupStatus, { text: string; type: 'info' | 'primary' | 'success' | 'danger' | 'warning' }> = {
  never: { text: '未备份', type: 'info' },
  running: { text: '备份中', type: 'primary' },
  success: { text: '成功', type: 'success' },
  failed: { text: '失败', type: 'danger' },
  unsupported: { text: '不支持', type: 'info' },
  skipped: { text: '已跳过', type: 'warning' }
}

const loading = ref(false)
const overview = ref<BackupOverviewItem[]>([])
const keyword = ref('')
const statusFilter = ref('')
const runningSwitchId = ref<number | null>(null)
const overviewTable = ref()
const selectedRows = ref<BackupOverviewItem[]>([])
const batchDownloading = ref(false)

const globalForm = reactive({ interval_minutes: 1440, retention_versions: 30 })
const vendorPresets = ref<Record<string, { device_type: string; command: string }>>({})
const savingSettings = ref(false)

const filteredItems = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return overview.value
  return overview.value.filter(item => {
    const haystack = [item.name, item.ip_address, item.vendor, item.model, item.location]
      .filter(Boolean)
      .join(' ')
      .toLowerCase()
    return haystack.includes(kw)
  })
})

const presetEntries = computed(() =>
  Object.entries(vendorPresets.value).map(([vendor, preset]) => ({
    vendor,
    device_type: preset.device_type,
    command: preset.command
  }))
)

// ---------- 总览 ----------
const loadOverview = async () => {
  loading.value = true
  try {
    const data = await fetchBackupOverview(statusFilter.value || undefined)
    overview.value = data.items
    globalForm.interval_minutes = data.global_interval_minutes
    // 列表重新加载后旧勾选已失效，清空避免误打包
    selectedRows.value = []
    overviewTable.value?.clearSelection?.()
  } catch {
    // apiClient 已统一提示错误
  } finally {
    loading.value = false
  }
}

const loadSettings = async () => {
  try {
    const data = await fetchBackupGlobalSettings()
    globalForm.interval_minutes = data.interval_minutes
    globalForm.retention_versions = data.retention_versions
    vendorPresets.value = data.vendor_presets || {}
  } catch {
    // apiClient 已统一提示错误
  }
}

const loadAll = async () => {
  await Promise.all([loadOverview(), loadSettings()])
}

const saveGlobalSettings = async () => {
  savingSettings.value = true
  try {
    const data = await updateBackupGlobalSettings({
      interval_minutes: globalForm.interval_minutes,
      retention_versions: globalForm.retention_versions
    })
    globalForm.interval_minutes = data.interval_minutes
    globalForm.retention_versions = data.retention_versions
    ElMessage.success('全局设置已保存')
    await loadOverview()
  } catch {
    // apiClient 已统一提示错误
  } finally {
    savingSettings.value = false
  }
}

const canRun = (row: BackupOverviewItem) =>
  authStore.isLoggedIn && row.enabled && row.backup_enabled && row.supported

const runTooltip = (row: BackupOverviewItem) => {
  if (!authStore.isLoggedIn) return '访客只读，请登录后备份'
  if (!row.enabled) return '交换机已停用'
  if (!row.backup_enabled) return '该交换机已关闭自动备份，可在「设置」中开启'
  if (!row.supported) return row.unsupported_reason || '缺少可用驱动或命令，请在「设置」中手动指定'
  return '立即执行一次只读备份'
}

const handleRun = async (row: BackupOverviewItem) => {
  runningSwitchId.value = row.switch_id
  try {
    const result = await runBackupNow(row.switch_id)
    if (result.status === 'success') {
      ElMessage.success(result.message || '备份成功')
    } else {
      ElMessage.warning(result.message || `备份未成功（${result.status}）`)
    }
    await loadOverview()
  } catch {
    // apiClient 已统一提示错误
  } finally {
    runningSwitchId.value = null
  }
}

// ---------- 历史 ----------
const historyVisible = ref(false)
const historyLoading = ref(false)
const historyItems = ref<BackupRecord[]>([])
const historyTotal = ref(0)
const historyPage = ref(1)
const historyPageSize = 20
const historyStatus = ref('')
const currentSwitch = ref<BackupOverviewItem | null>(null)
const successVersions = ref<BackupRecord[]>([])

const historyTitle = computed(() =>
  currentSwitch.value ? `${currentSwitch.value.name} · 备份历史` : '备份历史'
)

const router = useRouter()

// 历史弹窗标题里的交换机名可点击，跳到该交换机详情页
const goSwitchDetail = (switchId: number) => {
  historyVisible.value = false
  router.push({ name: 'SwitchDetail', params: { id: switchId } })
}

const openHistory = (row: BackupOverviewItem) => {
  currentSwitch.value = row
  historyStatus.value = ''
  historyVisible.value = true
  historyPage.value = 1
  void loadHistoryPage(1)
}

const loadHistoryPage = async (page: number) => {
  if (!currentSwitch.value) return
  historyPage.value = page
  historyLoading.value = true
  try {
    const data = await fetchBackupHistory(currentSwitch.value.switch_id, {
      page,
      page_size: historyPageSize,
      status: historyStatus.value || undefined
    })
    historyItems.value = data.items
    historyTotal.value = data.total
    if (!historyStatus.value) {
      // 单独取成功版本供对比选择（不依赖当前分页）
      const successData = await fetchBackupHistory(currentSwitch.value.switch_id, {
        page: 1,
        page_size: 100,
        status: 'success'
      })
      successVersions.value = successData.items
    }
  } catch {
    // apiClient 已统一提示错误
  } finally {
    historyLoading.value = false
  }
}

// ---------- 正文 ----------
const contentVisible = ref(false)
const contentLoading = ref(false)
const contentText = ref('')
const contentMeta = ref<BackupVersionContent | null>(null)
const contentTitle = computed(() =>
  contentMeta.value ? `配置内容 #${contentMeta.value.id}` : '配置内容'
)

const loadContent = async (backupId: number) => {
  contentVisible.value = true
  contentLoading.value = true
  contentText.value = ''
  contentMeta.value = null
  try {
    const data = await fetchBackupContent(backupId)
    contentMeta.value = data
    contentText.value = data.content
  } catch {
    contentVisible.value = false
  } finally {
    contentLoading.value = false
  }
}

const handleViewRecord = (row: BackupRecord) => {
  if (!row.sha256) return
  void loadContent(row.id)
}

const handleViewLatest = (row: BackupOverviewItem) => {
  if (!row.last_success_id) return
  void loadContent(row.last_success_id)
}

const handleDownload = async (backupId: number | null, row: Partial<BackupOverviewItem>) => {
  if (!backupId) return
  try {
    await downloadBackup(backupId, `${row.name || 'switch'}.cfg`)
  } catch {
    // apiClient/blob 下载失败在此兜底提示
    ElMessage.error('下载失败，请稍后重试')
  }
}

const handleSelectionChange = (rows: BackupOverviewItem[]) => {
  selectedRows.value = rows
}

const handleBatchDownload = async () => {
  if (!selectedRows.value.length) return
  batchDownloading.value = true
  try {
    const result = await downloadBackupsBatch(selectedRows.value.map(row => row.switch_id))
    const skippedTip = result.skippedNames.length
      ? `；跳过 ${result.skipped} 台没有成功备份：${result.skippedNames.slice(0, 5).join('、')}${result.skippedNames.length > 5 ? ' 等' : ''}`
      : ''
    ElMessage.success(`已打包 ${result.included} 台交换机的备份${skippedTip}`)
  } catch (error: any) {
    ElMessage.error(error?.message || '批量下载失败，请稍后重试')
  } finally {
    batchDownloading.value = false
  }
}

// ---------- 对比 ----------
const diffVisible = ref(false)
const diffLoading = ref(false)
const diffResult = ref<BackupDiffResponse | null>(null)
const diffFromId = ref<number | null>(null)
const diffToId = ref<number | null>(null)

const versionLabel = (record: BackupRecord) =>
  `#${record.id} · ${formatTime(record.started_at)} · ${formatBytes(record.size_bytes)}`

const openDiffDialog = () => {
  if (successVersions.value.length < 2) return
  diffToId.value = successVersions.value[0].id
  diffFromId.value = successVersions.value[1].id
  diffResult.value = null
  diffVisible.value = true
  void loadDiff()
}

const loadDiff = async () => {
  if (!diffFromId.value || !diffToId.value) {
    ElMessage.warning('请选择两个版本')
    return
  }
  if (diffFromId.value === diffToId.value) {
    ElMessage.warning('请选择两个不同的版本')
    return
  }
  diffLoading.value = true
  diffResult.value = null
  try {
    diffResult.value = await fetchBackupDiff(diffFromId.value, diffToId.value)
  } catch {
    // apiClient 已统一提示错误
  } finally {
    diffLoading.value = false
  }
}

const diffLines = computed(() => {
  if (!diffResult.value) return []
  return diffResult.value.diff.split('\n').map((text, index) => {
    let cls = 'diff-line'
    if (text.startsWith('+++') || text.startsWith('---')) {
      cls += ' diff-meta'
    } else if (text.startsWith('@@')) {
      cls += ' diff-hunk'
    } else if (text.startsWith('+')) {
      cls += ' diff-add'
    } else if (text.startsWith('-')) {
      cls += ' diff-del'
    }
    return { text, cls, key: index }
  })
})

// ---------- 单台设置 ----------
const switchSettingsVisible = ref(false)
const savingSwitchSettings = ref(false)
const switchForm = reactive({
  backup_enabled: true,
  backup_interval_minutes: null as number | null,
  backup_device_type: '',
  backup_config_command: ''
})
const switchSettingsResult = ref<SwitchBackupSettingsResponse | null>(null)
const switchSettingsTitle = computed(() =>
  currentSwitch.value ? `${currentSwitch.value.name} · 备份设置` : '备份设置'
)

const openSwitchSettings = (row: BackupOverviewItem) => {
  currentSwitch.value = row
  switchForm.backup_enabled = row.backup_enabled
  switchForm.backup_interval_minutes = row.backup_interval_minutes
  switchForm.backup_device_type = row.backup_device_type || ''
  switchForm.backup_config_command = row.backup_config_command || ''
  switchSettingsResult.value = null
  switchSettingsVisible.value = true
}

const saveSwitchSettings = async () => {
  if (!currentSwitch.value) return
  savingSwitchSettings.value = true
  try {
    const result = await updateSwitchBackupSettings(currentSwitch.value.switch_id, {
      backup_enabled: switchForm.backup_enabled,
      backup_interval_minutes: switchForm.backup_interval_minutes ?? null,
      backup_device_type: switchForm.backup_device_type.trim() || null,
      backup_config_command: switchForm.backup_config_command.trim() || null
    })
    switchSettingsResult.value = result
    ElMessage.success('备份设置已保存')
    await loadOverview()
  } catch {
    // apiClient 已统一提示错误
  } finally {
    savingSwitchSettings.value = false
  }
}

// ---------- 格式化 ----------
const statusLabel = (status: string) =>
  STATUS_META[status as BackupStatus]?.text || status

const statusTagType = (status: string) =>
  STATUS_META[status as BackupStatus]?.type || 'info'

const formatTime = (value: string | null | undefined) => {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

const formatBytes = (value: number | null | undefined) => {
  if (value == null) return '—'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(2)} MB`
}

const formatDuration = (value: number | null | undefined) => {
  if (value == null) return '—'
  if (value < 1000) return `${value} ms`
  return `${(value / 1000).toFixed(1)} s`
}

const formatInterval = (minutes: number | null | undefined) => {
  if (minutes == null) return '—'
  if (minutes % 1440 === 0) return `${minutes / 1440} 天`
  if (minutes % 60 === 0) return `${minutes / 60} 小时`
  return `${minutes} 分钟`
}

onMounted(loadAll)
</script>

<style scoped>
.config-backups-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 600;
}

.sub-title {
  margin-top: 4px;
  color: #909399;
  font-size: 12px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.settings-form {
  margin-bottom: -8px;
}

.preset-hint {
  margin-top: 4px;
  color: #909399;
  font-size: 12px;
  line-height: 2;
}

.preset-tag {
  margin: 0 6px 6px 0;
}

.table-card :deep(.el-card__body) {
  padding-bottom: 8px;
}

.switch-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.cell-sub {
  color: #909399;
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.warn-text {
  color: #e6a23c;
  font-size: 12px;
}

.row-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 2px 0;
}

.row-actions :deep(.el-button + .el-button) {
  margin-left: 8px;
}

.history-dialog-title {
  font-size: 16px;
  font-weight: 600;
}
.history-dialog-title-suffix {
  color: var(--el-text-color-regular);
  font-weight: 400;
}

.dialog-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  gap: 12px;
  flex-wrap: wrap;
}

.dialog-pagination {
  margin-top: 12px;
  justify-content: flex-end;
}

.content-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 8px;
  color: #606266;
  font-size: 12px;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.config-content {
  margin: 0;
  padding: 12px;
  max-height: 60vh;
  overflow: auto;
  background: #f5f7fa;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre;
  color: #303133;
}

.diff-alert {
  margin-bottom: 8px;
}

.diff-box {
  min-height: 200px;
}

.diff-empty {
  padding: 40px 0;
  text-align: center;
  color: #909399;
  font-size: 13px;
}

.diff-content {
  margin: 0;
  padding: 12px;
  max-height: 56vh;
  overflow: auto;
  background: #ffffff;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 1.5;
  color: #303133;
}

.diff-line {
  white-space: pre;
  padding: 0 4px;
}

.diff-add {
  background: #e7f7e7;
  color: #1a7f37;
}

.diff-del {
  background: #fdecea;
  color: #b42318;
}

.diff-hunk {
  background: #eef4ff;
  color: #2f54eb;
}

.diff-meta {
  color: #909399;
}
</style>
