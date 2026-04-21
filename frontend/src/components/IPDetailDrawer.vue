<template>
  <el-drawer
    v-model="visible"
    title="IP Address Details"
    size="600px"
    direction="rtl"
    :before-close="handleClose"
  >
    <div v-loading="loading" class="ip-detail-drawer">
      <!-- Basic Info - Always Expanded -->
      <el-card class="info-card" shadow="never">
        <template #header>
          <div class="card-header">
            <h3>Basic Information</h3>
            <el-tag :type="getStatusType(ipDetail.status)" size="large">
              {{ ipDetail.status?.toUpperCase() }}
            </el-tag>
          </div>
        </template>

        <el-descriptions :column="1" border>
          <el-descriptions-item label="IP Address">
            <span style="font-family: monospace; font-weight: 600; font-size: 16px">
              {{ ipDetail.ip_address }}
            </span>
          </el-descriptions-item>
          <el-descriptions-item label="Status">
            <el-icon v-if="ipDetail.is_reachable" style="color: #67c23a" :size="18">
              <CircleCheckFilled />
            </el-icon>
            <el-icon v-else style="color: #f56c6c" :size="18">
              <CircleCloseFilled />
            </el-icon>
            <span style="margin-left: 8px">
              {{ ipDetail.is_reachable ? 'Online' : 'Offline' }}
            </span>
          </el-descriptions-item>
          <el-descriptions-item label="MAC Address">
            {{ ipDetail.mac_address || '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="Hostname">
            {{ ipDetail.hostname || ipDetail.dns_name || ipDetail.system_name || '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="Response Time">
            {{ ipDetail.response_time ? `${ipDetail.response_time} ms` : '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="Last Seen">
            {{ ipDetail.last_seen_at ? formatDateTime(ipDetail.last_seen_at) : 'Never' }}
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <!-- Network Location - Collapsible -->
      <el-collapse v-model="activeCollapse" class="detail-collapse">
        <el-collapse-item name="location">
          <template #title>
            <div class="collapse-title">
              <el-icon><Connection /></el-icon>
              <span>Network Location</span>
            </div>
          </template>
          <el-descriptions :column="1" border>
            <el-descriptions-item label="Switch">
              <router-link
                v-if="ipDetail.switch_id"
                :to="`/switches/${ipDetail.switch_id}`"
                style="color: #409eff; text-decoration: none"
              >
                {{ ipDetail.switch_name || `Switch #${ipDetail.switch_id}` }}
              </router-link>
              <span v-else style="color: #909399">-</span>
            </el-descriptions-item>
            <el-descriptions-item label="Port">
              <el-tag v-if="ipDetail.switch_port" type="success">
                {{ ipDetail.switch_port }}
              </el-tag>
              <span v-else style="color: #909399">-</span>
            </el-descriptions-item>
            <el-descriptions-item label="VLAN">
              {{ ipDetail.vlan_id || '-' }}
            </el-descriptions-item>
          </el-descriptions>
        </el-collapse-item>

        <!-- Device Information - Collapsible -->
        <el-collapse-item name="device">
          <template #title>
            <div class="collapse-title">
              <el-icon><Monitor /></el-icon>
              <span>Device Information</span>
            </div>
          </template>
          <el-descriptions :column="1" border>
            <el-descriptions-item label="System Name">
              {{ ipDetail.system_name || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="Machine Type">
              {{ ipDetail.machine_type || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="Vendor">
              {{ ipDetail.vendor || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="OS Type">
              <el-tag v-if="ipDetail.os_type" :type="getOsTagType(ipDetail.os_type)">
                {{ ipDetail.os_type }}
              </el-tag>
              <span v-else style="color: #909399">-</span>
            </el-descriptions-item>
            <el-descriptions-item label="OS Name">
              {{ ipDetail.os_name || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="OS Version">
              {{ ipDetail.os_version || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="Last Boot">
              {{ ipDetail.last_boot_time ? formatDateTime(ipDetail.last_boot_time) : '-' }}
            </el-descriptions-item>
          </el-descriptions>
        </el-collapse-item>

        <!-- Scan History - Collapsible -->
        <el-collapse-item name="history">
          <template #title>
            <div class="collapse-title">
              <el-icon><Clock /></el-icon>
              <span>Scan History (Last 10)</span>
            </div>
          </template>
          <div v-loading="historyLoading">
            <el-empty v-if="!scanHistory.length" description="No scan history" />
            <el-timeline v-else>
              <el-timeline-item
                v-for="record in scanHistory"
                :key="record.id"
                :timestamp="formatDateTime(record.scanned_at)"
                placement="top"
              >
                <el-card shadow="hover" class="history-card">
                  <div class="history-item">
                    <div class="history-status">
                      <el-icon v-if="record.is_reachable" style="color: #67c23a" :size="16">
                        <CircleCheckFilled />
                      </el-icon>
                      <el-icon v-else style="color: #f56c6c" :size="16">
                        <CircleCloseFilled />
                      </el-icon>
                      <span style="margin-left: 4px">
                        {{ record.is_reachable ? 'Online' : 'Offline' }}
                      </span>
                      <span v-if="record.response_time" style="margin-left: 8px; color: #909399">
                        {{ record.response_time }}ms
                      </span>
                    </div>

                    <!-- Change badges -->
                    <div v-if="hasChanges(record)" class="history-changes">
                      <el-tag v-if="record.status_changed" type="warning" size="small">
                        Status Changed
                      </el-tag>
                      <el-tag v-if="record.mac_changed" type="warning" size="small">
                        MAC Changed
                      </el-tag>
                      <el-tag v-if="record.switch_changed" type="danger" size="small">
                        Switch Moved
                      </el-tag>
                      <el-tag v-if="record.port_changed" type="danger" size="small">
                        Port Changed
                      </el-tag>
                      <el-tag v-if="record.hostname_changed" type="info" size="small">
                        Hostname Changed
                      </el-tag>
                    </div>

                    <!-- Details -->
                    <div class="history-details">
                      <div v-if="record.mac_address">
                        <span style="color: #909399">MAC:</span> {{ record.mac_address }}
                      </div>
                      <div v-if="record.switch_port">
                        <span style="color: #909399">Port:</span> {{ record.switch_port }}
                      </div>
                      <div v-if="record.hostname">
                        <span style="color: #909399">Hostname:</span> {{ record.hostname }}
                      </div>
                    </div>
                  </div>
                </el-card>
              </el-timeline-item>
            </el-timeline>
          </div>
        </el-collapse-item>
      </el-collapse>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { ipamApi } from '@/api/ipam'
import type { IPAddressDetail, IPScanHistory } from '@/api/ipam'

interface Props {
  modelValue: boolean
  ipId: number | null
}

const props = defineProps<Props>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const visible = ref(false)
const loading = ref(false)
const historyLoading = ref(false)
const ipDetail = ref<IPAddressDetail>({} as IPAddressDetail)
const scanHistory = ref<IPScanHistory[]>([])
const activeCollapse = ref<string[]>(['location'])

watch(() => props.modelValue, (val) => {
  visible.value = val
  if (val && props.ipId) {
    loadIPDetail()
    loadScanHistory()
  }
})

watch(visible, (val) => {
  emit('update:modelValue', val)
})

const loadIPDetail = async () => {
  if (!props.ipId) return
  loading.value = true
  try {
    ipDetail.value = await ipamApi.getIPAddress(props.ipId)
  } catch (error) {
    console.error('Failed to load IP details:', error)
  } finally {
    loading.value = false
  }
}

const loadScanHistory = async () => {
  if (!props.ipId) return
  historyLoading.value = true
  try {
    scanHistory.value = await ipamApi.getIPScanHistory(props.ipId)
  } catch (error) {
    console.error('Failed to load scan history:', error)
  } finally {
    historyLoading.value = false
  }
}

const handleClose = () => {
  visible.value = false
}

const formatDateTime = (dateString: string) => {
  const date = new Date(dateString)
  return date.toLocaleString()
}

const getStatusType = (status: string) => {
  const types: Record<string, any> = {
    used: 'success',
    available: '',
    reserved: 'warning',
    offline: 'danger'
  }
  return types[status] || ''
}

const getOsTagType = (osType: string) => {
  const types: Record<string, any> = {
    windows: 'primary',
    linux: 'success',
    network: 'warning',
    unix: 'info'
  }
  return types[osType] || ''
}

const hasChanges = (record: IPScanHistory) => {
  return record.status_changed || record.mac_changed || record.switch_changed ||
         record.port_changed || record.hostname_changed || record.os_changed
}
</script>

<style scoped>
.ip-detail-drawer {
  padding: 0 20px 20px 20px;
}

.info-card {
  margin-bottom: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.card-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
}

.detail-collapse {
  border: none;
}

.collapse-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 500;
}

.history-card {
  margin-bottom: 8px;
}

.history-item {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.history-status {
  display: flex;
  align-items: center;
  font-weight: 500;
}

.history-changes {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.history-details {
  font-size: 13px;
  color: #606266;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

:deep(.el-descriptions__label) {
  width: 140px;
  font-weight: 500;
}

:deep(.el-collapse-item__header) {
  font-size: 15px;
  padding-left: 12px;
}

:deep(.el-timeline-item__timestamp) {
  font-size: 12px;
  color: #909399;
}
</style>
