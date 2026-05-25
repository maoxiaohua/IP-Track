<template>
  <div class="os-type-ip-list">
    <el-card>
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center">
          <div>
            <h2 style="margin: 0">{{ label }} 设备清单</h2>
            <span style="font-size: 13px; color: #909399">共 {{ total }} 台设备（{{ filterType === 'vendor' ? '厂商' : 'OS 类型' }}：{{ filterValue }}）</span>
          </div>
          <el-button @click="exportToCSV" :disabled="!total">
            <el-icon><Download /></el-icon>
            导出 CSV
          </el-button>
        </div>
      </template>

      <el-input
        v-model="searchText"
        placeholder="搜索 IP、主机名、MAC、描述..."
        clearable
        style="margin-bottom: 16px; width: 360px"
        @change="handleSearch"
      >
        <template #prefix>
          <el-icon><Search /></el-icon>
        </template>
      </el-input>

      <el-table
        :data="ipList"
        v-loading="loading"
        stripe
        style="width: 100%"
        @row-click="handleRowClick"
        :row-style="{ cursor: 'pointer' }"
      >
        <el-table-column prop="ip_address" label="IP 地址" width="160" sortable="custom" />
        <el-table-column label="主机名" min-width="200">
          <template #default="{ row }">
            {{ row.hostname || row.dns_name || row.system_name || '-' }}
          </template>
        </el-table-column>
        <el-table-column label="MAC 地址" width="160">
          <template #default="{ row }">
            {{ row.mac_address || '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="os_name" label="操作系统" width="140">
          <template #default="{ row }">
            {{ row.os_name || row.os_type || '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="90">
          <template #default="{ row }">
            <el-tag
              :type="row.status === 'used' ? 'success' : row.status === 'offline' ? 'danger' : row.status === 'reserved' ? 'warning' : 'info'"
              size="small"
            >
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="subnet_name" label="子网" min-width="180">
          <template #default="{ row }">
            <router-link
              v-if="row.subnet_id"
              :to="`/ipam/subnets/${row.subnet_id}`"
              style="color: var(--primary-color); text-decoration: none"
              @click.stop
            >
              {{ row.subnet_name || row.subnet_id }}
            </router-link>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column prop="switch_name" label="交换机" min-width="180">
          <template #default="{ row }">
            <router-link
              v-if="row.switch_id"
              :to="`/switches/${row.switch_id}`"
              style="color: var(--primary-color); text-decoration: none"
              @click.stop
            >
              {{ row.switch_name || row.switch_id }}
            </router-link>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column prop="switch_port" label="端口" width="100">
          <template #default="{ row }">
            {{ row.switch_port || '-' }}
          </template>
        </el-table-column>
        <el-table-column label="最后扫描" width="140">
          <template #default="{ row }">
            {{ row.last_scan_at ? formatTime(row.last_scan_at) : '-' }}
          </template>
        </el-table-column>
      </el-table>

      <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 16px">
        <span style="font-size: 13px; color: #909399">共 {{ total }} 条记录</span>
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :page-sizes="[50, 100, 200, 500]"
          :total="total"
          layout="total, sizes, prev, pager, next, jumper"
          @current-change="loadData"
          @size-change="handlePageSizeChange"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Download, Search } from '@element-plus/icons-vue'
import { ipamApi, type IPAddressDetail } from '@/api/ipam'

const route = useRoute()
const router = useRouter()

const filterType = computed(() => {
  if (route.query.os_type) return 'os_type'
  if (route.query.vendor) return 'vendor'
  return 'os_type'
})
const filterValue = computed(() => (route.query[filterType.value] as string) || '')
const label = computed(() => (route.query.label as string) || filterValue.value || '设备清单')

const ipList = ref<IPAddressDetail[]>([])
const loading = ref(false)
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(100)
const searchText = ref('')

async function loadData() {
  loading.value = true
  try {
    const params: Record<string, any> = {
      limit: pageSize.value,
      skip: (currentPage.value - 1) * pageSize.value
    }
    params[filterType.value] = filterValue.value
    if (searchText.value.trim()) {
      params.search = searchText.value.trim()
    }
    const response = await ipamApi.getIPAddresses(params)
    ipList.value = response.items || []
    total.value = response.total || 0
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '加载设备清单失败')
    ipList.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  currentPage.value = 1
  loadData()
}

function handlePageSizeChange() {
  currentPage.value = 1
  loadData()
}

function handleRowClick(row: IPAddressDetail) {
  router.push(`/ipam/subnets/${row.subnet_id}`)
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    used: '在线',
    available: '可用',
    reserved: '保留',
    offline: '离线'
  }
  return map[status] || status || '-'
}

function formatTime(dateStr: string): string {
  try {
    const date = new Date(dateStr)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMins = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMs / 3600000)
    const diffDays = Math.floor(diffMs / 86400000)

    if (diffMins < 1) return '刚刚'
    if (diffMins < 60) return `${diffMins} 分钟前`
    if (diffHours < 24) return `${diffHours} 小时前`
    if (diffDays < 7) return `${diffDays} 天前`

    return date.toLocaleDateString('zh-CN')
  } catch {
    return dateStr
  }
}

function exportToCSV() {
  if (ipList.value.length === 0) {
    ElMessage.warning('没有数据可导出')
    return
  }

  const exportData = ipList.value.map(row => ({
    'IP 地址': row.ip_address,
    '主机名': row.hostname || row.dns_name || row.system_name || '',
    'MAC 地址': row.mac_address || '',
    '操作系统': row.os_name || row.os_type || '',
    '状态': statusLabel(row.status),
    '子网': row.subnet_name || '',
    '交换机': row.switch_name || '',
    '端口': row.switch_port || '',
    '最后扫描': row.last_scan_at ? formatTime(row.last_scan_at) : ''
  }))

  import('@/utils/export').then(({ exportToCSV: doExport }) => {
    doExport(exportData, `${label.value}_${new Date().toISOString().slice(0, 10)}`)
    ElMessage.success(`已导出 ${ipList.value.length} 条记录`)
  })
}

onMounted(() => {
  loadData()
})
</script>

<style scoped>
.os-type-ip-list {
  padding: 20px;
}
</style>
