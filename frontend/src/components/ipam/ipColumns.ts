/**
 * IP 地址表格的「单一列定义源」。
 *
 * 子网详情、饼图下钻页（OSTypeIPList）、IPAM 全局搜索结果三处表格，
 * 以及两处导出（CSV / Excel），全部从这里取列定义。
 * 以后新增一列只需要改这个文件，不必再去各页面逐个添加。
 */
import type { IPAddressDetail } from '@/api/ipam'
import { formatDateTime, formatLastResponse } from '@/utils/time'

export interface IPColumnDef {
  /** 唯一键，用于保存「哪些列被隐藏」的偏好 */
  key: string
  label: string
  /** el-table-column 的 prop（用于默认排序匹配） */
  prop?: string
  width?: number
  minWidth?: number
  align?: 'left' | 'center' | 'right'
  sortable?: boolean
  /** 默认是否可见；false 的列默认收起，用户可在列设置里打开 */
  defaultVisible: boolean
  /** 导出时写入该列的值（所有导出共用，保证口径一致） */
  exportValue: (row: IPAddressDetail) => string | number
}

// 对端设备（后端统一判定）：仅做文案映射，不做前端二次推断。
export const PORT_DEVICE_LABEL: Record<string, string> = {
  switch: '交换机',
  router: '路由器',
  'wlan-ap': '无线 AP',
  hub: '集线器',
  phone: 'IP 话机',
  host: 'PC / 服务器',
  unknown: '未识别'
}

export const portDeviceLabel = (deviceClass?: string | null) =>
  PORT_DEVICE_LABEL[deviceClass || ''] || '未识别'

export const portDeviceTagType = (deviceClass?: string | null) => {
  if (deviceClass === 'switch' || deviceClass === 'router') return 'success'
  if (deviceClass === 'hub' || deviceClass === 'wlan-ap') return 'warning'
  return 'info'
}

export const portDeviceTooltip = (row: IPAddressDetail) => {
  const parts: string[] = [portDeviceLabel(row.port_device_class)]
  if (row.port_device_confidence != null) parts.push(`置信度 ${row.port_device_confidence}%`)
  if (row.port_device_reasons) parts.push(row.port_device_reasons)
  return parts.join(' · ')
}

const OS_TYPE_LABEL: Record<string, string> = {
  windows: 'Windows',
  linux: 'Linux',
  network: 'Network',
  unix: 'Unix'
}

export const IP_STATUS_LABEL: Record<string, string> = {
  used: '使用中',
  available: '可用',
  reserved: '保留',
  offline: '离线'
}

export const ipStatusLabel = (status?: string | null) =>
  IP_STATUS_LABEL[status || ''] || status || '-'

export const IP_COLUMNS: IPColumnDef[] = [
  {
    key: 'status',
    label: 'Status',
    width: 60,
    align: 'center',
    defaultVisible: true,
    exportValue: (row) => (row.is_reachable ? 'Reachable' : 'Unreachable')
  },
  {
    key: 'ip_address',
    label: 'IP Address',
    prop: 'ip_address',
    width: 135,
    sortable: true,
    defaultVisible: true,
    exportValue: (row) => row.ip_address
  },
  {
    key: 'last_response',
    label: 'Last Response',
    width: 120,
    sortable: true,
    defaultVisible: true,
    exportValue: (row) => formatLastResponse(row.last_seen_at) || '-'
  },
  {
    key: 'response_time',
    label: 'Response Time',
    width: 100,
    align: 'right',
    defaultVisible: true,
    exportValue: (row) => (row.response_time != null ? `${row.response_time} ms` : '-')
  },
  {
    key: 'dns',
    label: 'DNS',
    minWidth: 140,
    defaultVisible: true,
    exportValue: (row) => row.dns_name || row.hostname || '-'
  },
  {
    key: 'system_name',
    label: 'System Name',
    prop: 'system_name',
    minWidth: 120,
    defaultVisible: true,
    exportValue: (row) => row.system_name || '-'
  },
  {
    key: 'machine_type',
    label: 'Machine Type',
    prop: 'machine_type',
    minWidth: 110,
    defaultVisible: true,
    exportValue: (row) => row.machine_type || '-'
  },
  {
    key: 'vendor',
    label: 'Vendor',
    prop: 'vendor',
    width: 100,
    defaultVisible: true,
    exportValue: (row) => row.vendor || '-'
  },
  {
    key: 'serial_number',
    label: 'SN',
    prop: 'serial_number',
    minWidth: 140,
    defaultVisible: true,
    exportValue: (row) => row.serial_number || '-'
  },
  {
    key: 'device_model',
    label: '设备型号',
    prop: 'device_model',
    minWidth: 140,
    defaultVisible: true,
    exportValue: (row) => row.device_model || '-'
  },
  {
    key: 'subnet',
    label: '子网',
    minWidth: 180,
    defaultVisible: true,
    exportValue: (row) => row.subnet_name || (row.subnet_id != null ? `#${row.subnet_id}` : '-')
  },
  {
    key: 'switch',
    label: 'Switch',
    minWidth: 150,
    defaultVisible: true,
    exportValue: (row) => row.switch_name || '-'
  },
  {
    key: 'port',
    label: 'Port',
    width: 110,
    defaultVisible: true,
    exportValue: (row) => row.switch_port || '-'
  },
  {
    key: 'port_device',
    label: '对端设备',
    width: 120,
    defaultVisible: true,
    exportValue: (row) => (row.port_device_class ? portDeviceLabel(row.port_device_class) : '-')
  },
  {
    key: 'os_type',
    label: 'OS Type',
    prop: 'os_type',
    width: 95,
    defaultVisible: true,
    exportValue: (row) => (row.os_type ? OS_TYPE_LABEL[row.os_type] || row.os_type : '-')
  },
  {
    key: 'os_name',
    label: 'OS Name',
    prop: 'os_name',
    minWidth: 110,
    defaultVisible: true,
    exportValue: (row) => row.os_name || '-'
  },
  {
    key: 'os_version',
    label: 'OS Version',
    prop: 'os_version',
    width: 100,
    defaultVisible: true,
    exportValue: (row) => row.os_version || '-'
  },
  {
    key: 'last_boot_time',
    label: 'Last Boot Time',
    minWidth: 130,
    defaultVisible: true,
    exportValue: (row) => formatDateTime(row.last_boot_time)
  },
  {
    key: 'mac_address',
    label: 'MAC 地址',
    prop: 'mac_address',
    width: 160,
    defaultVisible: false,
    exportValue: (row) => row.mac_address || '-'
  },
  {
    key: 'last_scan_time',
    label: '最近扫描时间',
    minWidth: 140,
    defaultVisible: false,
    exportValue: (row) => formatDateTime(row.last_scan_at)
  }
]

export const IP_COLUMN_KEYS = IP_COLUMNS.map((column) => column.key)

/** 默认隐藏的列（用户偏好里保存的是「被隐藏的 key」） */
export const IP_COLUMNS_DEFAULT_HIDDEN = IP_COLUMNS.filter((c) => !c.defaultVisible).map(
  (c) => c.key
)

/** 仅用于导出的补充字段（不参与表格列设置） */
export interface IPExportExtra {
  label: string
  exportValue: (row: IPAddressDetail) => string | number
}

export const IP_EXPORT_EXTRAS: IPExportExtra[] = [
  { label: '状态', exportValue: (row) => ipStatusLabel(row.status) },
  {
    label: '对端设备置信度',
    exportValue: (row) => (row.port_device_confidence != null ? `${row.port_device_confidence}%` : '')
  },
  { label: 'VLAN ID', exportValue: (row) => row.vlan_id ?? '' },
  { label: '备注/描述', exportValue: (row) => row.description || '' }
]

/**
 * 按同一套列定义生成导出行，保证页面新增列后导出自动跟随。
 */
export function buildIPExportRows(
  rows: IPAddressDetail[],
  extras: IPExportExtra[] = IP_EXPORT_EXTRAS
): Record<string, string | number>[] {
  return rows.map((row) => {
    const out: Record<string, string | number> = {}
    for (const column of IP_COLUMNS) out[column.label] = column.exportValue(row)
    for (const extra of extras) out[extra.label] = extra.exportValue(row)
    return out
  })
}

// ---------- 排序 / 展示辅助（三处表格共用） ----------

export const getLastResponse = (ip: IPAddressDetail): string =>
  formatLastResponse(ip.last_seen_at)

export const getLastResponseColor = (ip: IPAddressDetail): string => {
  const dateStr = ip.last_seen_at
  if (!dateStr) return '#909399'

  const diffMs = new Date().getTime() - new Date(dateStr).getTime()
  const diffDays = Math.floor(diffMs / 86400000)

  if (diffDays === 0) return '#67c23a'
  if (diffDays <= 7) return '#409eff'
  if (diffDays <= 30) return '#e6a23c'
  return '#f56c6c'
}

export const sortByLastResponse = (a: IPAddressDetail, b: IPAddressDetail): number => {
  const dateA = new Date(a.last_seen_at || 0).getTime()
  const dateB = new Date(b.last_seen_at || 0).getTime()
  return dateB - dateA
}

export const ipToNumber = (ip: string): number => {
  // 仅 IPv4 支持数值排序；其他（IPv6 等）返回 NaN，由调用方回退到字符串比较
  if (!ip || ip.indexOf('.') === -1) return Number.NaN
  return ip.split('.').reduce((acc, octet) => acc * 256 + Number(octet), 0)
}

export const sortByIpAddress = (a: IPAddressDetail, b: IPAddressDetail): number => {
  const numA = ipToNumber(a.ip_address)
  const numB = ipToNumber(b.ip_address)
  if (Number.isNaN(numA) || Number.isNaN(numB)) {
    return String(a.ip_address || '').localeCompare(String(b.ip_address || ''))
  }
  return numA - numB
}

export const getStatusTooltip = (ip: IPAddressDetail): string => {
  if (ip.is_reachable) return 'Online - IP is reachable'
  if (ip.status === 'used') return 'Offline - IP was used but not reachable'
  if (ip.status === 'reserved') return 'Reserved - IP is reserved'
  return 'Available - IP is not in use'
}
