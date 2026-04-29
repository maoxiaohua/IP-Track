<template>
  <div class="subnet-detail-solarwinds">
    <el-card>
      <template #header>
        <div class="header-bar">
          <div>
            <h2 style="margin: 0 0 8px 0">{{ subnet.network || 'Loading...' }}</h2>
            <div style="color: #909399">
              <span v-if="subnet.subnet_name">{{ subnet.subnet_name }} | </span>
              <span>{{ subnet.total_ips || 0 }} addresses | </span>
              <span style="color: #67c23a">{{ subnet.available_ips || 0 }} available</span>
              <span> | </span>
              <span style="color: #409eff">{{ subnet.used_ips || 0 }} used</span>
              <span> | </span>
              <span>Last Scan: {{ subnet.last_scan_at ? formatDateTime(subnet.last_scan_at) : 'Never' }}</span>
            </div>
          </div>
          <div style="display: flex; gap: 10px">
            <el-button type="primary" plain @click="$router.back()">
              <el-icon><Back /></el-icon>
              返回
            </el-button>
            <el-button type="primary" plain @click="showEditDialog = true">
              <el-icon><Edit /></el-icon>
              编辑子网
            </el-button>
            <el-button type="success" @click="scanSubnet" :loading="scanning || isCurrentSubnetScanning" :disabled="Boolean(scanStatus?.running)">
              <el-icon><Refresh /></el-icon>
              扫描子网
            </el-button>
          </div>
        </div>
      </template>

      <div v-if="shouldShowScanStatus" class="detail-scan-status">
        <div class="detail-scan-status-top">
          <div>
            <div class="detail-scan-title">{{ scanSourceLabel }} | {{ scanTypeLabel }} | {{ scanStatus?.phase_label || '状态未知' }}</div>
            <div class="detail-scan-message">{{ scanStatus?.message || '等待扫描状态更新' }}</div>
          </div>
          <el-tag :type="scanStatus?.running ? 'warning' : scanStatus?.current_phase === 'error' ? 'danger' : 'success'">
            {{ scanStatus?.running ? '进行中' : scanStatus?.current_phase === 'error' ? '失败' : '完成' }}
          </el-tag>
        </div>

        <div class="detail-scan-metrics">
          <span>当前子网: {{ currentScanSubnetLabel }}</span>
          <span>子网进度: {{ subnetProgressText }}</span>
          <span>主机探测: {{ quickProgressText }}</span>
          <span>识别进度: {{ enrichmentProgressText }}</span>
        </div>

        <el-progress
          v-if="scanStatus?.running"
          :percentage="scanProgressPercent"
          :stroke-width="14"
          status="success"
        />
      </div>

      <!-- Filters -->
      <el-row :gutter="20" style="margin-bottom: 20px">
        <el-col :span="6">
          <el-select v-model="filters.status" placeholder="筛选状态" clearable @change="loadIPs">
            <el-option label="All" value="" />
            <el-option label="Available" value="available" />
            <el-option label="Used" value="used" />
            <el-option label="Reserved" value="reserved" />
          </el-select>
        </el-col>
        <el-col :span="6">
          <el-select v-model="filters.is_reachable" placeholder="筛选可达性" clearable @change="loadIPs">
            <el-option label="All" value="" />
            <el-option label="Online" :value="true" />
            <el-option label="Offline" :value="false" />
          </el-select>
        </el-col>
        <el-col :span="12">
          <el-input
            v-model="filters.search"
            placeholder="搜索 IP 地址、主机名、DNS 名称..."
            clearable
            @change="loadIPs"
          >
            <template #prefix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>
        </el-col>
      </el-row>

      <!-- IP Table (SolarWinds Style) - All IPs shown for easy searching -->
      <div style="margin-bottom: 10px; color: #909399; font-size: 13px">
        显示全部 {{ ipAddresses.length }} 个 IP 地址
      </div>
      <el-table
        :data="ipAddresses"
        v-loading="loading"
        stripe
        style="width: 100%"
        :default-sort="{ prop: 'ip_address', order: 'ascending' }"
        highlight-current-row
        :current-row-key="selectedIpId || undefined"
        row-key="id"
      >
        <!-- Status Icon -->
        <el-table-column label="Status" width="80" align="center">
          <template #default="{ row }">
            <el-tooltip :content="getStatusTooltip(row)" placement="top">
              <div style="display: flex; align-items: center; justify-content: center">
                <el-icon v-if="row.is_reachable" :size="20" style="color: #67c23a">
                  <CircleCheckFilled />
                </el-icon>
                <el-icon v-else-if="row.status === 'used'" :size="20" style="color: #f56c6c">
                  <CircleCloseFilled />
                </el-icon>
                <el-icon v-else-if="row.status === 'reserved'" :size="20" style="color: #e6a23c">
                  <WarningFilled />
                </el-icon>
                <el-icon v-else :size="20" style="color: #909399">
                  <Remove />
                </el-icon>
              </div>
            </el-tooltip>
          </template>
        </el-table-column>

        <!-- IP Address -->
        <el-table-column prop="ip_address" label="IP Address" width="140" sortable :sort-method="sortByIpAddress">
          <template #default="{ row }">
            <span
              class="ip-address-link"
              @click="openIPDetail(row.id)"
            >{{ row.ip_address }}</span>
          </template>
        </el-table-column>

        <!-- Last Response (IMPORTANT!) -->
        <el-table-column label="Last Response" width="140" sortable :sort-method="sortByLastResponse">
          <template #default="{ row }">
            <span :style="{ color: getLastResponseColor(row) }">
              {{ getLastResponse(row) }}
            </span>
          </template>
        </el-table-column>

        <!-- Response Time -->
        <el-table-column label="Response Time" width="120">
          <template #default="{ row }">
            <span v-if="row.response_time != null">{{ row.response_time }} ms</span>
            <span v-else style="color: #909399">-</span>
          </template>
        </el-table-column>

        <!-- DNS Name -->
        <el-table-column prop="dns_name" label="DNS" min-width="180">
          <template #default="{ row }">
            {{ row.dns_name || row.hostname || '-' }}
          </template>
        </el-table-column>

        <!-- System Name -->
        <el-table-column prop="system_name" label="System Name" min-width="150">
          <template #default="{ row }">
            {{ row.system_name || '-' }}
          </template>
        </el-table-column>

        <!-- Machine Type -->
        <el-table-column prop="machine_type" label="Machine Type" min-width="150">
          <template #default="{ row }">
            {{ row.machine_type || '-' }}
          </template>
        </el-table-column>

        <!-- Vendor -->
        <el-table-column prop="vendor" label="Vendor" width="120">
          <template #default="{ row }">
            {{ row.vendor || '-' }}
          </template>
        </el-table-column>

        <!-- Switch Name -->
        <el-table-column prop="switch_name" label="Switch" min-width="200">
          <template #default="{ row }">
            <router-link
              v-if="row.switch_id"
              :to="`/switches/${row.switch_id}`"
              style="color: #409eff; text-decoration: none"
            >
              {{ row.switch_name || '-' }}
            </router-link>
            <span v-else style="color: #909399">-</span>
          </template>
        </el-table-column>

        <!-- Switch Port -->
        <el-table-column prop="switch_port" label="Port" width="120">
          <template #default="{ row }">
            <el-tag v-if="row.switch_port" type="success" size="small">{{ row.switch_port }}</el-tag>
            <span v-else style="color: #909399">-</span>
          </template>
        </el-table-column>

        <!-- OS Type -->
        <el-table-column prop="os_type" label="OS Type" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.os_type === 'windows'" type="primary" size="small">Windows</el-tag>
            <el-tag v-else-if="row.os_type === 'linux'" type="success" size="small">Linux</el-tag>
            <el-tag v-else-if="row.os_type === 'network'" type="warning" size="small">Network</el-tag>
            <el-tag v-else-if="row.os_type === 'unix'" type="info" size="small">Unix</el-tag>
            <span v-else style="color: #909399">-</span>
          </template>
        </el-table-column>

        <!-- OS Name -->
        <el-table-column prop="os_name" label="OS Name" min-width="140">
          <template #default="{ row }">
            {{ row.os_name || '-' }}
          </template>
        </el-table-column>

        <!-- OS Version -->
        <el-table-column prop="os_version" label="OS Version" width="120">
          <template #default="{ row }">
            {{ row.os_version || '-' }}
          </template>
        </el-table-column>

        <!-- Last Boot Time -->
        <el-table-column label="Last Boot Time" min-width="160">
          <template #default="{ row }">
            {{ row.last_boot_time ? formatDateTime(row.last_boot_time) : '-' }}
          </template>
        </el-table-column>
      </el-table>

    </el-card>

    <!-- IP Detail Drawer -->
    <IPDetailDrawer
      v-model="showDrawer"
      :ip-id="selectedIpId"
      :refresh-key="detailDrawerRefreshKey"
    />

    <!-- Edit Subnet Dialog -->
    <el-dialog v-model="showEditDialog" title="编辑 IP 子网" width="600px">
      <el-form :model="editForm" label-width="120px">
        <el-form-item label="子网名称">
          <el-input v-model="editForm.name" placeholder="例如: 办公网络" />
        </el-form-item>
        <el-form-item label="网络地址">
          <el-input v-model="editForm.network" disabled />
        </el-form-item>
        <el-form-item label="网关">
          <el-input v-model="editForm.gateway" placeholder="例如: 10.0.0.1" />
        </el-form-item>
        <el-form-item label="VLAN ID">
          <el-input-number v-model="editForm.vlan_id" :min="1" :max="4094" />
        </el-form-item>
        <el-form-item label="DNS 服务器">
          <el-input v-model="editForm.dns_servers" placeholder="例如: 8.8.8.8,8.8.4.4" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="editForm.description" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showEditDialog = false">取消</el-button>
        <el-button type="primary" @click="handleEditSubmit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Back,
  Edit,
  Refresh,
  Search,
  CircleCheckFilled,
  CircleCloseFilled,
  WarningFilled,
  Remove
} from '@element-plus/icons-vue'
import apiClient from '@/api/index'
import { ipamApi, type IPAMScanStatus } from '@/api/ipam'
import IPDetailDrawer from '@/components/IPDetailDrawer.vue'
import { useIPAMScanMonitor } from '@/composables/useIPAMScanMonitor'

interface IPAddress {
  id: number
  ip_address: string
  status: string
  is_reachable: boolean
  response_time?: number
  hostname?: string
  dns_name?: string
  system_name?: string
  machine_type?: string
  vendor?: string
  switch_id?: number
  switch_name?: string
  switch_port?: string
  vlan_id?: number
  os_type?: string
  os_name?: string
  os_version?: string
  last_boot_time?: string
  description?: string
  last_seen_at?: string
  last_scan_at?: string
}

interface Subnet {
  id?: number
  network: string
  subnet_name: string
  name?: string
  total_ips: number
  available_ips: number
  used_ips: number
  last_scan_at?: string
}

const route = useRoute()
const subnetId = parseInt(route.params.id as string)

const subnet = ref<Subnet>({
  network: '',
  subnet_name: '',
  total_ips: 0,
  available_ips: 0,
  used_ips: 0,
  last_scan_at: ''
})
const ipAddresses = ref<IPAddress[]>([])
const loading = ref(false)
const scanning = ref(false)
const showEditDialog = ref(false)

const editForm = ref({
  name: '',
  network: '',
  gateway: '',
  vlan_id: undefined as number | undefined,
  dns_servers: '',
  description: ''
})

const filters = ref({
  status: '',
  is_reachable: '' as boolean | string,
  search: ''
})

const showDrawer = ref(false)
const selectedIpId = ref<number | null>(null)
const detailDrawerRefreshKey = ref(0)
let lastStatusNotificationKey = ''

const openIPDetail = (ipId: number) => {
  if (selectedIpId.value === ipId && showDrawer.value) {
    detailDrawerRefreshKey.value += 1
    return
  }
  selectedIpId.value = ipId
  showDrawer.value = true
}

const handleScanStatusChange = (status: IPAMScanStatus, previous: IPAMScanStatus | null) => {
  if (status.subnet_id === subnetId && status.current_subnet_last_scan_at) {
    subnet.value.last_scan_at = status.current_subnet_last_scan_at
  }

  const notificationKey = `${status.type || status.current_phase}:${status.session_id || 'none'}:${status.updated_at || ''}`

  if (
    status.subnet_id === subnetId &&
    previous?.current_subnet_last_scan_at !== status.current_subnet_last_scan_at &&
    status.current_subnet_last_scan_at
  ) {
    void loadSubnet()
    void loadIPs()
    if (showDrawer.value && selectedIpId.value) {
      detailDrawerRefreshKey.value += 1
    }
  }

  if (notificationKey === lastStatusNotificationKey) {
    return
  }

  if (status.type === 'complete') {
    lastStatusNotificationKey = notificationKey
    if (status.subnet_id === subnetId && status.source === 'manual') {
      const summary = status.summary as any
      ElMessage.success(
        status.message ||
        `扫描完成：${summary?.reachable ?? 0} 个在线，${summary?.unreachable ?? 0} 个离线`
      )
    }
    if (status.subnet_id === subnetId) {
      void loadSubnet()
      void loadIPs()
      if (showDrawer.value && selectedIpId.value) {
        detailDrawerRefreshKey.value += 1
      }
    }
    return
  }

  if (status.type === 'error') {
    lastStatusNotificationKey = notificationKey
    if (status.subnet_id === subnetId || status.source === 'manual') {
      ElMessage.error(status.message || status.error || 'IPAM 扫描失败')
    }
  }
}

const {
  scanStatus,
  monitorSupported,
  connect: connectScanMonitor,
  loadInitialStatus
} = useIPAMScanMonitor({
  onStatus: handleScanStatusChange
})

const isFreshScanStatus = (status: IPAMScanStatus | null) => {
  if (!status) {
    return false
  }
  const reference = status.updated_at || status.last_completed_at
  if (!reference) {
    return false
  }
  return Date.now() - new Date(reference).getTime() < 10 * 60 * 1000
}

const shouldShowScanStatus = computed(() => {
  return Boolean(
    scanStatus.value &&
    (
      scanStatus.value.running ||
      (
        (scanStatus.value.current_phase === 'completed' || scanStatus.value.current_phase === 'error') &&
        isFreshScanStatus(scanStatus.value)
      )
    )
  )
})

const scanSourceLabel = computed(() => {
  return scanStatus.value?.source === 'auto' ? '自动扫描' : '手动扫描'
})

const scanTypeLabel = computed(() => {
  return scanStatus.value?.scan_type === 'quick' ? '快速模式' : '全量模式'
})

const currentScanSubnetLabel = computed(() => {
  return scanStatus.value?.subnet_network || scanStatus.value?.subnet_name || '等待扫描任务'
})

const subnetProgressText = computed(() => {
  const status = scanStatus.value
  if (!status) {
    return '-'
  }
  return `${status.completed_subnets}/${status.total_subnets || 0}`
})

const quickProgressText = computed(() => {
  const status = scanStatus.value
  if (!status) {
    return '-'
  }
  return `${status.current_subnet_completed_ips}/${status.current_subnet_total_ips}，待回复 ${status.current_subnet_pending_ips}`
})

const enrichmentProgressText = computed(() => {
  const status = scanStatus.value
  if (!status) {
    return '-'
  }
  if (status.scan_type === 'quick') {
    return '本次为快速扫描，未执行识别'
  }
  if (!status.current_subnet_enrichment_total) {
    return '等待在线主机识别'
  }
  return `${status.current_subnet_enrichment_completed}/${status.current_subnet_enrichment_total}`
})

const scanProgressPercent = computed(() => {
  const status = scanStatus.value
  if (!status) {
    return 0
  }

  const totalSubnets = status.total_subnets || 1
  const completedSubnets = Math.min(status.completed_subnets || 0, totalSubnets)
  let currentSubnetProgress = 0

  if (status.current_phase === 'enrichment' && status.current_subnet_enrichment_total > 0) {
    currentSubnetProgress = status.current_subnet_enrichment_completed / status.current_subnet_enrichment_total
  } else if (status.current_subnet_total_ips > 0) {
    currentSubnetProgress = status.current_subnet_completed_ips / status.current_subnet_total_ips
  }

  const overall = ((completedSubnets + currentSubnetProgress) / totalSubnets) * 100
  return Math.max(0, Math.min(100, Math.round(overall)))
})

const isCurrentSubnetScanning = computed(() => {
  return Boolean(scanStatus.value?.running && scanStatus.value?.subnet_id === subnetId)
})

// Pagination removed - show all IPs for easier searching

// Load subnet info
const loadSubnet = async () => {
  try {
    const response = await apiClient.get(`/api/v1/ipam/subnets/${subnetId}`)
    subnet.value = {
      ...response.data,
      subnet_name: response.data.subnet_name || response.data.name || ''
    }

    // Update edit form with loaded data
    editForm.value = {
      name: response.data.name || '',
      network: response.data.network || '',
      gateway: response.data.gateway || '',
      vlan_id: response.data.vlan_id,
      dns_servers: response.data.dns_servers || '',
      description: response.data.description || ''
    }
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '加载子网信息失败')
  }
}

// Handle edit submit
const handleEditSubmit = async () => {
  try {
    await apiClient.put(`/api/v1/ipam/subnets/${subnetId}`, editForm.value)
    ElMessage.success('子网更新成功')
    showEditDialog.value = false
    await loadSubnet()
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '更新子网失败')
  }
}

// Load ALL IP addresses (no pagination - show everything)
const loadIPs = async () => {
  loading.value = true
  try {
    const params: any = {
      subnet_id: subnetId,
      skip: 0,  // Start from beginning
      limit: 10000  // Backend max limit
    }

    if (filters.value.status) params.status = filters.value.status
    if (filters.value.is_reachable !== '') params.is_reachable = filters.value.is_reachable
    if (filters.value.search) params.search = filters.value.search

    const response = await apiClient.get('/api/v1/ipam/ip-addresses', { params })
    ipAddresses.value = response.data.items || []
    ipAddresses.value.sort((a, b) => sortByIpAddress(a, b))

    // Log for debugging
    console.log(`Loaded ${ipAddresses.value.length} IP addresses for subnet ${subnetId}`)
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '加载 IP 地址失败')
  } finally {
    loading.value = false
  }
}

// Scan subnet in the background and follow progress via SSE.
const scanSubnet = async () => {
  scanning.value = true
  try {
    const response = await ipamApi.startSubnetScan(subnetId, 'full')
    if (response.mode === 'sync') {
      if (response.summary?.subnet_last_scan_at) {
        subnet.value.last_scan_at = response.summary.subnet_last_scan_at
      }
      ElMessage.success(
        response.message ||
        `同步扫描完成：${response.summary?.reachable ?? 0} 个在线，${response.summary?.unreachable ?? 0} 个离线`
      )
      await loadSubnet()
      await loadIPs()
      if (showDrawer.value && selectedIpId.value) {
        detailDrawerRefreshKey.value += 1
      }
      return
    }

    ElMessage.success(response.message || '已启动后台扫描')
  } catch (error: any) {
    if (error.response?.status === 409) {
      ElMessage.warning(error.response?.data?.detail || '当前已有扫描任务正在运行，请稍后重试')
      await loadSubnet()
    } else {
      ElMessage.error(error.response?.data?.detail || '扫描失败')
    }
  } finally {
    scanning.value = false
  }
}

// Get Last Response (CRITICAL FUNCTION!)
const getLastResponse = (ip: IPAddress): string => {
  // ONLY use last_seen_at - this is when IP actually responded
  // Do NOT fallback to last_scan_at (that's just when we scanned, not when it responded)
  const dateStr = ip.last_seen_at

  if (!dateStr) {
    return ''
  }

  try {
    const date = new Date(dateStr)
    const now = new Date()

    // Calculate difference
    const diffMs = now.getTime() - date.getTime()
    const diffMins = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMs / 3600000)
    const diffDays = Math.floor(diffMs / 86400000)

    // Today
    if (diffDays === 0) {
      if (diffMins < 1) return 'Just now'
      if (diffMins < 60) return `${diffMins} min ago`
      if (diffHours < 2) return `${diffHours} hour ago`
      return 'Today'
    }

    // Yesterday
    if (diffDays === 1) return 'Yesterday'

    // Within a week
    if (diffDays < 7) return `${diffDays} days ago`

    // Within a month
    if (diffDays < 30) {
      const weeks = Math.floor(diffDays / 7)
      return `${weeks} week${weeks > 1 ? 's' : ''} ago`
    }

    // Within a year
    if (diffDays < 365) {
      const months = Math.floor(diffDays / 30)
      return `${months} month${months > 1 ? 's' : ''} ago`
    }

    // More than a year
    const years = Math.floor(diffDays / 365)
    return `${years} year${years > 1 ? 's' : ''} ago`
  } catch {
    return 'Unknown'
  }
}

// Get color for Last Response
const getLastResponseColor = (ip: IPAddress): string => {
  const dateStr = ip.last_seen_at
  if (!dateStr) return '#909399'

  const diffMs = new Date().getTime() - new Date(dateStr).getTime()
  const diffDays = Math.floor(diffMs / 86400000)

  if (diffDays === 0) return '#67c23a'  // Green - Today
  if (diffDays <= 7) return '#409eff'   // Blue - This week
  if (diffDays <= 30) return '#e6a23c'  // Orange - This month
  return '#f56c6c'                       // Red - Long time ago
}

// Sort by last response
const sortByLastResponse = (a: IPAddress, b: IPAddress): number => {
  const dateA = new Date(a.last_seen_at || 0).getTime()
  const dateB = new Date(b.last_seen_at || 0).getTime()
  return dateB - dateA  // Most recent first
}

const ipToNumber = (ip: string): number => {
  return ip.split('.').reduce((acc, octet) => acc * 256 + Number(octet), 0)
}

const sortByIpAddress = (a: IPAddress, b: IPAddress): number => {
  return ipToNumber(a.ip_address) - ipToNumber(b.ip_address)
}

// Get status tooltip
const getStatusTooltip = (ip: IPAddress): string => {
  if (ip.is_reachable) return 'Online - IP is reachable'
  if (ip.status === 'used') return 'Offline - IP was used but not reachable'
  if (ip.status === 'reserved') return 'Reserved - IP is reserved'
  return 'Available - IP is not in use'
}

// Format datetime
const formatDateTime = (dateStr?: string | null): string => {
  if (!dateStr) return '-'
  try {
    return new Date(dateStr).toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    })
  } catch {
    return dateStr
  }
}

onMounted(() => {
  loadSubnet()
  loadIPs()
  void loadInitialStatus().then((supported) => {
    if (supported && monitorSupported.value) {
      connectScanMonitor()
    }
  })
})
</script>

<style scoped>
.subnet-detail-solarwinds {
  padding: 20px;
}

.header-bar {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.detail-scan-status {
  margin-bottom: 20px;
  padding: 16px 18px;
  border: 1px solid #d9ecff;
  border-radius: 12px;
  background: linear-gradient(135deg, #f4f9ff 0%, #ffffff 100%);
}

.detail-scan-status-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.detail-scan-title {
  font-size: 15px;
  font-weight: 700;
  color: #1f2a44;
}

.detail-scan-message {
  margin-top: 4px;
  font-size: 13px;
  color: #5c6b82;
}

.detail-scan-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 18px;
  margin-bottom: 12px;
  font-size: 13px;
  color: #22324d;
}

:deep(.el-table) {
  font-size: 13px;
}

:deep(.el-table th) {
  background-color: #f5f7fa;
  font-weight: 600;
}

.ip-address-link {
  font-family: 'SFMono-Regular', 'Cascadia Code', 'Consolas', 'Liberation Mono',
    'Courier New', monospace;
  font-size: 13px;
  font-weight: 700;
  color: #1d4ed8;
  letter-spacing: 0.02em;
  font-variant-numeric: tabular-nums;
  cursor: pointer;
  transition: color 0.2s ease;
}

.ip-address-link:hover {
  color: #1e3a8a;
  text-decoration: underline;
  text-underline-offset: 2px;
}

@media (max-width: 768px) {
  .subnet-detail-solarwinds {
    padding: 12px;
  }

  .header-bar {
    flex-direction: column;
    gap: 14px;
  }
}

</style>
