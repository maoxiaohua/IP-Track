<template>
  <div class="ip-table-scroll" :style="wrapperMaxHeight ? { maxHeight: wrapperMaxHeight } : undefined">
    <el-table
      :data="rows"
      v-loading="loading"
      :element-loading-text="loadingText"
      :stripe="stripe"
      :size="size"
      :max-height="maxHeight"
      :default-sort="defaultSort"
      :highlight-current-row="highlightCurrentRow"
      :current-row-key="currentRowKey"
      row-key="id"
      :row-style="rowClickable ? { cursor: 'pointer' } : undefined"
      :class="['ip-address-table', tableClass]"
      @row-click="handleRowClick"
    >
      <el-table-column
        v-for="col in columns"
        :key="col.key"
        :prop="col.prop"
        :label="col.label"
        :width="col.width"
        :min-width="col.minWidth"
        :align="col.align"
        :sortable="col.sortable ? true : false"
        :sort-method="sortMethodOf(col.key)"
        show-overflow-tooltip
      >
        <template #default="{ row }">
          <!-- Status 图标 -->
          <template v-if="col.key === 'status'">
            <el-tooltip :content="getStatusTooltip(row)" placement="top">
              <div style="display: flex; align-items: center; justify-content: center">
                <el-icon v-if="row.is_reachable" :size="18" style="color: #67c23a">
                  <CircleCheckFilled />
                </el-icon>
                <el-icon v-else-if="row.status === 'used'" :size="18" style="color: #f56c6c">
                  <CircleCloseFilled />
                </el-icon>
                <el-icon v-else-if="row.status === 'reserved'" :size="18" style="color: #e6a23c">
                  <WarningFilled />
                </el-icon>
                <el-icon v-else :size="18" style="color: #909399">
                  <Remove />
                </el-icon>
              </div>
            </el-tooltip>
          </template>

          <!-- IP 地址（点击打开详情 / 下钻） -->
          <template v-else-if="col.key === 'ip_address'">
            <span class="ip-address-link" @click.stop="emit('ip-click', row)">
              {{ row.ip_address }}
            </span>
          </template>

          <template v-else-if="col.key === 'last_response'">
            <span :style="{ color: getLastResponseColor(row) }">
              {{ getLastResponse(row) }}
            </span>
          </template>

          <template v-else-if="col.key === 'response_time'">
            <span v-if="row.response_time != null" class="response-time-cell">
              {{ row.response_time }} ms
            </span>
            <span v-else style="color: #909399">-</span>
          </template>

          <template v-else-if="col.key === 'dns'">
            {{ row.dns_name || row.hostname || '-' }}
          </template>

          <template v-else-if="col.key === 'system_name'">
            {{ row.system_name || '-' }}
          </template>

          <template v-else-if="col.key === 'machine_type'">
            {{ row.machine_type || '-' }}
          </template>

          <template v-else-if="col.key === 'vendor'">
            {{ row.vendor || '-' }}
          </template>

          <template v-else-if="col.key === 'serial_number'">
            <span v-if="row.serial_number" class="serial-cell">{{ row.serial_number }}</span>
            <span v-else style="color: #909399">-</span>
          </template>

          <template v-else-if="col.key === 'device_model'">
            {{ row.device_model || '-' }}
          </template>

          <template v-else-if="col.key === 'subnet'">
            <router-link
              v-if="row.subnet_id"
              :to="`/ipam/subnets/${row.subnet_id}`"
              style="color: var(--primary-color); text-decoration: none"
              @click.stop
            >
              {{ row.subnet_name || `#${row.subnet_id}` }}
            </router-link>
            <span v-else style="color: #909399">-</span>
          </template>

          <template v-else-if="col.key === 'switch'">
            <router-link
              v-if="row.switch_id"
              :to="`/switches/${row.switch_id}`"
              style="color: var(--primary-color); text-decoration: none"
              @click.stop
            >
              {{ row.switch_name || '-' }}
            </router-link>
            <span v-else style="color: #909399">-</span>
          </template>

          <template v-else-if="col.key === 'port'">
            <el-tooltip
              v-if="row.switch_port"
              :content="row.switch_port"
              placement="top"
              :disabled="(row.switch_port || '').length <= 12"
            >
              <el-tag type="success" size="small" class="port-tag">{{ row.switch_port }}</el-tag>
            </el-tooltip>
            <span v-else style="color: #909399">-</span>
          </template>

          <template v-else-if="col.key === 'port_device'">
            <el-tooltip
              v-if="row.port_device_class"
              :content="portDeviceTooltip(row)"
              placement="top"
            >
              <el-tag :type="portDeviceTagType(row.port_device_class)" effect="dark" size="small">
                {{ portDeviceLabel(row.port_device_class) }}
              </el-tag>
            </el-tooltip>
            <span v-else style="color: #909399">-</span>
          </template>

          <template v-else-if="col.key === 'os_type'">
            <el-tag v-if="row.os_type === 'windows'" type="primary" size="small">Windows</el-tag>
            <el-tag v-else-if="row.os_type === 'linux'" type="success" size="small">Linux</el-tag>
            <el-tag v-else-if="row.os_type === 'network'" type="warning" size="small">Network</el-tag>
            <el-tag v-else-if="row.os_type === 'unix'" type="info" size="small">Unix</el-tag>
            <span v-else style="color: #909399">-</span>
          </template>

          <template v-else-if="col.key === 'os_name'">
            {{ row.os_name || '-' }}
          </template>

          <template v-else-if="col.key === 'os_version'">
            {{ row.os_version || '-' }}
          </template>

          <template v-else-if="col.key === 'last_boot_time'">
            {{ row.last_boot_time ? formatDateTime(row.last_boot_time) : '-' }}
          </template>

          <template v-else-if="col.key === 'mac_address'">
            {{ row.mac_address || '-' }}
          </template>

          <template v-else-if="col.key === 'last_scan_time'">
            {{ formatDateTime(row.last_scan_at) }}
          </template>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import {
  CircleCheckFilled,
  CircleCloseFilled,
  Remove,
  WarningFilled
} from '@element-plus/icons-vue'
import type { IPAddressDetail } from '@/api/ipam'
import { formatDateTime } from '@/utils/time'
import {
  getLastResponse,
  getLastResponseColor,
  getStatusTooltip,
  portDeviceLabel,
  portDeviceTagType,
  portDeviceTooltip,
  sortByIpAddress,
  sortByLastResponse,
  type IPColumnDef
} from './ipColumns'

const props = withDefaults(
  defineProps<{
    rows: IPAddressDetail[]
    columns: IPColumnDef[]
    loading?: boolean
    loadingText?: string
    size?: 'large' | 'default' | 'small'
    stripe?: boolean
    /** 外层横向滚动容器（宽表格） */
    wrapperMaxHeight?: string
    /** el-table 自身的最大高度（内部纵向滚动） */
    maxHeight?: string | number
    highlightCurrentRow?: boolean
    currentRowKey?: string | number
    defaultSortProp?: string
    defaultSortOrder?: 'ascending' | 'descending'
    tableClass?: string
    rowClickable?: boolean
  }>(),
  {
    loading: false,
    loadingText: '正在加载...',
    size: 'small',
    stripe: true,
    wrapperMaxHeight: '',
    maxHeight: undefined,
    highlightCurrentRow: false,
    currentRowKey: undefined,
    defaultSortProp: '',
    defaultSortOrder: 'ascending',
    tableClass: '',
    rowClickable: false
  }
)

const emit = defineEmits<{
  (e: 'row-click', row: IPAddressDetail): void
  (e: 'ip-click', row: IPAddressDetail): void
}>()

const defaultSort = computed(() =>
  props.defaultSortProp
    ? { prop: props.defaultSortProp, order: props.defaultSortOrder }
    : undefined
)

const SORT_METHODS: Record<string, (a: IPAddressDetail, b: IPAddressDetail) => number> = {
  ip_address: sortByIpAddress,
  last_response: sortByLastResponse
}

const sortMethodOf = (key: string) => SORT_METHODS[key]

const handleRowClick = (row: IPAddressDetail) => {
  if (props.rowClickable) emit('row-click', row)
}
</script>

<style scoped>
.ip-table-scroll {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: thin;
  scrollbar-color: #c0c4cc transparent;
}

.ip-address-table {
  width: auto !important;
  min-width: 100%;
}

.ip-address-table :deep(.el-table__body-wrapper) {
  overflow-y: auto;
}

.ip-address-table :deep(.cell) {
  padding: 4px 8px;
  font-size: 13px;
  line-height: 1.4;
  word-break: break-word;
}

.ip-address-table :deep(.el-table th) {
  background-color: #f5f7fa;
  color: #1f2937 !important;
  font-weight: 600;
}

.ip-address-table :deep(.el-table th .cell) {
  color: #1f2937 !important;
}

.ip-table-scroll::-webkit-scrollbar {
  height: 8px;
}

.ip-table-scroll::-webkit-scrollbar-track {
  background: #f0f2f5;
  border-radius: 4px;
}

.ip-table-scroll::-webkit-scrollbar-thumb {
  background: #c0c4cc;
  border-radius: 4px;
}

.ip-table-scroll::-webkit-scrollbar-thumb:hover {
  background: #909399;
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

.serial-cell {
  font-family: monospace;
  word-break: break-all;
}

.response-time-cell {
  font-variant-numeric: tabular-nums;
}

.port-tag {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
