<template>
  <div class="switch-list">
    <el-table
      :data="switches"
      v-loading="loading"
      stripe
      style="width: 100%"
      @selection-change="handleSelectionChange"
      @sort-change="handleSortChange"
      ref="tableRef"
    >
      <el-table-column type="selection" width="45" />

      <!-- Name -->
      <el-table-column prop="name" label="名称" min-width="160">
        <template #default="{ row }">
          <el-link type="primary" @click="goToDetail(row)" underline="never" style="font-weight: 500; cursor: pointer;">
            {{ row.name }}
          </el-link>
        </template>
      </el-table-column>

      <!-- IP Address -->
      <el-table-column prop="ip_address" label="IP 地址" width="135" sortable="custom">
        <template #default="{ row }">
          <el-tag type="primary" size="small">{{ row.ip_address }}</el-tag>
        </template>
      </el-table-column>

      <!-- Vendor + Model combined -->
      <el-table-column prop="model" label="厂商 / 型号" min-width="160" sortable="custom">
        <template #default="{ row }">
          <div>
            <el-tag :type="getVendorTagType(row.vendor)" size="small">
              {{ row.vendor.toUpperCase() }}
            </el-tag>
            <span v-if="row.model" style="margin-left: 6px; font-size: 12px; color: #606266;">
              {{ row.model }}
            </span>
          </div>
        </template>
      </el-table-column>

      <!-- 认证配置: CLI + SNMP status -->
      <el-table-column label="认证配置" width="130">
        <template #default="{ row }">
          <div style="display: flex; gap: 4px; flex-wrap: wrap;">
            <el-tooltip :content="row.cli_enabled ? `CLI 已启用 (${(row.cli_transport || 'ssh').toUpperCase()})` : 'CLI 未启用'" placement="top">
              <el-tag :type="row.cli_enabled ? 'success' : 'info'" size="small">CLI</el-tag>
            </el-tooltip>
            <el-tooltip :content="row.has_snmp_credentials ? 'SNMP 已配置' : 'SNMP 未配置'" placement="top">
              <el-tag :type="row.has_snmp_credentials ? 'success' : 'warning'" size="small">SNMP</el-tag>
            </el-tooltip>
          </div>
        </template>
      </el-table-column>

      <!-- 自动采集: ARP + MAC -->
      <el-table-column label="自动采集" width="100">
        <template #default="{ row }">
          <div style="display: flex; gap: 4px;">
            <el-tooltip content="ARP 自动采集" placement="top">
              <el-tag :type="row.auto_collect_arp ? 'success' : 'info'" size="small">ARP</el-tag>
            </el-tooltip>
            <el-tooltip content="MAC 自动采集" placement="top">
              <el-tag :type="row.auto_collect_mac ? 'success' : 'info'" size="small">MAC</el-tag>
            </el-tooltip>
          </div>
        </template>
      </el-table-column>

      <el-table-column label="Trunk 识别" width="140">
        <template #default="{ row }">
          <div style="font-size: 12px;">
            <el-tag :type="row.trunk_review_completed ? 'success' : 'warning'" size="small">
              {{ row.trunk_review_completed ? '已完成' : '待处理' }}
            </el-tag>
            <div
              v-if="row.trunk_review_completed_at"
              style="color: #909399; margin-top: 2px; font-size: 11px;"
            >
              {{ formatRelativeTime(row.trunk_review_completed_at) }}
            </div>
          </div>
        </template>
      </el-table-column>

      <!-- 上次采集 -->
      <el-table-column label="上次采集" width="110" column-key="last_collection_time" sortable="custom">
        <template #default="{ row }">
          <div v-if="row.last_collection_status" style="font-size: 12px;">
            <el-tag
              :type="row.last_collection_status === 'success' ? 'success' : row.last_collection_status === 'failed' ? 'danger' : 'warning'"
              size="small"
            >
              {{ row.last_collection_status }}
            </el-tag>
            <div v-if="row.last_arp_collection_at || row.last_mac_collection_at" style="color: #909399; margin-top: 2px; font-size: 11px;">
              {{ formatCollectionTime(row) }}
            </div>
          </div>
          <span v-else style="color: #909399; font-size: 12px;">-</span>
        </template>
      </el-table-column>

      <!-- Ping 状态 + 响应时间 combined -->
      <el-table-column prop="is_reachable" column-key="connection_status" label="连接状态" width="120" sortable="custom">
        <template #default="{ row }">
          <div v-if="row.is_reachable === true">
            <el-tag type="success" size="small" effect="dark">
              <el-icon><CircleCheck /></el-icon> 在线
            </el-tag>
            <div v-if="row.response_time_ms" style="color: #67c23a; font-size: 11px; margin-top: 2px; font-weight: 500;">
              {{ row.response_time_ms.toFixed(1) }}ms
            </div>
          </div>
          <el-tag v-else-if="row.is_reachable === false" type="danger" size="small" effect="dark">
            <el-icon><CircleClose /></el-icon> 离线
          </el-tag>
          <el-tag v-else type="info" size="small">
            <el-icon><QuestionFilled /></el-icon> 未知
          </el-tag>
        </template>
      </el-table-column>

      <!-- 启用状态 -->
      <el-table-column prop="enabled" label="启用" width="70">
        <template #default="{ row }">
          <el-tag :type="row.enabled ? 'success' : 'info'" size="small">
            {{ row.enabled ? '是' : '否' }}
          </el-tag>
        </template>
      </el-table-column>

      <!-- 操作 -->
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-space :size="5">
            <!-- Primary Action: View Details (on name click) + Test -->
            <el-tooltip content="测试连接" placement="top">
              <el-button
                size="small"
                type="primary"
                :icon="Connection"
                circle
                @click="$emit('test', row)"
              />
            </el-tooltip>

            <!-- Secondary Actions (Dropdown) -->
            <el-dropdown trigger="click" @command="(cmd: string) => handleAction(cmd, row)">
              <el-button size="small" :icon="More" circle />
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="edit" :icon="Edit">
                    编辑交换机
                  </el-dropdown-item>
                  <el-dropdown-item command="delete" :icon="Delete" divided style="color: #f56c6c">
                    删除交换机
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </el-space>
        </template>
      </el-table-column>
    </el-table>

    <el-empty v-if="!loading && switches.length === 0" description="暂无交换机">
      <el-button type="primary" @click="$emit('refresh')">添加第一台交换机</el-button>
    </el-empty>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { Connection, Edit, Delete, CircleCheck, CircleClose, QuestionFilled, More } from '@element-plus/icons-vue'
import type { Switch } from '@/api/switches'

const router = useRouter()

defineProps<{
  switches: Switch[]
  loading: boolean
}>()

const emit = defineEmits<{
  refresh: []
  edit: [switchItem: Switch]
  delete: [switchItem: Switch]
  test: [switchItem: Switch]
  selectionChange: [switches: Switch[]]
  sortChange: [sortBy: string, sortOrder: 'asc' | 'desc' | null]
}>()

const tableRef = ref()

const goToDetail = (switchItem: Switch) => {
  router.push(`/switches/${switchItem.id}`)
}

const handleSelectionChange = (selection: Switch[]) => {
  emit('selectionChange', selection)
}

const handleSortChange = ({ prop, column, order }: { prop: string; column: any; order: 'ascending' | 'descending' | null }) => {
  const sortKey = column?.columnKey || prop
  const sortOrder = order === 'ascending' ? 'asc' : order === 'descending' ? 'desc' : null
  emit('sortChange', sortKey, sortOrder)
}

const getVendorTagType = (vendor: string) => {
  const types: Record<string, any> = {
    cisco: 'primary',
    dell: 'success',
    alcatel: 'warning'
  }
  return types[vendor] || 'info'
}

const formatCollectionTime = (row: Switch) => {
  if (row.last_arp_collection_at || row.last_mac_collection_at) {
    const time = row.last_arp_collection_at || row.last_mac_collection_at
    if (!time) return '-'

    const date = new Date(time)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMins = Math.floor(diffMs / 60000)

    if (diffMins < 1) return '刚刚'
    if (diffMins < 60) return `${diffMins}分钟前`
    if (diffMins < 1440) return `${Math.floor(diffMins / 60)}小时前`
    return `${Math.floor(diffMins / 1440)}天前`
  }
  return '-'
}

const formatRelativeTime = (time: string) => {
  const date = new Date(time)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)

  if (diffMins < 1) return '刚刚'
  if (diffMins < 60) return `${diffMins}分钟前`
  if (diffMins < 1440) return `${Math.floor(diffMins / 60)}小时前`
  return `${Math.floor(diffMins / 1440)}天前`
}

// Handle dropdown menu actions
const handleAction = (command: string, row: Switch) => {
  if (command === 'edit') {
    emit('edit', row)
  } else if (command === 'delete') {
    emit('delete', row)
  }
}
</script>

<style scoped>
.switch-list {
  width: 100%;
}
</style>
