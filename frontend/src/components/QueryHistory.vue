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

      <el-table-column prop="switch_name" label="Switch" width="200">
        <template #default="{ row }">
          <el-button
            v-if="row.switch_name && row.switch_id"
            type="primary"
            link
            @click="openSwitchDetail(row.switch_id)"
          >
            {{ row.switch_name }}
          </el-button>
          <el-tag v-else-if="row.switch_name" type="primary">{{ row.switch_name }}</el-tag>
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

      <el-table-column label="Current State" width="180">
        <template #default="{ row }">
          <div v-if="row.switch_id" class="state-stack">
            <el-tag
              v-if="row.current_freshness_status"
              :type="row.current_freshness_status === 'stale' ? 'warning' : 'success'"
              size="small"
            >
              {{ row.current_freshness_status === 'stale' ? 'Stale' : 'Fresh' }}
            </el-tag>
            <el-tag
              v-if="row.current_switch_is_reachable !== undefined && row.current_switch_is_reachable !== null"
              :type="row.current_switch_is_reachable ? 'success' : 'danger'"
              size="small"
            >
              {{ row.current_switch_is_reachable ? '在线' : '离线' }}
            </el-tag>
            <div
              v-if="row.current_switch_collection_status"
              class="state-meta"
              :title="row.current_switch_collection_message || ''"
            >
              {{ row.current_switch_collection_status }}
            </div>
          </div>
          <span v-else class="text-muted">-</span>
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

      <el-table-column label="Actions" width="120" fixed="right">
        <template #default="{ row }">
          <el-button
            type="primary"
            link
            @click="requeryIp(row.target_ip)"
          >
            重新查询
          </el-button>
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
import { useRouter } from 'vue-router'
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
void props

const router = useRouter()
const emit = defineEmits<{
  pageChange: [page: number, pageSize: number]
}>()

const currentPage = ref(1)
const pageSize = ref(20)

const formatDate = (dateString: string) => {
  const date = new Date(dateString)
  return date.toLocaleString()
}

const openSwitchDetail = (switchId: number) => {
  router.push(`/switches/${switchId}`)
}

const requeryIp = (ipAddress: string) => {
  router.push({
    path: '/',
    query: {
      ip: ipAddress,
      rerun: String(Date.now())
    }
  })
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

.state-stack {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.state-meta {
  font-size: 11px;
  color: #909399;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
