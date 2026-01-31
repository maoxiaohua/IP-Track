<template>
  <div class="home-view">
    <el-card class="lookup-card">
      <template #header>
        <div class="card-header">
          <h2>IP Address Lookup</h2>
          <p>Enter an IP address to find which switch port it's connected to</p>
        </div>
      </template>

      <IPLookupForm />
      <ResultDisplay v-if="lookupStore.currentResult" :result="lookupStore.currentResult" />
    </el-card>

    <el-card class="recent-history-card" v-if="recentHistory.length > 0">
      <template #header>
        <div class="card-header">
          <h3>Recent Queries</h3>
        </div>
      </template>
      <QueryHistory :items="recentHistory" :show-pagination="false" />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useLookupStore } from '@/stores/lookup'
import { lookupApi, type QueryHistoryItem } from '@/api/lookup'
import IPLookupForm from '@/components/IPLookupForm.vue'
import ResultDisplay from '@/components/ResultDisplay.vue'
import QueryHistory from '@/components/QueryHistory.vue'

const lookupStore = useLookupStore()
const recentHistory = ref<QueryHistoryItem[]>([])

onMounted(async () => {
  try {
    const response = await lookupApi.getHistory(1, 5)
    recentHistory.value = response.items
  } catch (error) {
    console.error('Failed to load recent history:', error)
  }
})
</script>

<style scoped>
.home-view {
  max-width: 1200px;
  margin: 0 auto;
}

.lookup-card {
  margin-bottom: 20px;
}

.card-header h2 {
  margin: 0 0 8px 0;
  color: #303133;
}

.card-header h3 {
  margin: 0;
  color: #303133;
}

.card-header p {
  margin: 0;
  color: #909399;
  font-size: 14px;
}

.recent-history-card {
  margin-top: 20px;
}
</style>
