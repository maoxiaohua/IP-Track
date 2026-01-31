<template>
  <div class="subnet-detail-view">
    <el-card>
      <template #header>
        <div class="card-header">
          <div>
            <h2>{{ subnet.name }}</h2>
            <div class="subnet-info">
              <el-tag type="primary">{{ subnet.network }}</el-tag>
              <span v-if="subnet.vlan_id" style="margin-left: 10px">
                VLAN: {{ subnet.vlan_id }}
              </span>
              <span v-if="subnet.gateway" style="margin-left: 10px">
                网关: {{ subnet.gateway }}
              </span>
            </div>
          </div>
          <div>
            <el-button @click="$router.back()">
              <el-icon><Back /></el-icon>
              返回
            </el-button>
            <el-button type="success" @click="scanSubnet" :loading="scanning">
              <el-icon><Refresh /></el-icon>
              扫描子网
            </el-button>
          </div>
        </div>
      </template>

      <!-- Statistics -->
      <el-row :gutter="20" style="margin-bottom: 20px">
        <el-col :span="4">
          <el-statistic title="总 IP 数" :value="statistics.total_ips" />
        </el-col>
        <el-col :span="4">
          <el-statistic title="已使用" :value="statistics.used_ips">
            <template #prefix>
              <el-icon style="color: #67c23a"><Check /></el-icon>
            </template>
          </el-statistic>
        </el-col>
        <el-col :span="4">
          <el-statistic title="可用" :value="statistics.available_ips">
            <template #prefix>
              <el-icon style="color: #909399"><CircleClose /></el-icon>
            </template>
          </el-statistic>
        </el-col>
        <el-col :span="4">
          <el-statistic title="在线" :value="statistics.reachable_count">
            <template #prefix>
              <el-icon style="color: #67c23a"><Connection /></el-icon>
            </template>
          </el-statistic>
        </el-col>
        <el-col :span="4">
          <el-statistic title="离线" :value="statistics.offline_ips">
            <template #prefix>
              <el-icon style="color: #f56c6c"><Close /></el-icon>
            </template>
          </el-statistic>
        </el-col>
        <el-col :span="4">
          <el-statistic title="利用率" :value="statistics.utilization_percent" suffix="%" />
        </el-col>
      </el-row>

      <!-- Filters -->
      <el-row :gutter="20" style="margin-bottom: 20px">
        <el-col :span="6">
          <el-select v-model="filters.status" placeholder="状态筛选" clearable @change="loadIPs">
            <el-option label="全部" value="" />
            <el-option label="可用" value="available" />
            <el-option label="已使用" value="used" />
            <el-option label="保留" value="reserved" />
            <el-option label="离线" value="offline" />
          </el-select>
        </el-col>
        <el-col :span="6">
          <el-select v-model="filters.is_reachable" placeholder="可达性筛选" clearable @change="loadIPs">
            <el-option label="全部" value="" />
            <el-option label="在线" :value="true" />
            <el-option label="离线" :value="false" />
          </el-select>
        </el-col>
        <el-col :span="12">
          <el-input
            v-model="filters.search"
            placeholder="搜索 IP、主机名或描述"
            clearable
            @change="loadIPs"
          >
            <template #prefix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>
        </el-col>
      </el-row>

      <!-- IP Addresses Table -->
      <el-table :data="ipAddresses" v-loading="loading" stripe style="width: 100%">
        <el-table-column prop="ip_address" label="IP 地址" width="140" fixed>
          <template #default="{ row }">
            <el-tag :type="row.is_reachable ? 'success' : 'info'">
              {{ row.ip_address }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)" size="small">
              {{ getStatusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column prop="hostname" label="主机名" width="180">
          <template #default="{ row }">
            {{ row.hostname || '-' }}
          </template>
        </el-table-column>

        <el-table-column prop="mac_address" label="MAC 地址" width="150">
          <template #default="{ row }">
            {{ row.mac_address || '-' }}
          </template>
        </el-table-column>

        <el-table-column label="操作系统" width="200">
          <template #default="{ row }">
            <div v-if="row.os_name">
              <div style="font-weight: bold">{{ row.os_name }}</div>
              <div style="font-size: 12px; color: #909399">
                {{ row.os_vendor }} {{ row.os_version }}
              </div>
            </div>
            <span v-else>-</span>
          </template>
        </el-table-column>

        <el-table-column label="交换机端口" width="200">
          <template #default="{ row }">
            <div v-if="row.switch_name">
              <div>{{ row.switch_name }}</div>
              <div style="font-size: 12px; color: #909399">
                {{ row.switch_port }}
                <span v-if="row.vlan_id"> (VLAN {{ row.vlan_id }})</span>
              </div>
            </div>
            <span v-else>-</span>
          </template>
        </el-table-column>

        <el-table-column label="响应时间" width="100">
          <template #default="{ row }">
            <span v-if="row.response_time">{{ row.response_time }} ms</span>
            <span v-else>-</span>
          </template>
        </el-table-column>

        <el-table-column label="最后在线" width="180">
          <template #default="{ row }">
            {{ row.last_seen_at ? formatDate(row.last_seen_at) : '从未在线' }}
          </template>
        </el-table-column>

        <el-table-column prop="description" label="描述" min-width="150">
          <template #default="{ row }">
            {{ row.description || '-' }}
          </template>
        </el-table-column>

        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button
              size="small"
              type="primary"
              @click="viewIPDetail(row)"
              :icon="View"
            >
              详情
            </el-button>
            <el-button
              size="small"
              @click="editIP(row)"
              :icon="Edit"
            >
              编辑
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- Pagination -->
      <el-pagination
        v-model:current-page="pagination.page"
        v-model:page-size="pagination.pageSize"
        :page-sizes="[50, 100, 200, 500]"
        :total="pagination.total"
        layout="total, sizes, prev, pager, next, jumper"
        @size-change="loadIPs"
        @current-change="loadIPs"
        style="margin-top: 20px; justify-content: center"
      />
    </el-card>

    <!-- Edit IP Dialog -->
    <el-dialog v-model="showEditDialog" title="编辑 IP 地址" width="500px">
      <el-form :model="editForm" label-width="100px">
        <el-form-item label="IP 地址">
          <el-input v-model="editForm.ip_address" disabled />
        </el-form-item>

        <el-form-item label="状态">
          <el-select v-model="editForm.status">
            <el-option label="可用" value="available" />
            <el-option label="已使用" value="used" />
            <el-option label="保留" value="reserved" />
            <el-option label="离线" value="offline" />
          </el-select>
        </el-form-item>

        <el-form-item label="主机名">
          <el-input v-model="editForm.hostname" />
        </el-form-item>

        <el-form-item label="MAC 地址">
          <el-input v-model="editForm.mac_address" />
        </el-form-item>

        <el-form-item label="描述">
          <el-input v-model="editForm.description" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="showEditDialog = false">取消</el-button>
        <el-button type="primary" @click="handleEditIP">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Back, Refresh, Check, CircleClose, Connection, Close, Search, View, Edit
} from '@element-plus/icons-vue'
import axios from 'axios'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const scanning = ref(false)
const showEditDialog = ref(false)

const subnetId = parseInt(route.params.id as string)

const subnet = ref<any>({})
const statistics = ref<any>({})
const ipAddresses = ref<any[]>([])

const filters = reactive({
  status: '',
  is_reachable: '' as boolean | string,
  search: ''
})

const pagination = reactive({
  page: 1,
  pageSize: 100,
  total: 0
})

const editForm = reactive({
  id: 0,
  ip_address: '',
  status: 'available',
  hostname: '',
  mac_address: '',
  description: ''
})

const loadSubnet = async () => {
  try {
    const response = await axios.get(`/api/v1/ipam/subnets/${subnetId}`)
    subnet.value = response.data
  } catch (error) {
    ElMessage.error('加载子网信息失败')
  }
}

const loadStatistics = async () => {
  try {
    const response = await axios.get(`/api/v1/ipam/subnets/${subnetId}/statistics`)
    statistics.value = response.data
  } catch (error) {
    ElMessage.error('加载统计信息失败')
  }
}

const loadIPs = async () => {
  loading.value = true
  try {
    const params: any = {
      subnet_id: subnetId,
      skip: (pagination.page - 1) * pagination.pageSize,
      limit: pagination.pageSize
    }

    if (filters.status) params.status = filters.status
    if (filters.is_reachable !== '') params.is_reachable = filters.is_reachable
    if (filters.search) params.search = filters.search

    const response = await axios.get('/api/v1/ipam/ip-addresses', { params })
    ipAddresses.value = response.data

    // Note: In a real implementation, you'd get total count from API
    pagination.total = response.data.length
  } catch (error) {
    ElMessage.error('加载 IP 地址失败')
  } finally {
    loading.value = false
  }
}

const scanSubnet = async () => {
  scanning.value = true
  try {
    const response = await axios.post('/api/v1/ipam/scan', {
      subnet_id: subnetId,
      scan_type: 'full'
    })

    const result = response.data
    ElMessage.success(
      `扫描完成：${result.reachable} 个在线，${result.unreachable} 个离线，发现 ${result.new_devices} 个新设备`
    )

    loadStatistics()
    loadIPs()
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '扫描失败')
  } finally {
    scanning.value = false
  }
}

const viewIPDetail = (ip: any) => {
  router.push(`/ipam/ip/${ip.id}`)
}

const editIP = (ip: any) => {
  Object.assign(editForm, {
    id: ip.id,
    ip_address: ip.ip_address,
    status: ip.status,
    hostname: ip.hostname || '',
    mac_address: ip.mac_address || '',
    description: ip.description || ''
  })
  showEditDialog.value = true
}

const handleEditIP = async () => {
  try {
    await axios.put(`/api/v1/ipam/ip-addresses/${editForm.id}`, {
      status: editForm.status,
      hostname: editForm.hostname,
      mac_address: editForm.mac_address,
      description: editForm.description
    })

    ElMessage.success('IP 地址已更新')
    showEditDialog.value = false
    loadIPs()
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '更新失败')
  }
}

const getStatusType = (status: string) => {
  const types: Record<string, any> = {
    available: 'info',
    used: 'success',
    reserved: 'warning',
    offline: 'danger'
  }
  return types[status] || 'info'
}

const getStatusLabel = (status: string) => {
  const labels: Record<string, string> = {
    available: '可用',
    used: '已使用',
    reserved: '保留',
    offline: '离线'
  }
  return labels[status] || status
}

const formatDate = (dateString: string) => {
  const date = new Date(dateString)
  return date.toLocaleString('zh-CN')
}

onMounted(() => {
  loadSubnet()
  loadStatistics()
  loadIPs()
})
</script>

<style scoped>
.subnet-detail-view {
  max-width: 1800px;
  margin: 0 auto;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.card-header h2 {
  margin: 0 0 8px 0;
  color: #303133;
}

.subnet-info {
  font-size: 14px;
  color: #606266;
}
</style>
