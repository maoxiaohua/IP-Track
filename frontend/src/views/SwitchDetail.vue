<template>
  <div class="switch-detail">
    <el-page-header @back="goBack">
      <template #title>
        <span style="font-size: 18px; font-weight: 600;">{{ switchInfo?.name || '交换机详情' }}</span>
      </template>
      <template #content>
        <div class="header-content" v-if="switchInfo">
          <el-tag :type="switchInfo.is_reachable ? 'success' : 'danger'">
            {{ switchInfo.is_reachable ? '在线' : '离线' }}
          </el-tag>
          <span class="switch-ip">{{ switchInfo.ip_address }}</span>
        </div>
      </template>
    </el-page-header>

    <!-- Loading State -->
    <el-card v-if="loading" class="info-card" v-loading="true" element-loading-text="加载中...">
      <div style="height: 200px;"></div>
    </el-card>

    <!-- Error State -->
    <el-card v-else-if="!switchInfo && !loading" class="info-card">
      <el-empty description="加载交换机信息失败">
        <el-button type="primary" @click="loadSwitchInfo">重新加载</el-button>
      </el-empty>
    </el-card>

    <!-- Switch Info Card -->
    <el-card v-else-if="switchInfo" class="info-card" shadow="hover">
      <template #header>
        <div class="card-header">
          <span style="font-weight: 600; font-size: 16px;">交换机信息</span>
          <el-button
            type="success"
            size="small"
            @click="refreshDeviceInfo"
            :loading="deviceInfoLoading"
            plain
          >
            <template #icon><el-icon><Refresh /></el-icon></template>
            刷新设备信息
          </el-button>
        </div>
      </template>
      <el-descriptions :column="3" border size="default">
        <el-descriptions-item label="名称" label-class-name="desc-label">
          {{ switchInfo.name }}
        </el-descriptions-item>
        <el-descriptions-item label="IP地址" label-class-name="desc-label">
          {{ switchInfo.ip_address }}
        </el-descriptions-item>
        <el-descriptions-item label="厂商" label-class-name="desc-label">
          <el-tag size="small">{{ switchInfo.vendor?.toUpperCase() || 'Unknown' }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="型号" label-class-name="desc-label">
          {{ switchInfo.model || 'Unknown' }}
        </el-descriptions-item>
        <el-descriptions-item label="角色" label-class-name="desc-label">
          <el-tag size="small" :type="getRoleType(switchInfo.role)">
            {{ getRoleLabel(switchInfo.role) }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="优先级" label-class-name="desc-label">
          <el-tag size="small" :type="getPriorityType(switchInfo.priority)">
            {{ switchInfo.priority }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="响应时间" label-class-name="desc-label">
          <span v-if="switchInfo.response_time_ms" style="color: #67c23a; font-weight: 500;">
            {{ switchInfo.response_time_ms.toFixed(2) }} ms
          </span>
          <span v-else style="color: #909399;">-</span>
        </el-descriptions-item>
        <el-descriptions-item label="最后检查" label-class-name="desc-label">
          {{ switchInfo.last_check_at ? formatDateTime(switchInfo.last_check_at) : '-' }}
        </el-descriptions-item>
        <el-descriptions-item label="SNMP" label-class-name="desc-label">
          <el-tag :type="switchInfo.snmp_enabled ? 'success' : 'info'" size="small">
            {{ switchInfo.snmp_enabled ? '已启用' : '未启用' }}
          </el-tag>
        </el-descriptions-item>
      </el-descriptions>
    </el-card>

    <!-- Data Tabs -->
    <el-tabs v-model="activeTab" class="data-tabs">
      <el-tab-pane label="ARP 表" name="arp">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span style="font-weight: 600;">ARP 表 ({{ arpData.length }} 条记录)</span>
              <el-button type="primary" size="small" @click="collectArpData" :loading="arpLoading" plain>
                <template #icon><el-icon><Refresh /></el-icon></template>
                立即收集
              </el-button>
            </div>
          </template>

          <el-alert
            v-if="arpData.length === 0 && !arpLoading"
            title="暂无数据"
            type="info"
            description="系统每10分钟自动采集一次ARP数据，请稍后刷新查看。"
            :closable="false"
            show-icon
            style="margin-bottom: 20px;"
          />

          <el-table 
            v-if="arpData.length > 0" 
            :data="filteredArpData" 
            stripe 
            style="width: 100%" 
            :default-sort="{ prop: 'last_seen', order: 'descending' }"
            border
          >
            <el-table-column prop="ip_address" label="IP 地址" width="150" sortable>
              <template #default="{ row }">
                <el-link type="primary" @click="searchIP(row.ip_address)" underline="never">
                  {{ row.ip_address }}
                </el-link>
              </template>
            </el-table-column>
            <el-table-column prop="mac_address" label="MAC 地址" width="180" sortable />
            <el-table-column prop="vlan_id" label="VLAN" width="100" sortable align="center" />
            <el-table-column prop="interface" label="接口" width="150" sortable />
            <el-table-column prop="age_seconds" label="Age (秒)" width="120" sortable align="center" />
            <el-table-column prop="last_seen" label="最后发现时间" sortable min-width="180">
              <template #default="{ row }">
                {{ formatDateTime(row.last_seen) }}
              </template>
            </el-table-column>
          </el-table>

          <el-pagination
            v-if="arpData.length > pageSize"
            v-model:current-page="arpCurrentPage"
            :page-size="pageSize"
            layout="total, prev, pager, next"
            :total="arpData.length"
            style="margin-top: 20px; justify-content: center"
          />
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="MAC 地址表" name="mac">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span style="font-weight: 600;">MAC 地址表 ({{ macData.length }} 条记录)</span>
              <el-button type="primary" size="small" @click="collectMacData" :loading="macLoading" plain>
                <template #icon><el-icon><Refresh /></el-icon></template>
                立即收集
              </el-button>
            </div>
          </template>

          <el-alert
            v-if="macData.length === 0 && !macLoading"
            title="暂无数据"
            type="info"
            description="系统每10分钟自动采集一次MAC地址表数据，请稍后刷新查看。"
            :closable="false"
            show-icon
            style="margin-bottom: 20px;"
          />

          <el-table 
            v-if="macData.length > 0" 
            :data="filteredMacData" 
            stripe 
            style="width: 100%" 
            :default-sort="{ prop: 'last_seen', order: 'descending' }"
            border
          >
            <el-table-column prop="mac_address" label="MAC 地址" width="180" sortable />
            <el-table-column prop="port_name" label="端口" width="150" sortable />
            <el-table-column prop="vlan_id" label="VLAN" width="100" sortable align="center" />
            <el-table-column prop="is_dynamic" label="类型" width="100" align="center">
              <template #default="{ row }">
                <el-tag :type="row.is_dynamic ? 'success' : 'warning'" size="small">
                  {{ row.is_dynamic ? '动态' : '静态' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="last_seen" label="最后发现时间" sortable min-width="180">
              <template #default="{ row }">
                {{ formatDateTime(row.last_seen) }}
              </template>
            </el-table-column>
          </el-table>

          <el-pagination
            v-if="macData.length > pageSize"
            v-model:current-page="macCurrentPage"
            :page-size="pageSize"
            layout="total, prev, pager, next"
            :total="macData.length"
            style="margin-top: 20px; justify-content: center"
          />
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="光模块" name="optical">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span style="font-weight: 600;">光模块信息 ({{ opticalData.length }} 个模块)</span>
              <el-button type="primary" size="small" @click="collectOpticalData" :loading="opticalLoading" plain>
                <template #icon><el-icon><Refresh /></el-icon></template>
                立即收集
              </el-button>
            </div>
          </template>

          <el-alert
            v-if="opticalData.length === 0 && !opticalLoading"
            title="暂无数据"
            type="info"
            description="点击【立即收集】按钮通过SNMP采集光模块信息（需要SNMP配置正确）。"
            :closable="false"
            show-icon
            style="margin-bottom: 20px;"
          />

          <el-table
            v-if="opticalData.length > 0"
            :data="filteredOpticalData"
            stripe
            style="width: 100%"
            :default-sort="{ prop: 'port_name', order: 'ascending' }"
            border
          >
            <el-table-column prop="port_name" label="端口" width="150" sortable />
            <el-table-column prop="module_type" label="模块类型" width="120" sortable>
              <template #default="{ row }">
                <el-tag
                  :type="getModuleTagType(row.module_type)"
                  size="small"
                >
                  {{ row.module_type || 'Unknown' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="vendor" label="厂商" width="150" sortable show-overflow-tooltip />
            <el-table-column prop="model" label="型号" width="180" sortable show-overflow-tooltip />
            <el-table-column prop="serial_number" label="序列号" width="180" sortable show-overflow-tooltip />
            <el-table-column prop="speed_gbps" label="速率" width="100" sortable align="center">
              <template #default="{ row }">
                <span v-if="row.speed_gbps">{{ row.speed_gbps }} Gbps</span>
                <span v-else style="color: #999;">-</span>
              </template>
            </el-table-column>
            <el-table-column prop="last_seen" label="采集时间" sortable min-width="180">
              <template #default="{ row }">
                {{ formatDateTime(row.last_seen) }}
              </template>
            </el-table-column>
          </el-table>

          <el-pagination
            v-if="opticalData.length > pageSize"
            v-model:current-page="opticalCurrentPage"
            :page-size="pageSize"
            layout="total, prev, pager, next"
            :total="opticalData.length"
            style="margin-top: 20px; justify-content: center"
          />
        </el-card>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import apiClient from '@/api'
import { switchesApi } from '@/api/switches'

const route = useRoute()
const router = useRouter()

const switchId = ref(Number(route.params.id))
const switchInfo = ref<any>(null)
const activeTab = ref('arp')
const loading = ref(true)
const deviceInfoLoading = ref(false)

const arpData = ref<any[]>([])
const macData = ref<any[]>([])
const opticalData = ref<any[]>([])
const arpLoading = ref(false)
const macLoading = ref(false)
const opticalLoading = ref(false)

const arpCurrentPage = ref(1)
const macCurrentPage = ref(1)
const opticalCurrentPage = ref(1)
const pageSize = ref(50)

const filteredArpData = computed(() => {
  const start = (arpCurrentPage.value - 1) * pageSize.value
  const end = start + pageSize.value
  return arpData.value.slice(start, end)
})

const filteredMacData = computed(() => {
  const start = (macCurrentPage.value - 1) * pageSize.value
  const end = start + pageSize.value
  return macData.value.slice(start, end)
})

const filteredOpticalData = computed(() => {
  const start = (opticalCurrentPage.value - 1) * pageSize.value
  const end = start + pageSize.value
  return opticalData.value.slice(start, end)
})

const goBack = () => {
  router.push('/switches')
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

const getRoleType = (role: string) => {
  const types: Record<string, any> = {
    core: 'danger',
    aggregation: 'warning',
    access: 'info'
  }
  return types[role] || 'info'
}

const getRoleLabel = (role: string) => {
  const labels: Record<string, string> = {
    core: 'Core',
    aggregation: 'Aggregation',
    access: 'Access'
  }
  return labels[role] || role
}

const getModuleTagType = (moduleType: string) => {
  if (!moduleType) return 'info'
  if (moduleType === 'QSFP28') return 'danger'
  if (moduleType === 'QSFP+' || moduleType === 'QSFP') return 'warning'
  return 'success'
}

const getPriorityType = (priority: number) => {
  if (priority <= 10) return 'danger'
  if (priority <= 50) return 'warning'
  return 'info'
}

const searchIP = (ip: string) => {
  router.push(`/?ip=${ip}`)
}

const loadSwitchInfo = async () => {
  loading.value = true
  try {
    const response = await apiClient.get(`/api/v1/switches/${switchId.value}`)
    switchInfo.value = response.data
    console.log('Switch info loaded:', response.data)
  } catch (error: any) {
    console.error('Failed to load switch info:', error)
    ElMessage.error(error.response?.data?.detail || '加载交换机信息失败')
  } finally {
    loading.value = false
  }
}

const loadArpData = async () => {
  arpLoading.value = true
  try {
    console.log(`正在加载交换机 ${switchId.value} 的ARP表...`)
    const response = await apiClient.get(`/api/v1/switches/${switchId.value}/arp`)
    console.log('ARP表响应:', response.data)
    arpData.value = response.data.entries || []
    if (arpData.value.length > 0) {
      ElMessage.success(`刷新成功：加载了 ${arpData.value.length} 条 ARP 记录`)
    } else {
      ElMessage.info('刷新成功：当前暂无 ARP 记录，系统每10分钟自动采集一次数据')
    }
  } catch (error: any) {
    console.error('Failed to load ARP data:', error)
    ElMessage.error(error.response?.data?.detail || '加载ARP表失败')
  } finally {
    arpLoading.value = false
  }
}

const loadMacData = async () => {
  macLoading.value = true
  try {
    console.log(`正在加载交换机 ${switchId.value} 的MAC表...`)
    const response = await apiClient.get(`/api/v1/switches/${switchId.value}/mac`)
    console.log('MAC表响应:', response.data)
    macData.value = response.data.entries || []
    if (macData.value.length > 0) {
      ElMessage.success(`刷新成功：加载了 ${macData.value.length} 条 MAC 记录`)
    } else {
      ElMessage.info('刷新成功：当前暂无 MAC 记录，系统每10分钟自动采集一次数据')
    }
  } catch (error: any) {
    console.error('Failed to load MAC data:', error)
    ElMessage.error(error.response?.data?.detail || '加载MAC表失败')
  } finally {
    macLoading.value = false
  }
}

// Manual collection functions
const collectArpData = async () => {
  arpLoading.value = true
  try {
    ElMessage.info('正在从交换机实时收集 ARP 表数据，请稍候...')
    const response = await switchesApi.collectArp(switchId.value)
    console.log('ARP collection response:', response)

    if (response.total_entries > 0) {
      ElMessage.success(`✅ ${response.message}`)
      // Reload data from database
      await loadArpData()
    } else {
      ElMessage.warning(response.message || '未能收集到 ARP 数据')
    }
  } catch (error: any) {
    console.error('Failed to collect ARP data:', error)
    ElMessage.error(error.response?.data?.detail || '收集 ARP 表失败')
  } finally {
    arpLoading.value = false
  }
}

const collectMacData = async () => {
  macLoading.value = true
  try {
    ElMessage.info('正在从交换机实时收集 MAC 地址表数据，请稍候...')
    const response = await switchesApi.collectMac(switchId.value)
    console.log('MAC collection response:', response)

    if (response.total_entries > 0) {
      ElMessage.success(`✅ ${response.message}`)
      // Reload data from database
      await loadMacData()
    } else {
      ElMessage.warning(response.message || '未能收集到 MAC 数据')
    }
  } catch (error: any) {
    console.error('Failed to collect MAC data:', error)
    ElMessage.error(error.response?.data?.detail || '收集 MAC 地址表失败')
  } finally {
    macLoading.value = false
  }
}

const loadOpticalData = async () => {
  opticalLoading.value = true
  try {
    const response = await switchesApi.getOpticalModules(switchId.value)
    opticalData.value = response.entries || []
    console.log('Loaded optical modules:', opticalData.value.length)
  } catch (error: any) {
    console.error('Failed to load optical modules:', error)
    if (error.response?.status !== 404) {
      ElMessage.error('加载光模块信息失败')
    }
  } finally {
    opticalLoading.value = false
  }
}

const collectOpticalData = async () => {
  opticalLoading.value = true
  try {
    ElMessage.info('正在从交换机通过 SNMP 收集光模块信息，请稍候...')
    const response = await switchesApi.collectOpticalModules(switchId.value)
    console.log('Optical module collection response:', response)

    if (response.total_modules > 0) {
      ElMessage.success(`✅ ${response.message}`)
      // Reload data from database
      await loadOpticalData()
    } else {
      ElMessage.warning(response.message || '未能收集到光模块信息')
    }
  } catch (error: any) {
    console.error('Failed to collect optical modules:', error)
    ElMessage.error(error.response?.data?.detail || '收集光模块信息失败')
  } finally {
    opticalLoading.value = false
  }
}

const refreshDeviceInfo = async () => {
  deviceInfoLoading.value = true
  try {
    ElMessage.info('正在从交换机实时获取设备信息，请稍候...')
    const response = await switchesApi.collectDeviceInfo(switchId.value)
    console.log('Device info collection response:', response)

    if (response.success) {
      if (response.updated_fields.length > 0) {
        ElMessage.success(`✅ ${response.message}`)
        // Reload switch info
        await loadSwitchInfo()
      } else {
        ElMessage.info(response.message || '设备信息无变化')
      }
    } else {
      ElMessage.warning(response.message || '未能获取设备信息')
    }
  } catch (error: any) {
    console.error('Failed to collect device info:', error)
    ElMessage.error(error.response?.data?.detail || '获取设备信息失败')
  } finally {
    deviceInfoLoading.value = false
  }
}

onMounted(async () => {
  await loadSwitchInfo()
  await loadArpData()
  await loadMacData()
  await loadOpticalData()
})
</script>

<style scoped>
.switch-detail {
  padding: 20px;
  background-color: #f5f7fa;
  min-height: 100vh;
}

.header-content {
  display: flex;
  align-items: center;
  gap: 10px;
}

.switch-ip {
  font-size: 14px;
  color: #606266;
  font-weight: 500;
}

.info-card {
  margin: 20px 0;
  border-radius: 8px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.data-tabs {
  margin-top: 20px;
}

:deep(.desc-label) {
  font-weight: 600;
  background-color: #fafafa;
}

:deep(.el-descriptions__body .el-descriptions__table) {
  table-layout: fixed;
}

:deep(.el-card__header) {
  background-color: #fafafa;
  border-bottom: 1px solid #ebeef5;
}

:deep(.el-button.is-plain) {
  background-color: #fff;
}

:deep(.el-button.is-plain:hover) {
  background-color: #ecf5ff;
  border-color: #409eff;
  color: #409eff;
}
</style>
