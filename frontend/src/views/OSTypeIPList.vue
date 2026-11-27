<template>
  <div class="os-type-ip-list">
    <el-card>
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center">
          <div>
            <h2 style="margin: 0">{{ label }} 设备清单</h2>
            <span style="font-size: 13px; color: #909399">共 {{ total }} 台设备（{{ filterLabel }}：{{ filterDisplay }}）</span>
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

      <div class="table-toolbar">
        <span class="table-count">共 {{ total }} 条记录（当前页 {{ ipList.length }} 条）</span>
        <ColumnSettings
          :columns="columns"
          :is-visible="isVisible"
          :saving="columnSaving"
          @toggle="toggle"
          @reset="resetColumns"
          @save="saveColumns"
        />
      </div>

      <IPAddressTable
        :rows="ipList"
        :columns="visibleColumns"
        :loading="loading"
        loading-text="正在加载设备清单..."
        wrapper-max-height="70vh"
        default-sort-prop="ip_address"
        row-clickable
        @row-click="handleRowClick"
        @ip-click="handleRowClick"
      />

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
import IPAddressTable from '@/components/ipam/IPAddressTable.vue'
import ColumnSettings from '@/components/ipam/ColumnSettings.vue'
import { buildIPExportRows } from '@/components/ipam/ipColumns'
import { useColumnPreferences } from '@/composables/useColumnPreferences'

const route = useRoute()
const router = useRouter()

const filterType = computed(() => {
  if (route.query.os_type) return 'os_type'
  if (route.query.vendor) return 'vendor'
  if (route.query.vendor_missing) return 'vendor_missing'
  return 'os_type'
})
const filterValue = computed(() => (
  filterType.value === 'vendor_missing'
    ? ''
    : (route.query[filterType.value] as string) || ''
))
const filterLabel = computed(() => (filterType.value === 'os_type' ? 'OS 类型' : '厂商'))
const filterDisplay = computed(() => (
  filterType.value === 'vendor_missing' ? '未识别' : filterValue.value
))
const label = computed(() => (route.query.label as string) || filterDisplay.value || '设备清单')

const ipList = ref<IPAddressDetail[]>([])
const loading = ref(false)
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(100)
const searchText = ref('')

// 列显示偏好（按账号保存）；与子网详情使用同一套列和默认显示，保证两处参数完全一致
const {
  columns,
  visibleColumns,
  isVisible,
  saving: columnSaving,
  load: loadColumnPreferences,
  save: handleColumnSave,
  toggle,
  reset
} = useColumnPreferences('ipam.os-type-ip-list')

const saveColumns = async () => {
  try {
    await handleColumnSave()
  } catch (error) {
    ElMessage.error('列设置保存失败')
  }
}

const resetColumns = async () => {
  reset()
  await saveColumns()
}

async function loadData() {
  loading.value = true
  try {
    const params: Record<string, any> = {
      limit: pageSize.value,
      skip: (currentPage.value - 1) * pageSize.value
    }
    if (filterType.value === 'vendor_missing') {
      params.vendor_missing = true
    } else {
      params[filterType.value] = filterValue.value
    }
    if (searchText.value.trim()) {
      params.search = searchText.value.trim()
    }
    // 从扇形图钻取时必须与扇区口径一致：显式传参，不能依赖后端默认全量
    params.include_archived = route.query.include_archived === '1'
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

function exportToCSV() {
  if (ipList.value.length === 0) {
    ElMessage.warning('没有数据可导出')
    return
  }

  // 与表格共用同一套列定义，页面新增列后导出自动跟随
  const exportData = buildIPExportRows(ipList.value)

  import('@/utils/export').then(({ exportToCSV: doExport }) => {
    doExport(exportData, `${label.value}_${new Date().toISOString().slice(0, 10)}`)
    ElMessage.success(`已导出 ${ipList.value.length} 条记录`)
  })
}

onMounted(() => {
  loadData()
  void loadColumnPreferences()
})
</script>

<style scoped>
.os-type-ip-list {
  padding: 20px;
}

.table-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.table-count {
  color: #909399;
  font-size: 13px;
}
</style>
