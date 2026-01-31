<template>
  <div class="query-history">
    <el-table :data="items" stripe style="width: 100%">
      <el-table-column prop="target_ip" label="IP Address" width="150">
        <template #default="{ row }">
          <el-tag type="primary">{{ row.target_ip }}</el-tag>
        </template>
      </el-table-column>

      <el-table-column prop="found_mac" label="MAC Address" width="180">
        <template #default="{ row }">
          <el-tag v-if="row.found_mac" type="info">{{ row.found_mac }}</el-tag>
          <span v-else class="text-muted">-</span>
        </template>
      </el-table-column>

      <el-table-column prop="port_name" label="Port" width="120">
        <template #default="{ row }">
          <el-tag v-if="row.port_name" type="success">{{ row.port_name }}</el-tag>
          <span v-else class="text-muted">-</span>
        </template>
      </el-table-column>

      <el-table-column prop="vlan_id" label="VLAN" width="100">
        <template #default="{ row }">
          <el-tag v-if="row.vlan_id" type="warning">{{ row.vlan_id }}</el-tag>
          <span v-else class="text-muted">-</span>
        </template>
      </el-table-column>

      <el-table-column prop="query_status" label="Status" width="120">
        <template #default="{ row }">
          <el-tag v-if="row.query_status === 'success'" type="success">Success</el-tag>
          <el-tag v-else-if="row.query_status === 'not_found'" type="warning">Not Found</el-tag>
          <el-tag v-else type="danger">Error</el-tag>
        </template>
      </el-table-column>

      <el-table-column prop="query_time_ms" label="Time (ms)" width="100" />

      <el-table-column prop="queried_at" label="Queried At" width="180">
        <template #default="{ row }">
          {{ formatDate(row.queried_at) }}
        </template>
      </el-table-column>

      <el-table-column label="Details" width="100">
        <template #default="{ row }">
          <el-tooltip v-if="row.error_message" :content="row.error_message" placement="top">
            <el-icon color="#f56c6c"><InfoFilled /></el-icon>
          </el-tooltip>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      v-if="showPagination"
      v-model:current-page="currentPage"
      v-model:page-size="pageSize"
      :total="total"
      :page-sizes="[10, 20, 50, 100]"
      layout="total, sizes, prev, pager, next, jumper"
      @size-change="handleSizeChange"
      @current-change="handleCurrentChange"
      style="margin-top: 20px; justify-content: center"
    />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { QueryHistoryItem } from '@/api/lookup'

interface Props {
  items: QueryHistoryItem[]
  total?: number
  showPagination?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  total: 0,
  showPagination: true
})

const emit = defineEmits<{
  pageChange: [page: number, pageSize: number]
}>()

const currentPage = ref(1)
const pageSize = ref(20)

const formatDate = (dateString: string) => {
  const date = new Date(dateString)
  return date.toLocaleString()
}

const handleSizeChange = (size: number) => {
  pageSize.value = size
  emit('pageChange', currentPage.value, size)
}

const handleCurrentChange = (page: number) => {
  currentPage.value = page
  emit('pageChange', page, pageSize.value)
}
</script>

<style scoped>
.text-muted {
  color: #909399;
}
</style>
