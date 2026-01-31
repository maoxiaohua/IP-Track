<template>
  <div class="ipam-view">
    <el-card>
      <template #header>
        <div class="card-header">
          <h2>IPAM - IP 地址管理</h2>
          <el-button type="primary" @click="showAddSubnetDialog = true">
            <el-icon><Plus /></el-icon>
            添加子网
          </el-button>
        </div>
      </template>

      <!-- Statistics Overview -->
      <el-row :gutter="20" style="margin-bottom: 20px">
        <el-col :span="6">
          <el-statistic title="总子网数" :value="dashboard.total_subnets">
            <template #prefix>
              <el-icon><Grid /></el-icon>
            </template>
          </el-statistic>
        </el-col>
        <el-col :span="6">
          <el-statistic title="总 IP 数" :value="dashboard.total_ips">
            <template #prefix>
              <el-icon><Connection /></el-icon>
            </template>
          </el-statistic>
        </el-col>
        <el-col :span="6">
          <el-statistic title="已使用" :value="dashboard.used_ips">
            <template #prefix>
              <el-icon style="color: #67c23a"><Check /></el-icon>
            </template>
          </el-statistic>
        </el-col>
        <el-col :span="6">
          <el-statistic title="利用率" :value="dashboard.overall_utilization" suffix="%">
            <template #prefix>
              <el-icon><PieChart /></el-icon>
            </template>
          </el-statistic>
        </el-col>
      </el-row>

      <!-- Subnets Table -->
      <el-table :data="subnets" v-loading="loading" stripe style="width: 100%">
        <el-table-column prop="name" label="子网名称" width="180" />

        <el-table-column prop="network" label="网络" width="150">
          <template #default="{ row }">
            <el-tag type="primary">{{ row.network }}</el-tag>
          </template>
        </el-table-column>

        <el-table-column label="IP 统计" width="200">
          <template #default="{ row }">
            <div style="font-size: 12px">
              <div>总数: {{ row.total_ips }}</div>
              <div>已用: <span style="color: #67c23a">{{ row.used_ips }}</span></div>
              <div>可用: <span style="color: #909399">{{ row.available_ips }}</span></div>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="利用率" width="150">
          <template #default="{ row }">
            <el-progress
              :percentage="row.utilization_percent"
              :color="getUtilizationColor(row.utilization_percent)"
            />
          </template>
        </el-table-column>

        <el-table-column prop="vlan_id" label="VLAN" width="80" />

        <el-table-column label="自动扫描" width="100">
          <template #default="{ row }">
            <el-tag :type="row.auto_scan ? 'success' : 'info'" size="small">
              {{ row.auto_scan ? '启用' : '禁用' }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="最后扫描" width="180">
          <template #default="{ row }">
            {{ row.last_scan_at ? formatDate(row.last_scan_at) : '从未扫描' }}
          </template>
        </el-table-column>

        <el-table-column label="操作" width="250" fixed="right">
          <template #default="{ row }">
            <el-button
              size="small"
              type="primary"
              @click="viewSubnetIPs(row)"
              :icon="View"
            >
              查看 IP
            </el-button>
            <el-button
              size="small"
              type="success"
              @click="scanSubnet(row)"
              :icon="Refresh"
              :loading="scanning[row.id]"
            >
              扫描
            </el-button>
            <el-button
              size="small"
              type="danger"
              @click="deleteSubnet(row)"
              :icon="Delete"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- Add Subnet Dialog -->
    <el-dialog
      v-model="showAddSubnetDialog"
      title="添加 IP 子网"
      width="600px"
    >
      <el-form :model="subnetForm" :rules="subnetRules" ref="subnetFormRef" label-width="120px">
        <el-form-item label="子网名称" prop="name">
          <el-input v-model="subnetForm.name" placeholder="例如: 办公网络" />
        </el-form-item>

        <el-form-item label="网络地址" prop="network">
          <el-input v-model="subnetForm.network" placeholder="例如: 10.0.0.0/24">
            <template #append>CIDR</template>
          </el-input>
          <div class="form-tip">
            支持 CIDR 格式，如 10.0.0.0/24 或 192.168.1.0/24
          </div>
        </el-form-item>

        <el-form-item label="描述">
          <el-input
            v-model="subnetForm.description"
            type="textarea"
            :rows="2"
            placeholder="子网用途描述"
          />
        </el-form-item>

        <el-form-item label="VLAN ID">
          <el-input-number v-model="subnetForm.vlan_id" :min="1" :max="4094" />
        </el-form-item>

        <el-form-item label="网关">
          <el-input v-model="subnetForm.gateway" placeholder="例如: 10.0.0.1" />
        </el-form-item>

        <el-form-item label="DNS 服务器">
          <el-input
            v-model="subnetForm.dns_servers"
            placeholder="例如: 8.8.8.8,8.8.4.4"
          />
          <div class="form-tip">多个 DNS 用逗号分隔</div>
        </el-form-item>

        <el-form-item label="自动扫描">
          <el-switch v-model="subnetForm.auto_scan" />
        </el-form-item>

        <el-form-item label="扫描间隔" v-if="subnetForm.auto_scan">
          <el-input-number v-model="subnetForm.scan_interval" :min="300" :max="86400" />
          <span style="margin-left: 8px">秒</span>
          <div class="form-tip">建议: 3600 秒 (1 小时)</div>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="showAddSubnetDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleAddSubnet">
          创建
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import {
  Plus, Grid, Connection, Check, PieChart, View, Refresh, Delete
} from '@element-plus/icons-vue'
import axios from 'axios'

const router = useRouter()
const loading = ref(false)
const saving = ref(false)
const showAddSubnetDialog = ref(false)
const subnetFormRef = ref<FormInstance>()
const scanning = ref<Record<number, boolean>>({})

interface Dashboard {
  total_subnets: number
  total_ips: number
  used_ips: number
  available_ips: number
  offline_ips: number
  overall_utilization: number
  subnets: any[]
  recent_changes: any[]
}

const dashboard = ref<Dashboard>({
  total_subnets: 0,
  total_ips: 0,
  used_ips: 0,
  available_ips: 0,
  offline_ips: 0,
  overall_utilization: 0,
  subnets: [],
  recent_changes: []
})

const subnets = ref<any[]>([])

const subnetForm = reactive({
  name: '',
  network: '',
  description: '',
  vlan_id: null as number | null,
  gateway: '',
  dns_servers: '',
  auto_scan: true,
  scan_interval: 3600
})

const subnetRules: FormRules = {
  name: [{ required: true, message: '请输入子网名称', trigger: 'blur' }],
  network: [
    { required: true, message: '请输入网络地址', trigger: 'blur' },
    {
      pattern: /^(\d{1,3}\.){3}\d{1,3}\/\d{1,2}$/,
      message: '请输入有效的 CIDR 格式，如 10.0.0.0/24',
      trigger: 'blur'
    }
  ]
}

const loadDashboard = async () => {
  loading.value = true
  try {
    const response = await axios.get('/api/v1/ipam/dashboard')
    dashboard.value = response.data
    subnets.value = response.data.subnets
  } catch (error) {
    ElMessage.error('加载仪表板失败')
  } finally {
    loading.value = false
  }
}

const handleAddSubnet = async () => {
  if (!subnetFormRef.value) return

  await subnetFormRef.value.validate(async (valid) => {
    if (!valid) return

    saving.value = true
    try {
      await axios.post('/api/v1/ipam/subnets', subnetForm)
      ElMessage.success('子网创建成功')
      showAddSubnetDialog.value = false
      resetForm()
      loadDashboard()
    } catch (error: any) {
      ElMessage.error(error.response?.data?.detail || '创建子网失败')
    } finally {
      saving.value = false
    }
  })
}

const resetForm = () => {
  Object.assign(subnetForm, {
    name: '',
    network: '',
    description: '',
    vlan_id: null,
    gateway: '',
    dns_servers: '',
    auto_scan: true,
    scan_interval: 3600
  })
  subnetFormRef.value?.clearValidate()
}

const viewSubnetIPs = (subnet: any) => {
  router.push(`/ipam/subnets/${subnet.subnet_id}`)
}

const scanSubnet = async (subnet: any) => {
  scanning.value[subnet.subnet_id] = true
  try {
    const response = await axios.post('/api/v1/ipam/scan', {
      subnet_id: subnet.subnet_id,
      scan_type: 'full'
    })

    const result = response.data
    ElMessage.success(
      `扫描完成：${result.reachable} 个在线，${result.unreachable} 个离线`
    )
    loadDashboard()
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '扫描失败')
  } finally {
    scanning.value[subnet.subnet_id] = false
  }
}

const deleteSubnet = async (subnet: any) => {
  try {
    await ElMessageBox.confirm(
      `确定要删除子网 "${subnet.subnet_name}" 吗？这将删除该子网下的所有 IP 地址记录。`,
      '警告',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )

    await axios.delete(`/api/v1/ipam/subnets/${subnet.subnet_id}`)
    ElMessage.success('子网已删除')
    loadDashboard()
  } catch (error: any) {
    if (error !== 'cancel') {
      ElMessage.error(error.response?.data?.detail || '删除失败')
    }
  }
}

const getUtilizationColor = (percent: number) => {
  if (percent < 50) return '#67c23a'
  if (percent < 80) return '#e6a23c'
  return '#f56c6c'
}

const formatDate = (dateString: string) => {
  const date = new Date(dateString)
  return date.toLocaleString('zh-CN')
}

onMounted(() => {
  loadDashboard()
})
</script>

<style scoped>
.ipam-view {
  max-width: 1600px;
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

.form-tip {
  font-size: 12px;
  color: #909399;
  margin-top: 5px;
}
</style>
