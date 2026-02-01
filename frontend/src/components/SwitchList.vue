<template>
  <div class="switch-list">
    <el-table :data="switches" v-loading="loading" stripe style="width: 100%">
      <el-table-column prop="name" label="Name" min-width="150" />

      <el-table-column prop="ip_address" label="IP Address" width="140">
        <template #default="{ row }">
          <el-tag type="primary">{{ row.ip_address }}</el-tag>
        </template>
      </el-table-column>

      <el-table-column prop="vendor" label="Vendor" width="100">
        <template #default="{ row }">
          <el-tag
            :type="getVendorTagType(row.vendor)"
          >
            {{ row.vendor.toUpperCase() }}
          </el-tag>
        </template>
      </el-table-column>

      <el-table-column prop="model" label="Model" min-width="120">
        <template #default="{ row }">
          {{ row.model || '-' }}
        </template>
      </el-table-column>

      <el-table-column prop="role" label="Role" width="100">
        <template #default="{ row }">
          <el-tag :type="getRoleTagType(row.role)">
            {{ getRoleLabel(row.role) }}
          </el-tag>
        </template>
      </el-table-column>

      <el-table-column prop="priority" label="Priority" width="90">
        <template #default="{ row }">
          <el-tag :type="getPriorityTagType(row.priority)">
            {{ row.priority }}
          </el-tag>
        </template>
      </el-table-column>

      <el-table-column prop="ssh_port" label="Port" width="70" />

      <el-table-column prop="username" label="Username" width="110" />

      <el-table-column label="Ping Status" width="120">
        <template #default="{ row }">
          <el-tag
            v-if="row.is_reachable === true"
            type="success"
            size="small"
            effect="dark"
          >
            <el-icon><CircleCheck /></el-icon>
            Online
          </el-tag>
          <el-tag
            v-else-if="row.is_reachable === false"
            type="danger"
            size="small"
            effect="dark"
          >
            <el-icon><CircleClose /></el-icon>
            Offline
          </el-tag>
          <el-tag
            v-else
            type="info"
            size="small"
          >
            <el-icon><QuestionFilled /></el-icon>
            Unknown
          </el-tag>
        </template>
      </el-table-column>

      <el-table-column label="Response" width="100">
        <template #default="{ row }">
          <span v-if="row.response_time_ms" style="color: #67c23a; font-weight: 500;">
            {{ row.response_time_ms.toFixed(1) }}ms
          </span>
          <span v-else style="color: #909399;">-</span>
        </template>
      </el-table-column>

      <el-table-column prop="enabled" label="Enabled" width="90">
        <template #default="{ row }">
          <el-tag :type="row.enabled ? 'success' : 'info'" size="small">
            {{ row.enabled ? 'On' : 'Off' }}
          </el-tag>
        </template>
      </el-table-column>

      <el-table-column label="Actions" width="260" fixed="right">
        <template #default="{ row }">
          <el-button
            size="small"
            type="primary"
            @click="$emit('test', row)"
            :icon="Connection"
          >
            Test
          </el-button>
          <el-button
            size="small"
            @click="$emit('edit', row)"
            :icon="Edit"
          >
            Edit
          </el-button>
          <el-button
            size="small"
            type="danger"
            @click="$emit('delete', row)"
            :icon="Delete"
          >
            Delete
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-empty v-if="!loading && switches.length === 0" description="No switches configured">
      <el-button type="primary" @click="$emit('refresh')">Add Your First Switch</el-button>
    </el-empty>
  </div>
</template>

<script setup lang="ts">
import { Connection, Edit, Delete, CircleCheck, CircleClose, QuestionFilled } from '@element-plus/icons-vue'
import type { Switch } from '@/api/switches'

defineProps<{
  switches: Switch[]
  loading: boolean
}>()

defineEmits<{
  refresh: []
  edit: [switchItem: Switch]
  delete: [switchItem: Switch]
  test: [switchItem: Switch]
}>()

const getVendorTagType = (vendor: string) => {
  const types: Record<string, any> = {
    cisco: 'primary',
    dell: 'success',
    alcatel: 'warning'
  }
  return types[vendor] || 'info'
}

const getRoleTagType = (role: string) => {
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
    aggregation: 'Agg',
    access: 'Access'
  }
  return labels[role] || role
}

const getPriorityTagType = (priority: number) => {
  if (priority <= 20) return 'danger'
  if (priority <= 40) return 'warning'
  return 'info'
}

const formatDate = (dateString: string) => {
  const date = new Date(dateString)
  return date.toLocaleString()
}
</script>

<style scoped>
.switch-list {
  width: 100%;
  overflow-x: auto;
}
</style>
