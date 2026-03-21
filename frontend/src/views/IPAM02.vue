<template>
  <div class="ipam-grid-view">
    <!-- Header Section -->
    <el-card class="header-card">
      <h2 style="margin: 0 0 20px 0">IPAM 网格视图 (Grid View)</h2>

      <!-- Subnet Selector -->
      <el-row :gutter="20" style="margin-bottom: 20px">
        <el-col :span="12">
          <el-select
            v-model="selectedSubnetId"
            placeholder="选择子网"
            filterable
            @change="onSubnetChange"
            style="width: 100%"
            size="large"
          >
            <el-option
              v-for="subnet in subnets"
              :key="subnet.subnet_id"
              :label="`${subnet.network} - ${subnet.subnet_name} (利用率: ${subnet.utilization_percent || 0}%)`"
              :value="subnet.subnet_id"
            />
          </el-select>
        </el-col>
        <el-col :span="12">
          <div style="display: flex; gap: 10px">
            <el-button type="success" @click="scanSubnet" :loading="scanning" :disabled="!selectedSubnetId">
              <el-icon><Refresh /></el-icon>
              扫描子网
            </el-button>
            <el-button @click="loadCurrentSubnet" :disabled="!selectedSubnetId">
              <el-icon><Refresh /></el-icon>
              刷新
            </el-button>
          </div>
        </el-col>
      </el-row>

      <!-- Statistics Row -->
      <el-row v-if="selectedSubnetId && statistics" :gutter="20">
        <el-col :span="4">
          <el-statistic title="总 IP 数" :value="statistics.total_ips || 0" />
        </el-col>
        <el-col :span="4">
          <el-statistic title="已使用" :value="statistics.used_ips || 0">
            <template #prefix>
              <el-icon style="color: #409eff"><Check /></el-icon>
            </template>
          </el-statistic>
        </el-col>
        <el-col :span="4">
          <el-statistic title="可用" :value="statistics.available_ips || 0">
            <template #prefix>
              <el-icon style="color: #67c23a"><CircleClose /></el-icon>
            </template>
          </el-statistic>
        </el-col>
        <el-col :span="4">
          <el-statistic title="在线" :value="statistics.reachable_count || 0">
            <template #prefix>
              <el-icon style="color: #67c23a"><Connection /></el-icon>
            </template>
          </el-statistic>
        </el-col>
        <el-col :span="4">
          <el-statistic title="离线" :value="statistics.offline_ips || 0">
            <template #prefix>
              <el-icon style="color: #f56c6c"><Close /></el-icon>
            </template>
          </el-statistic>
        </el-col>
        <el-col :span="4">
          <el-statistic title="利用率" :value="statistics.utilization_percent || 0" suffix="%" />
        </el-col>
      </el-row>
    </el-card>

    <!-- Legend -->
    <el-card v-if="selectedSubnetId" class="legend-card" style="margin-top: 20px">
      <div class="legend">
        <div class="legend-item">
          <div class="legend-box available"></div>
          <span>可用 (Available)</span>
        </div>
        <div class="legend-item">
          <div class="legend-box used"></div>
          <span>已使用 (Used)</span>
        </div>
        <div class="legend-item">
          <div class="legend-box reserved"></div>
          <span>保留 (Reserved)</span>
        </div>
        <div class="legend-item">
          <div class="legend-box offline"></div>
          <span>离线 (Offline)</span>
        </div>
      </div>
    </el-card>

    <!-- IP Address Grid -->
    <el-card v-if="selectedSubnetId" class="grid-card" v-loading="loading" style="margin-top: 20px">
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center">
          <h3 style="margin: 0">{{ currentSubnet?.network || 'IP 地址网格' }}</h3>
          <span style="color: #909399; font-size: 14px">
            点击方块查看详情 | 鼠标悬停显示信息
          </span>
        </div>
      </template>

      <div v-if="ipAddresses.length > 0" :class="getGridClass()" class="ip-grid">
        <el-tooltip
          v-for="ip in ipAddresses"
          :key="ip.id"
          :content="getTooltipContent(ip)"
          placement="top"
          :show-after="200"
        >
          <div
            :class="['ip-cell', getIPStatusClass(ip)]"
            @click="showIPDetail(ip)"
          >
            <div class="ip-address">{{ getLastOctet(ip.ip_address) }}</div>
            <div v-if="ip.is_reachable" class="status-indicator online"></div>
            <div v-else-if="ip.status === 'used'" class="status-indicator offline"></div>
          </div>
        </el-tooltip>
      </div>

      <el-empty v-else description="请选择子网并扫描以查看 IP 地址" />
    </el-card>

    <!-- IP Detail Drawer -->
    <el-drawer
      v-model="drawerVisible"
      :title="`IP 地址详情 - ${selectedIP?.ip_address || ''}`"
      size="500px"
      direction="rtl"
    >
      <div v-if="selectedIP" class="ip-detail">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="IP 地址">
            <el-tag type="primary" size="large">{{ selectedIP.ip_address }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="getStatusTagType(selectedIP.status)" size="large">
              {{ getStatusText(selectedIP.status) }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="可达性">
            <el-tag :type="selectedIP.is_reachable ? 'success' : 'danger'" size="large">
              {{ selectedIP.is_reachable ? '在线' : '离线' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="响应时间" v-if="selectedIP.last_response_time">
            {{ selectedIP.last_response_time }}
          </el-descriptions-item>
          <el-descriptions-item label="主机名" v-if="selectedIP.hostname">
            {{ selectedIP.hostname }}
          </el-descriptions-item>
          <el-descriptions-item label="DNS 名称" v-if="selectedIP.dns_name">
            {{ selectedIP.dns_name }}
          </el-descriptions-item>
          <el-descriptions-item label="系统名称" v-if="selectedIP.system_name">
            {{ selectedIP.system_name }}
          </el-descriptions-item>
          <el-descriptions-item label="联系人" v-if="selectedIP.contact">
            {{ selectedIP.contact }}
          </el-descriptions-item>
          <el-descriptions-item label="位置" v-if="selectedIP.location">
            {{ selectedIP.location }}
          </el-descriptions-item>
          <el-descriptions-item label="机器类型" v-if="selectedIP.machine_type">
            {{ selectedIP.machine_type }}
          </el-descriptions-item>
          <el-descriptions-item label="上次启动时间" v-if="selectedIP.last_boot_time">
            {{ selectedIP.last_boot_time }}
          </el-descriptions-item>
          <el-descriptions-item label="描述" v-if="selectedIP.description">
            {{ selectedIP.description }}
          </el-descriptions-item>
          <el-descriptions-item label="上次扫描时间" v-if="selectedIP.last_scanned_at">
            {{ formatDateTime(selectedIP.last_scanned_at) }}
          </el-descriptions-item>
        </el-descriptions>

        <div style="margin-top: 20px">
          <el-button type="primary" @click="drawerVisible = false">关闭</el-button>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Check, CircleClose, Connection, Close, Refresh } from '@element-plus/icons-vue'
import apiClient from '@/api/index'

// Types
interface Subnet {
  subnet_id: number
  subnet_name: string
  network: string
  vlan_id?: number
  gateway?: string
  utilization_percent?: number
}

interface IPAddress {
  id: number
  ip_address: string
  status: string
  is_reachable: boolean
  last_response_time?: string
  hostname?: string
  dns_name?: string
  system_name?: string
  contact?: string
  location?: string
  machine_type?: string
  last_boot_time?: string
  description?: string
  last_scanned_at?: string
}

interface Statistics {
  total_ips: number
  used_ips: number
  available_ips: number
  reserved_ips: number
  reachable_count: number
  offline_ips: number
  utilization_percent: number
}

// State
const subnets = ref<Subnet[]>([])
const selectedSubnetId = ref<number | null>(null)
const currentSubnet = ref<Subnet | null>(null)
const ipAddresses = ref<IPAddress[]>([])
const statistics = ref<Statistics | null>(null)
const loading = ref(false)
const scanning = ref(false)
const drawerVisible = ref(false)
const selectedIP = ref<IPAddress | null>(null)

// Load subnets on mount
onMounted(async () => {
  await loadSubnets()
})

// Load all subnets
const loadSubnets = async () => {
  try {
    const response = await apiClient.get('/api/v1/ipam/dashboard')
    subnets.value = response.data.subnets || []

    console.log('Loaded subnets:', subnets.value.length)

    // Sort by utilization descending
    subnets.value.sort((a, b) => {
      const aUtil = a.utilization_percent ?? 0
      const bUtil = b.utilization_percent ?? 0
      return bUtil - aUtil
    })
  } catch (error: any) {
    console.error('Failed to load subnets:', error)
    ElMessage.error(error.response?.data?.detail || '加载子网失败')
  }
}

// Handle subnet change
const onSubnetChange = async () => {
  console.log('Subnet changed to:', selectedSubnetId.value)
  if (!selectedSubnetId.value) return
  await loadCurrentSubnet()
}

// Load current subnet and IPs
const loadCurrentSubnet = async () => {
  if (!selectedSubnetId.value) return

  loading.value = true
  try {
    // Load subnet details
    const subnetResponse = await apiClient.get(`/api/v1/ipam/subnets/${selectedSubnetId.value}`)
    currentSubnet.value = subnetResponse.data

    // Load IPs
    const ipResponse = await apiClient.get('/api/v1/ipam/ip-addresses', {
      params: {
        subnet_id: selectedSubnetId.value,
        limit: 10000  // Large limit to get all IPs
      }
    })
    ipAddresses.value = ipResponse.data.items || []

    // Sort IPs by IP address (numeric sort)
    ipAddresses.value.sort((a, b) => {
      const aNum = ipToNumber(a.ip_address)
      const bNum = ipToNumber(b.ip_address)
      return aNum - bNum
    })

    // Load statistics
    const statsResponse = await apiClient.get(`/api/v1/ipam/subnets/${selectedSubnetId.value}/statistics`)
    statistics.value = statsResponse.data
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '加载子网数据失败')
  } finally {
    loading.value = false
  }
}

// Scan subnet
const scanSubnet = async () => {
  if (!selectedSubnetId.value) return

  scanning.value = true
  try {
    await apiClient.post('/api/v1/ipam/scan', {
      subnet_id: selectedSubnetId.value,
      scan_type: 'full'
    })
    ElMessage.success('子网扫描已启动，请稍后刷新查看结果')

    // Reload after 5 seconds
    setTimeout(() => {
      loadCurrentSubnet()
    }, 5000)
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '扫描子网失败')
  } finally {
    scanning.value = false
  }
}

// Convert IP address to number for sorting
const ipToNumber = (ip: string): number => {
  const parts = ip.split('.').map(Number)
  return (parts[0] << 24) + (parts[1] << 16) + (parts[2] << 8) + parts[3]
}

// Get last octet of IP address for display in grid
const getLastOctet = (ip: string): string => {
  const parts = ip.split('.')
  return parts[parts.length - 1]
}

// Get IP status class for color coding
const getIPStatusClass = (ip: IPAddress): string => {
  if (!ip.is_reachable && ip.status === 'used') {
    return 'offline'
  }
  return ip.status || 'available'
}

// Get tooltip content
const getTooltipContent = (ip: IPAddress): string => {
  let content = `IP: ${ip.ip_address}\n`
  content += `状态: ${getStatusText(ip.status)}\n`
  content += `可达性: ${ip.is_reachable ? '在线' : '离线'}\n`

  if (ip.hostname) content += `主机名: ${ip.hostname}\n`
  if (ip.dns_name) content += `DNS: ${ip.dns_name}\n`
  if (ip.last_response_time) content += `响应时间: ${ip.last_response_time}\n`

  return content.trim()
}

// Show IP detail drawer
const showIPDetail = (ip: IPAddress) => {
  selectedIP.value = ip
  drawerVisible.value = true
}

// Get status text
const getStatusText = (status: string): string => {
  const statusMap: Record<string, string> = {
    'available': '可用',
    'used': '已使用',
    'reserved': '保留',
    'offline': '离线'
  }
  return statusMap[status] || status
}

// Get status tag type
const getStatusTagType = (status: string): string => {
  const typeMap: Record<string, string> = {
    'available': 'success',
    'used': 'primary',
    'reserved': 'danger',
    'offline': 'info'
  }
  return typeMap[status] || 'info'
}

// Get utilization tag type
const getUtilizationTagType = (utilization: number): string => {
  if (utilization >= 90) return 'danger'
  if (utilization >= 70) return 'warning'
  if (utilization >= 50) return 'primary'
  return 'success'
}

// Get grid class based on subnet size
const getGridClass = (): string => {
  const totalIPs = ipAddresses.value.length

  // /24 subnet (256 IPs) - 16x16 grid
  if (totalIPs <= 256) return 'grid-16'

  // /23 subnet (512 IPs) - 32x16 grid
  if (totalIPs <= 512) return 'grid-32'

  // /22 subnet (1024 IPs) - 32x32 grid
  return 'grid-32'
}

// Format datetime
const formatDateTime = (dateStr?: string): string => {
  if (!dateStr) return '-'
  try {
    return new Date(dateStr).toLocaleString('zh-CN')
  } catch {
    return dateStr
  }
}
</script>

<style scoped>
.ipam-grid-view {
  padding: 20px;
}

.header-card, .legend-card, .grid-card {
  margin-bottom: 20px;
}

/* Legend Styles */
.legend {
  display: flex;
  gap: 30px;
  justify-content: center;
  align-items: center;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.legend-box {
  width: 24px;
  height: 24px;
  border-radius: 4px;
  border: 2px solid #dcdfe6;
}

.legend-box.available {
  background-color: #67c23a;
}

.legend-box.used {
  background-color: #409eff;
}

.legend-box.reserved {
  background-color: #f56c6c;
}

.legend-box.offline {
  background-color: #909399;
}

/* IP Grid Styles */
.ip-grid {
  display: grid;
  gap: 4px;
  padding: 10px;
}

/* 16x16 grid for /24 subnets */
.grid-16 {
  grid-template-columns: repeat(16, 1fr);
}

/* 32x16 grid for larger subnets */
.grid-32 {
  grid-template-columns: repeat(32, 1fr);
}

.ip-cell {
  position: relative;
  aspect-ratio: 1;
  border-radius: 4px;
  border: 1px solid #dcdfe6;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.2s;
  font-size: 11px;
  font-weight: 500;
  color: white;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.3);
}

.ip-cell:hover {
  transform: scale(1.2);
  z-index: 10;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
}

/* Color coding based on status */
.ip-cell.available {
  background-color: #67c23a;
}

.ip-cell.used {
  background-color: #409eff;
}

.ip-cell.reserved {
  background-color: #f56c6c;
}

.ip-cell.offline {
  background-color: #909399;
}

/* Status indicator (small dot) */
.status-indicator {
  position: absolute;
  top: 2px;
  right: 2px;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  border: 1px solid white;
}

.status-indicator.online {
  background-color: #67c23a;
}

.status-indicator.offline {
  background-color: #f56c6c;
}

.ip-address {
  font-size: 11px;
  line-height: 1;
}

/* IP Detail Drawer */
.ip-detail {
  padding: 20px;
}
</style>
