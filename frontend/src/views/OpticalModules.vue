<template>
  <div class="optical-modules-container">
    <el-card class="header-card">
      <template #header>
        <div class="card-header">
          <span class="title">光模块搜索</span>
          <div class="actions">
            <el-button
              type="primary"
              :icon="Refresh"
              :loading="collecting"
              @click="collectAllModules"
            >
              采集所有光模块
            </el-button>
          </div>
        </div>
      </template>

      <el-form :model="searchForm" label-width="120px" @submit.prevent="searchModules">
        <el-row :gutter="20">
          <el-col :span="8">
            <el-form-item label="序列号">
              <el-input
                v-model="searchForm.serial_number"
                placeholder="输入序列号"
                clearable
              />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="型号">
              <el-input
                v-model="searchForm.model"
                placeholder="输入型号"
                clearable
              />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="厂商">
              <el-input
                v-model="searchForm.vendor"
                placeholder="输入厂商"
                clearable
              />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="20">
          <el-col :span="8">
            <el-form-item label="交换机名称">
              <el-input
                v-model="searchForm.switch_name"
                placeholder="输入交换机名称"
                clearable
              />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="交换机IP">
              <el-input
                v-model="searchForm.switch_ip"
                placeholder="输入交换机IP"
                clearable
              />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="端口">
              <el-input
                v-model="searchForm.port_name"
                placeholder="输入端口名称"
                clearable
              />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="20">
          <el-col :span="8">
            <el-form-item label="模块类型">
              <el-select
                v-model="searchForm.module_type"
                placeholder="选择模块类型"
                clearable
                style="width: 100%"
              >
                <el-option label="SFP" value="SFP" />
                <el-option label="SFP+" value="SFP+" />
                <el-option label="QSFP" value="QSFP" />
                <el-option label="QSFP+" value="QSFP+" />
                <el-option label="QSFP28" value="QSFP28" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="16">
            <el-form-item>
              <el-button type="primary" :icon="Search" @click="searchModules" :loading="loading">
                搜索
              </el-button>
              <el-button @click="resetSearch">重置</el-button>
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
    </el-card>

    <el-alert
      title="当前页面同时展示当前存在的光模块和历史缓存"
      type="info"
      description="当交换机离线、采集失败，或本轮成功采集未再次发现某模块时，系统会保留历史记录并标记为“历史缓存”，用于故障追踪和资产回溯。"
      :closable="false"
      show-icon
      style="margin-bottom: 20px;"
    />

    <!-- Statistics Card -->
    <el-card class="stats-card" v-if="statistics">
      <template #header>
        <span>统计信息</span>
      </template>
      <el-row :gutter="20">
        <el-col :span="4">
          <el-statistic title="总计" :value="statistics.total_modules" />
        </el-col>
        <el-col :span="4">
          <el-statistic title="当前存在" :value="statistics.present_modules" />
        </el-col>
        <el-col :span="4">
          <el-statistic title="历史缓存" :value="statistics.historical_modules" />
        </el-col>
        <el-col :span="4">
          <el-statistic title="有模块交换机" :value="statistics.switches_with_modules" />
        </el-col>
        <el-col :span="4">
          <el-statistic title="当前有模块交换机" :value="statistics.switches_with_present_modules" />
        </el-col>
        <el-col :span="4">
          <el-statistic title="Stale交换机" :value="statistics.stale_switches" />
        </el-col>
      </el-row>
      <el-row :gutter="20" style="margin-top: 16px;">
        <el-col :span="8">
          <div class="stat-item">
            <div class="stat-title">按类型</div>
            <div class="stat-list">
              <div v-for="(count, type) in statistics.by_type" :key="type" class="stat-line">
                <span>{{ type }}:</span>
                <span>{{ count }}</span>
              </div>
            </div>
          </div>
        </el-col>
        <el-col :span="8">
          <div class="stat-item">
            <div class="stat-title">按速率</div>
            <div class="stat-list">
              <div v-for="(count, speed) in statistics.by_speed" :key="speed" class="stat-line">
                <span>{{ speed }}:</span>
                <span>{{ count }}</span>
              </div>
            </div>
          </div>
        </el-col>
        <el-col :span="8">
          <div class="stat-item">
            <div class="stat-title">Top厂商</div>
            <div class="stat-list">
              <div v-for="([vendorName, vendorCount], index) in Object.entries(statistics.by_vendor).slice(0, 5)" :key="`${vendorName}-${index}`" class="stat-line">
                <span>{{ vendorName }}:</span>
                <span>{{ vendorCount }}</span>
              </div>
            </div>
          </div>
        </el-col>
      </el-row>
    </el-card>

    <!-- Results Table -->
    <el-card class="results-card">
      <template #header>
        <div class="card-header">
          <span>
            搜索结果 ({{ searchResults.total || 0 }})
            <span v-if="searchResults.total > 0" style="font-size: 12px; color: #909399; margin-left: 8px;">
              当前存在 {{ searchResults.present_count || 0 }} / 历史缓存 {{ searchResults.historical_count || 0 }}
            </span>
          </span>
          <el-button
            v-if="searchResults.modules && searchResults.modules.length > 0"
            size="small"
            @click="exportToExcel"
          >
            导出Excel
          </el-button>
        </div>
      </template>

      <el-table
        :data="searchResults.modules"
        stripe
        :loading="loading"
        style="width: 100%"
        @row-click="handleRowClick"
      >
        <el-table-column prop="presence_status" label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="row.is_present ? 'success' : 'warning'" size="small">
              {{ row.is_present ? '当前存在' : '历史缓存' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="serial_number" label="序列号" width="150" />
        <el-table-column prop="model" label="型号" width="180" />
        <el-table-column prop="vendor" label="厂商" width="120" />
        <el-table-column prop="module_type" label="类型" width="100">
          <template #default="{ row }">
            <el-tag
              :type="getModuleTypeTag(row.module_type)"
              size="small"
            >
              {{ row.module_type || 'Unknown' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="speed_gbps" label="速率" width="80">
          <template #default="{ row }">
            {{ row.speed_gbps ? row.speed_gbps + 'G' : '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="switch_name" label="交换机" width="200" />
        <el-table-column prop="switch_ip" label="交换机IP" width="140" />
        <el-table-column prop="port_name" label="端口" width="120" />
        <el-table-column prop="last_seen" label="最近确认时间" width="180">
          <template #default="{ row }">
            {{ formatDateTime(row.last_seen) }}
          </template>
        </el-table-column>
        <el-table-column prop="switch_last_optical_collection_status" label="交换机光模块状态" width="150">
          <template #default="{ row }">
            <el-tag
              :type="row.switch_last_optical_collection_status === 'success' ? 'success' : row.switch_last_optical_collection_status === 'empty' ? 'info' : row.switch_last_optical_collection_status === 'failed' ? 'danger' : 'warning'"
              size="small"
            >
              {{ row.switch_last_optical_collection_status || '-' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button
              link
              type="primary"
              size="small"
              @click.stop="goToSwitch(row.switch_id)"
            >
              查看交换机
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-if="searchResults.total > 0"
        v-model:current-page="pagination.page"
        v-model:page-size="pagination.pageSize"
        :page-sizes="[20, 50, 100, 200]"
        :total="searchResults.total"
        layout="total, sizes, prev, pager, next, jumper"
        @current-change="handlePageChange"
        @size-change="handleSizeChange"
        style="margin-top: 20px; justify-content: center"
      />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Refresh } from '@element-plus/icons-vue'
import apiClient from '@/api'

const router = useRouter()

interface SearchForm {
  serial_number: string
  model: string
  vendor: string
  switch_name: string
  switch_ip: string
  port_name: string
  module_type: string
}

interface OpticalModule {
  id: number
  serial_number: string
  model: string
  part_number: string
  vendor: string
  module_type: string
  speed_gbps: number | null
  switch_id: number
  switch_name: string
  switch_ip: string
  port_name: string
  collected_at: string
  first_seen: string
  last_seen: string
  presence_status: 'present' | 'historical'
  is_present: boolean
  freshness_status: 'fresh' | 'stale'
  freshness_warning?: string | null
  switch_is_reachable?: boolean | null
  switch_last_optical_collection_at?: string | null
  switch_last_optical_success_at?: string | null
  switch_last_optical_collection_status?: string | null
  switch_last_optical_collection_message?: string | null
}

interface SearchResults {
  total: number
  count: number
  offset: number
  limit: number
  present_count: number
  historical_count: number
  modules: OpticalModule[]
}

interface Statistics {
  total_modules: number
  present_modules: number
  historical_modules: number
  switches_with_modules: number
  switches_with_present_modules: number
  stale_switches: number
  by_type: Record<string, number>
  by_vendor: Record<string, number>
  by_speed: Record<string, number>
  collections_last_24h: number
}

const searchForm = ref<SearchForm>({
  serial_number: '',
  model: '',
  vendor: '',
  switch_name: '',
  switch_ip: '',
  port_name: '',
  module_type: ''
})

const searchResults = ref<SearchResults>({
  total: 0,
  count: 0,
  offset: 0,
  limit: 100,
  present_count: 0,
  historical_count: 0,
  modules: []
})

const statistics = ref<Statistics | null>(null)

const pagination = ref({
  page: 1,
  pageSize: 100
})

const loading = ref(false)
const collecting = ref(false)

// Load statistics on mount
onMounted(async () => {
  await loadStatistics()
  // Auto-search to show all modules initially
  await searchModules()
})

async function loadStatistics() {
  try {
    const response = await apiClient.get('/api/v1/network/optical-modules/statistics')
    statistics.value = response.data
  } catch (error: any) {
    console.error('Failed to load statistics:', error)
  }
}

async function searchModules() {
  loading.value = true
  try {
    const params: any = {
      limit: pagination.value.pageSize,
      offset: (pagination.value.page - 1) * pagination.value.pageSize
    }

    // Only add non-empty search parameters
    if (searchForm.value.serial_number) params.serial_number = searchForm.value.serial_number
    if (searchForm.value.model) params.model = searchForm.value.model
    if (searchForm.value.vendor) params.vendor = searchForm.value.vendor
    if (searchForm.value.switch_name) params.switch_name = searchForm.value.switch_name
    if (searchForm.value.switch_ip) params.switch_ip = searchForm.value.switch_ip
    if (searchForm.value.port_name) params.port_name = searchForm.value.port_name
    if (searchForm.value.module_type) params.module_type = searchForm.value.module_type

    const response = await apiClient.get('/api/v1/network/optical-modules/search', { params })
    searchResults.value = response.data
  } catch (error: any) {
    ElMessage.error(`搜索失败: ${error.response?.data?.detail || error.message}`)
  } finally {
    loading.value = false
  }
}

async function resetSearch() {
  searchForm.value = {
    serial_number: '',
    model: '',
    vendor: '',
    switch_name: '',
    switch_ip: '',
    port_name: '',
    module_type: ''
  }
  pagination.value.page = 1
  await searchModules()
}

async function collectAllModules() {
  try {
    const result = await ElMessageBox.confirm(
      '这将从所有交换机采集光模块信息，可能需要较长时间。确认继续？',
      '采集光模块',
      {
        confirmButtonText: '确认',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )

    if (result) {
      collecting.value = true
      ElMessage.info('光模块采集任务已启动，请稍候...')

      const response = await apiClient.post('/api/v1/network/optical-modules/collect')

      ElMessage.success(
        `采集完成！成功: ${response.data.switches_success}/${response.data.switches_total} 台交换机，共 ${response.data.total_modules} 个光模块`
      )

      // Reload data
      await Promise.all([loadStatistics(), searchModules()])
    }
  } catch (error: any) {
    if (error !== 'cancel') {
      ElMessage.error(`采集失败: ${error.response?.data?.detail || error.message}`)
    }
  } finally {
    collecting.value = false
  }
}

function handlePageChange(page: number) {
  pagination.value.page = page
  searchModules()
}

function handleSizeChange(size: number) {
  pagination.value.pageSize = size
  pagination.value.page = 1
  searchModules()
}

function handleRowClick(row: OpticalModule) {
  console.log('Row clicked:', row)
}

function goToSwitch(switchId: number) {
  router.push(`/switches/${switchId}`)
}

function getModuleTypeTag(type: string | null): string {
  if (!type) return 'info'
  const upperType = type.toUpperCase()
  if (upperType.includes('QSFP28')) return 'danger'
  if (upperType.includes('QSFP')) return 'warning'
  if (upperType.includes('SFP+')) return 'success'
  if (upperType.includes('SFP')) return 'primary'
  return 'info'
}

function formatDateTime(dateStr?: string | null): string {
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

function exportToExcel() {
  ElMessage.info('导出功能开发中...')
}
</script>

<style scoped>
.optical-modules-container {
  padding: 20px;
}

.header-card {
  margin-bottom: 20px;
}

.stats-card {
  margin-bottom: 20px;
}

.results-card {
  margin-bottom: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.title {
  font-size: 18px;
  font-weight: bold;
}

.stat-item {
  padding: 10px;
}

.stat-title {
  font-size: 14px;
  color: #606266;
  margin-bottom: 10px;
  font-weight: bold;
}

.stat-list {
  font-size: 13px;
}

.stat-line {
  display: flex;
  justify-content: space-between;
  margin-bottom: 5px;
}

.stat-line span:first-child {
  color: #909399;
}

.stat-line span:last-child {
  font-weight: bold;
  color: #303133;
}

:deep(.el-table) {
  cursor: pointer;
}

:deep(.el-table__row):hover {
  background-color: #f5f7fa;
}
</style>
