<template>
  <div class="history-view">
    <el-card>
      <template #header>
        <div class="card-header">
          <h2>Query History</h2>
          <el-button @click="loadHistory" :icon="Refresh">Refresh</el-button>
        </div>
      </template>

      <QueryHistory
        :items="historyItems"
        :total="total"
        :show-pagination="true"
        @page-change="handlePageChange"
      />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { lookupApi, type QueryHistoryItem } from '@/api/lookup'
import QueryHistory from '@/components/QueryHistory.vue'

const historyItems = ref<QueryHistoryItem[]>([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const loading = ref(false)

const loadHistory = async () => {
  loading.value = true
  try {
    const response = await lookupApi.getHistory(currentPage.value, pageSize.value)
    historyItems.value = response.items
    total.value = response.total
  } catch (error) {
    ElMessage.error('Failed to load query history')
  } finally {
    loading.value = false
  }
}

const handlePageChange = (page: number, size: number) => {
  currentPage.value = page
  pageSize.value = size
  loadHistory()
}

onMounted(() => {
  loadHistory()
})
</script>

<style scoped>
.history-view {
  max-width: 1400px;
  margin: 0 auto;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.card-header h2 {
  margin: 0;
  color: #303133;
}
</style>
