<template>
  <div class="home-view">
    <el-card class="lookup-card">
      <template #header>
        <div class="card-header">
          <h2>IP Address Lookup</h2>
          <p>Enter an IP address to find which switch port it's connected to</p>
        </div>
      </template>

      <IPLookupForm
        :initial-ip="routeIp"
        :loading="lookupStore.loading"
        :error="lookupStore.error"
        @submit="handleLookupSubmit"
      />
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
import { computed, ref, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useLookupStore } from '@/stores/lookup'
import { lookupApi, type QueryHistoryItem } from '@/api/lookup'
import IPLookupForm from '@/components/IPLookupForm.vue'
import ResultDisplay from '@/components/ResultDisplay.vue'
import QueryHistory from '@/components/QueryHistory.vue'

const route = useRoute()
const router = useRouter()
const lookupStore = useLookupStore()
const recentHistory = ref<QueryHistoryItem[]>([])
const routeIp = computed(() => typeof route.query.ip === 'string' ? route.query.ip : '')
const routeRerun = computed(() => typeof route.query.rerun === 'string' ? route.query.rerun : '')

const isValidIPv4 = (value: string) => {
  const ipv4Regex = /^(\d{1,3}\.){3}\d{1,3}$/
  if (!ipv4Regex.test(value)) return false
  return value.split('.').every(part => {
    const num = Number(part)
    return Number.isInteger(num) && num >= 0 && num <= 255
  })
}

const loadRecentHistory = async () => {
  try {
    const response = await lookupApi.getHistory(1, 5)
    recentHistory.value = response.items
  } catch (error) {
    console.error('Failed to load recent history:', error)
  }
}

const runLookup = async (ipAddress: string) => {
  await lookupStore.lookupIP(ipAddress)
  await loadRecentHistory()
}

const handleLookupSubmit = async (ipAddress: string) => {
  if (!isValidIPv4(ipAddress)) {
    ElMessage.error('请输入有效的 IPv4 地址')
    return
  }

  if (routeIp.value === ipAddress) {
    await runLookup(ipAddress)
    return
  }

  await router.replace({
    query: {
      ...route.query,
      ip: ipAddress,
      rerun: undefined
    }
  })
}

onMounted(async () => {
  await loadRecentHistory()
})

watch(
  () => [routeIp.value, routeRerun.value],
  async ([ipAddress]) => {
    if (!ipAddress) {
      lookupStore.clearResult()
      return
    }

    if (!isValidIPv4(ipAddress)) {
      ElMessage.warning('URL 中的 IP 地址格式无效，已跳过自动查询')
      return
    }

    await runLookup(ipAddress)
  },
  { immediate: true }
)
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
