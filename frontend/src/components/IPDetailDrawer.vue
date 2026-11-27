<template>
  <el-drawer
    v-model="visible"
    :title="drawerTitle"
    :size="drawerSize"
    direction="rtl"
    append-to-body
    destroy-on-close
    :before-close="handleClose"
  >
    <div v-loading="loading" class="ip-detail-drawer">
      <!-- Basic Info - Always Expanded -->
      <el-card class="info-card" shadow="never">
        <template #header>
          <div class="card-header">
            <h3>Basic Information</h3>
            <el-tag :type="getStatusType(ipDetail.status)" size="large" effect="dark">
              {{ ipDetail.status?.toUpperCase() }}
            </el-tag>
          </div>
        </template>

        <el-descriptions :column="1" border>
          <el-descriptions-item label="IP Address">
            <span class="ip-address-value">
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
            <div class="identity-block">
              <div class="identity-main">
                <span>{{ getDisplayHostname(ipDetail) || '-' }}</span>
                <el-tag
                  v-if="ipDetail.hostname_source"
                  size="small"
                  :type="getHostnameSourceTagType(ipDetail.hostname_source)"
                >
                  {{ getHostnameSourceLabel(ipDetail.hostname_source) }}
                </el-tag>
              </div>
              <div v-if="getIdentityHint(ipDetail)" class="identity-hint">
                {{ getIdentityHint(ipDetail) }}
              </div>
            </div>
          </el-descriptions-item>
          <el-descriptions-item label="Response Time">
            {{ ipDetail.response_time != null ? `${ipDetail.response_time} ms` : '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="Last Verified">
            <div class="identity-block">
              <div class="identity-main">
                <span>{{ ipDetail.last_scan_at ? formatDateTime(ipDetail.last_scan_at) : '-' }}</span>
                <el-tag
                  v-if="ipDetail.last_scan_at"
                  size="small"
                  :type="getFreshnessTagType(ipDetail.last_scan_at)"
                >
                  {{ getFreshnessText(ipDetail.last_scan_at) }}
                </el-tag>
              </div>
            </div>
          </el-descriptions-item>
          <el-descriptions-item label="Last Seen">
            <span v-if="ipDetail.last_seen_at">{{ formatDateTime(ipDetail.last_seen_at) }}</span>
            <el-tag v-else type="warning" size="small">从未</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="Description">
            {{ ipDetail.description || '-' }}
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
                style="color: var(--primary-color); text-decoration: none"
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
            <el-descriptions-item label="对端设备">
              <template v-if="ipDetail.port_device_class">
                <el-tag :type="peerTagType" effect="dark" size="small">
                  {{ peerClassLabel }}
                </el-tag>
                <span v-if="ipDetail.port_device_confidence != null" class="peer-confidence">
                  置信度 {{ ipDetail.port_device_confidence }}%
                </span>
              </template>
              <span v-else style="color: #909399">-</span>
            </el-descriptions-item>
            <el-descriptions-item v-if="ipDetail.port_device_reasons" label="判定依据">
              {{ ipDetail.port_device_reasons }}
            </el-descriptions-item>
            <el-descriptions-item label="Location">
              {{ ipDetail.location || '-' }}
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
            <el-descriptions-item label="DNS Name">
              {{ ipDetail.dns_name || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="Machine Type">
              {{ ipDetail.machine_type || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="Vendor">
              {{ ipDetail.vendor || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="Hostname Source">
              {{ ipDetail.hostname_source || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="Contact">
              {{ ipDetail.contact || '-' }}
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
            <el-descriptions-item label="SN 序列号">
              <span class="hardware-serial">{{ ipDetail.serial_number || '-' }}</span>
              <el-tag
                v-if="ipDetail.hardware_source"
                size="small"
                :type="hardwareSourceTagType"
                class="hardware-source-tag"
              >
                {{ hardwareSourceLabel }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="设备型号">
              {{ ipDetail.device_model || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="硬件厂商">
              {{ ipDetail.hardware_vendor || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="采集时间">
              {{ ipDetail.hardware_collected_at ? formatDateTime(ipDetail.hardware_collected_at) : '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="硬件采集">
              <el-button
                type="primary"
                size="small"
                :loading="hardwareLoading"
                :disabled="hardwareLoading || !ipDetail.is_reachable"
                @click="collectHardware"
              >
                {{ hardwareLoading ? '采集中…' : '立即采集' }}
              </el-button>
              <span v-if="!ipDetail.is_reachable" class="hardware-hint">设备当前离线</span>
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
                      <span v-if="record.response_time != null" style="margin-left: 8px; color: #909399">
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
import { computed, ref, watch } from 'vue'
import {
  CircleCheckFilled,
  CircleCloseFilled,
  Clock,
  Connection,
  Monitor
} from '@element-plus/icons-vue'
import { ipamApi, hardwareApi } from '@/api/ipam'
import type { IPAddressDetail, IPScanHistory } from '@/api/ipam'
import { ElMessage } from 'element-plus'

interface Props {
  modelValue: boolean
  ipId: number | null
  refreshKey?: number
}

const props = defineProps<Props>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  refreshed: []
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value)
})
const loading = ref(false)
const historyLoading = ref(false)
const hardwareLoading = ref(false)
const ipDetail = ref<IPAddressDetail>({} as IPAddressDetail)

// 对端设备（后端统一判定）：只展示类别+置信度+依据，不在前端重复推断。
const PEER_CLASS_LABEL: Record<string, string> = {
  switch: '交换机',
  router: '路由器',
  'wlan-ap': '无线 AP',
  hub: '集线器',
  phone: 'IP 话机',
  host: 'PC / 服务器',
  unknown: '未识别'
}

const peerClassLabel = computed(
  () => PEER_CLASS_LABEL[ipDetail.value.port_device_class || ''] || '未识别'
)

const peerTagType = computed<'success' | 'warning' | 'info'>(() => {
  const cls = ipDetail.value.port_device_class
  if (cls === 'switch' || cls === 'router') return 'success'
  if (cls === 'hub' || cls === 'wlan-ap') return 'warning'
  return 'info'
})
const scanHistory = ref<IPScanHistory[]>([])
const activeCollapse = ref<string[]>(['location'])
let detailRequestSeq = 0
let historyRequestSeq = 0

const drawerTitle = computed(() => {
  if (ipDetail.value?.ip_address) {
    return `IP Address Details · ${ipDetail.value.ip_address}`
  }
  return 'IP Address Details'
})

const drawerSize = computed(() => window.innerWidth < 768 ? '100%' : '600px')

const resetDrawerState = () => {
  ipDetail.value = {} as IPAddressDetail
  scanHistory.value = []
  activeCollapse.value = ['location']
}

watch(
  [() => props.modelValue, () => props.ipId, () => props.refreshKey],
  ([isOpen, ipId], previousValues) => {
    const [prevOpen, prevIpId, prevRefreshKey] = previousValues ?? []

    if (!isOpen) {
      loading.value = false
      historyLoading.value = false
      detailRequestSeq += 1
      historyRequestSeq += 1
      resetDrawerState()
      return
    }

    if (!ipId) {
      resetDrawerState()
      return
    }

    const shouldReload =
      !prevOpen ||
      ipId !== prevIpId ||
      props.refreshKey !== prevRefreshKey

    if (shouldReload) {
      loadIPDetail()
      loadScanHistory()
    }
  },
  { immediate: true }
)

watch(() => props.modelValue, (val) => {
  if (!val) {
    resetDrawerState()
  }
})

const loadIPDetail = async () => {
  if (!props.ipId) return
  const requestSeq = ++detailRequestSeq
  loading.value = true
  ipDetail.value = {} as IPAddressDetail
  try {
    const detail = await ipamApi.getIPAddress(props.ipId)
    if (requestSeq !== detailRequestSeq) return
    ipDetail.value = detail
  } catch (error) {
    console.error('Failed to load IP details:', error)
  } finally {
    if (requestSeq === detailRequestSeq) {
      loading.value = false
    }
  }
}

const loadScanHistory = async () => {
  if (!props.ipId) return
  const requestSeq = ++historyRequestSeq
  historyLoading.value = true
  scanHistory.value = []
  try {
    const history = await ipamApi.getIPScanHistory(props.ipId)
    if (requestSeq !== historyRequestSeq) return
    scanHistory.value = history
  } catch (error) {
    console.error('Failed to load scan history:', error)
  } finally {
    if (requestSeq === historyRequestSeq) {
      historyLoading.value = false
    }
  }
}

const handleClose = (done?: () => void) => {
  emit('update:modelValue', false)
  done?.()
}

const formatDateTime = (dateString: string) => {
  const date = new Date(dateString)
  return date.toLocaleString('zh-CN')
}

// 硬件资产来源（SN/型号），与后端 hardware_source 取值保持一致
const HARDWARE_SOURCE_LABEL: Record<string, string> = {
  entity: 'SNMP ENTITY',
  printer: 'SNMP Printer',
  'host-resources': 'SNMP Host',
  sysdescr: 'SNMP sysDescr',
  wmi: 'WMI',
  winrm: 'WinRM',
  bmc: 'BMC',
  manual: '手工录入'
}

const hardwareSourceLabel = computed(
  () => HARDWARE_SOURCE_LABEL[ipDetail.value.hardware_source || ''] || ipDetail.value.hardware_source || ''
)

const hardwareSourceTagType = computed<'success' | 'warning' | 'info' | 'danger'>(() => {
  const source = ipDetail.value.hardware_source
  if (source === 'wmi' || source === 'winrm') return 'success'
  if (source === 'manual') return 'warning'
  if (source === 'sysdescr') return 'info'
  return 'info'
})

const collectHardware = async () => {
  if (!props.ipId || hardwareLoading.value) return
  hardwareLoading.value = true
  try {
    const result = await hardwareApi.collect({ ip_address_ids: [props.ipId], force: true })
    if (result.queued > 0) {
      ElMessage.success(result.message || '采集完成')
      await loadIPDetail()
      emit('refreshed')
    } else {
      ElMessage.warning('未获取到硬件信息，请确认设备已开启 SNMP，或已配置 WMI / WinRM 凭据')
    }
  } catch (error: any) {
    const detail = error?.response?.data?.detail
    ElMessage.error(detail || '硬件采集失败')
  } finally {
    hardwareLoading.value = false
  }
}

const getDisplayHostname = (detail: Partial<IPAddressDetail>) => {
  return detail.hostname || detail.dns_name || detail.system_name || ''
}

const getHostnameSourceLabel = (source?: string) => {
  const labels: Record<string, string> = {
    SNMP: 'SNMP',
    DNS: 'DNS PTR',
    NETBIOS: 'NetBIOS',
    MDNS: 'mDNS',
    ARP: 'ARP',
    SWITCH: 'Switch Cache',
    MANUAL: 'Manual'
  }
  return labels[source || ''] || source || ''
}

const getHostnameSourceTagType = (source?: string) => {
  const types: Record<string, any> = {
    SNMP: 'warning',
    DNS: 'success',
    NETBIOS: 'primary',
    MDNS: 'primary',
    ARP: 'info',
    SWITCH: 'info',
    MANUAL: 'danger'
  }
  return types[source || ''] || 'info'
}

const getIdentityHint = (detail: Partial<IPAddressDetail>) => {
  if (detail.hostname_source === 'DNS' && detail.dns_name && detail.hostname && detail.dns_name !== detail.hostname) {
    return `Full DNS: ${detail.dns_name}`
  }

  if (!getDisplayHostname(detail) && detail.is_reachable && detail.os_type === 'windows') {
    return 'Latest scan reached this Windows host, but neither DNS PTR nor NetBIOS returned a hostname.'
  }

  if (!getDisplayHostname(detail) && detail.is_reachable && (detail.os_type === 'linux' || detail.os_type === 'macos')) {
    return 'Latest scan reached this host, but DNS PTR and mDNS did not return a hostname. Ensure avahi-daemon or systemd-resolved is running.'
  }

  if (!getDisplayHostname(detail) && detail.is_reachable) {
    return 'Host is reachable, but the latest scan did not obtain a resolvable device name.'
  }

  if (!getDisplayHostname(detail) && detail.last_seen_at) {
    return 'Historical reachability exists, but no hostname source has been confirmed yet.'
  }

  return ''
}

const getFreshnessText = (dateString: string) => {
  const diffMs = Date.now() - new Date(dateString).getTime()
  const diffMinutes = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMs / 3600000)

  if (diffMinutes < 10) return 'Fresh'
  if (diffHours < 6) return 'Recent'
  if (diffHours < 24) return 'Today'
  return 'Stale'
}

const getFreshnessTagType = (dateString: string) => {
  const diffMs = Date.now() - new Date(dateString).getTime()
  const diffHours = Math.floor(diffMs / 3600000)

  if (diffHours < 1) return 'success'
  if (diffHours < 6) return 'primary'
  if (diffHours < 24) return 'warning'
  return 'danger'
}

const getStatusType = (status: string) => {
  const types: Record<string, any> = {
    used: 'primary',
    available: 'info',
    reserved: 'warning',
    offline: 'danger'
  }
  return types[status] || 'info'
}

const getOsTagType = (osType: string) => {
  const types: Record<string, any> = {
    windows: 'primary',
    linux: 'success',
    network: 'warning',
    unix: 'info'
  }
  return types[osType] || 'info'
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

.hardware-serial {
  font-family: monospace;
  word-break: break-all;
}

.hardware-source-tag {
  margin-left: 8px;
}

.hardware-hint {
  margin-left: 8px;
  font-size: 12px;
  color: #909399;
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

.identity-block {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.identity-main {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.identity-hint {
  color: #909399;
  font-size: 12px;
  line-height: 1.4;
}

.ip-address-value {
  font-family: 'SFMono-Regular', 'Cascadia Code', 'Consolas', 'Liberation Mono',
    'Courier New', monospace;
  font-size: 16px;
  font-weight: 700;
  color: #1e40af;
  letter-spacing: 0.02em;
  font-variant-numeric: tabular-nums;
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

.peer-confidence {
  margin-left: 8px;
  color: #606266;
  font-size: 12px;
}
</style>
