<template>
  <div class="result-display">
    <el-card v-if="result.found" class="success-card">
      <template #header>
        <div class="result-header">
          <el-icon color="#67c23a" :size="24"><SuccessFilled /></el-icon>
          <h3>Device Found</h3>
        </div>
      </template>

      <el-descriptions :column="2" border>
        <el-descriptions-item label="Target IP">
          <el-tag type="primary">{{ result.target_ip }}</el-tag>
        </el-descriptions-item>

        <el-descriptions-item label="MAC Address">
          <el-tag type="info">{{ result.mac_address }}</el-tag>
        </el-descriptions-item>

        <el-descriptions-item label="Switch Name">
          <strong>{{ result.switch_name }}</strong>
        </el-descriptions-item>

        <el-descriptions-item label="Switch IP">
          {{ result.switch_ip }}
        </el-descriptions-item>

        <el-descriptions-item label="Port">
          <el-tag type="success" size="large">{{ result.port_name }}</el-tag>
        </el-descriptions-item>

        <el-descriptions-item label="VLAN">
          <el-tag type="warning">VLAN {{ result.vlan_id }}</el-tag>
        </el-descriptions-item>

        <el-descriptions-item label="Query Time" :span="2">
          {{ result.query_time_ms }} ms
        </el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card v-else class="not-found-card">
      <template #header>
        <div class="result-header">
          <el-icon color="#f56c6c" :size="24"><CircleCloseFilled /></el-icon>
          <h3>Device Not Found</h3>
        </div>
      </template>

      <el-result
        icon="warning"
        :title="result.message || 'No device found for this IP address'"
      >
        <template #sub-title>
          <p>Target IP: <strong>{{ result.target_ip }}</strong></p>
          <p v-if="result.mac_address">MAC Address: <strong>{{ result.mac_address }}</strong></p>
          <p>Query Time: {{ result.query_time_ms }} ms</p>
        </template>
      </el-result>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import type { IPLookupResult } from '@/api/lookup'

defineProps<{
  result: IPLookupResult
}>()
</script>

<style scoped>
.result-display {
  margin-top: 20px;
}

.result-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.result-header h3 {
  margin: 0;
  color: #303133;
}

.success-card {
  border: 2px solid #67c23a;
}

.not-found-card {
  border: 2px solid #f56c6c;
}

.el-descriptions {
  margin-top: 16px;
}
</style>
