<template>
  <div class="discovery-view">
    <el-card>
      <template #header>
        <div class="card-header">
          <h2>批量发现交换机</h2>
          <p class="subtitle">扫描 IP 段自动发现并添加交换机</p>
        </div>
      </template>

      <!-- Step 1: 配置扫描参数 -->
      <el-steps :active="currentStep" align-center style="margin-bottom: 30px">
        <el-step title="配置扫描" description="设置 IP 范围和认证" />
        <el-step title="扫描结果" description="查看发现的交换机" />
        <el-step title="选择添加" description="选择要添加的交换机" />
      </el-steps>

      <!-- Step 1: 扫描配置 -->
      <div v-if="currentStep === 0">
        <el-form :model="scanForm" :rules="scanRules" ref="scanFormRef" label-width="120px">
          <el-form-item label="IP 范围" prop="ip_range">
            <el-input
              v-model="scanForm.ip_range"
              placeholder="例如: 10.0.0.1-10.0.0.50 或 10.0.0.0/24"
            >
              <template #prepend>
                <el-icon><Search /></el-icon>
              </template>
            </el-input>
            <div class="form-tip">
              支持格式：10.0.0.1-10.0.0.50（范围）或 10.0.0.0/24（CIDR）
            </div>
          </el-form-item>

          <el-divider content-position="left">SSH 认证配置</el-divider>

          <div v-for="(cred, index) in scanForm.credentials" :key="index" class="credential-group">
            <el-card shadow="hover">
              <template #header>
                <div class="credential-header">
                  <span>认证组 {{ index + 1 }}</span>
                  <el-button
                    v-if="scanForm.credentials.length > 1"
                    type="danger"
                    size="small"
                    :icon="Delete"
                    circle
                    @click="removeCredential(index)"
                  />
                </div>
              </template>

              <el-row :gutter="20">
                <el-col :span="12">
                  <el-form-item label="用户名" :prop="`credentials.${index}.username`">
                    <el-input v-model="cred.username" placeholder="SSH 用户名" />
                  </el-form-item>
                </el-col>
                <el-col :span="12">
                  <el-form-item label="密码" :prop="`credentials.${index}.password`">
                    <el-input
                      v-model="cred.password"
                      type="password"
                      placeholder="SSH 密码"
                      show-password
                    />
                  </el-form-item>
                </el-col>
              </el-row>

              <el-row :gutter="20">
                <el-col :span="12">
                  <el-form-item label="Enable 密码">
                    <el-input
                      v-model="cred.enable_password"
                      type="password"
                      placeholder="Cisco Enable 密码（可选）"
                      show-password
                    />
                  </el-form-item>
                </el-col>
                <el-col :span="12">
                  <el-form-item label="SSH 端口">
                    <el-input-number v-model="cred.port" :min="1" :max="65535" />
                  </el-form-item>
                </el-col>
              </el-row>
            </el-card>
          </div>

          <el-button
            type="primary"
            plain
            :icon="Plus"
            @click="addCredential"
            style="width: 100%; margin-top: 10px"
          >
            添加另一组认证
          </el-button>

          <el-form-item style="margin-top: 30px">
            <el-button
              type="primary"
              size="large"
              :loading="scanning"
              @click="startScan"
              style="width: 100%"
            >
              <el-icon v-if="!scanning"><Search /></el-icon>
              {{ scanning ? '扫描中...' : '开始扫描' }}
            </el-button>
          </el-form-item>
        </el-form>
      </div>

      <!-- Step 2: 扫描结果 -->
      <div v-if="currentStep === 1">
        <el-alert
          v-if="scanResult"
          :title="`扫描完成：共扫描 ${scanResult.total_scanned} 个 IP，发现 ${scanResult.discovered} 个交换机`"
          type="success"
          :closable="false"
          style="margin-bottom: 20px"
        />

        <el-table
          :data="scanResult?.switches || []"
          stripe
          style="width: 100%"
          @selection-change="handleSelectionChange"
        >
          <el-table-column type="selection" width="55" />
          <el-table-column prop="name" label="名称" width="180" />
          <el-table-column prop="ip_address" label="IP 地址" width="150">
            <template #default="{ row }">
              <el-tag type="primary">{{ row.ip_address }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="vendor" label="厂商" width="120">
            <template #default="{ row }">
              <el-tag :type="getVendorTagType(row.vendor)">
                {{ row.vendor.toUpperCase() }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="model" label="型号" width="200" />
          <el-table-column prop="role" label="角色" width="120">
            <template #default="{ row }">
              <el-tag :type="getRoleTagType(row.role)">
                {{ getRoleLabel(row.role) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="priority" label="优先级" width="100">
            <template #default="{ row }">
              <el-tag :type="getPriorityTagType(row.priority)">
                {{ row.priority }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="username" label="用户名" width="120" />
        </el-table>

        <div class="action-buttons">
          <el-button @click="currentStep = 0">返回重新扫描</el-button>
          <el-button
            type="primary"
            :disabled="selectedSwitches.length === 0"
            @click="currentStep = 2"
          >
            下一步：添加选中的交换机 ({{ selectedSwitches.length }})
          </el-button>
        </div>
      </div>

      <!-- Step 3: 确认添加 -->
      <div v-if="currentStep === 2">
        <el-alert
          :title="`即将添加 ${selectedSwitches.length} 个交换机到系统`"
          type="info"
          :closable="false"
          style="margin-bottom: 20px"
        />

        <el-table :data="selectedSwitches" stripe style="width: 100%">
          <el-table-column prop="name" label="名称" />
          <el-table-column prop="ip_address" label="IP 地址" />
          <el-table-column prop="vendor" label="厂商" />
          <el-table-column prop="role" label="角色" />
          <el-table-column prop="priority" label="优先级" />
        </el-table>

        <div class="action-buttons">
          <el-button @click="currentStep = 1">返回</el-button>
          <el-button
            type="primary"
            :loading="adding"
            @click="batchAddSwitches"
          >
            {{ adding ? '添加中...' : '确认添加' }}
          </el-button>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Search, Plus, Delete } from '@element-plus/icons-vue'
import apiClient from '@/api'

const router = useRouter()
const currentStep = ref(0)
const scanning = ref(false)
const adding = ref(false)
const scanFormRef = ref<FormInstance>()

interface Credential {
  username: string
  password: string
  enable_password?: string
  port: number
}

interface DiscoveredSwitch {
  name: string
  ip_address: string
  vendor: string
  model: string
  role: string
  priority: number
  ssh_port: number
  username: string
}

const scanForm = reactive({
  ip_range: '',
  credentials: [
    {
      username: '',
      password: '',
      enable_password: '',
      port: 22
    }
  ] as Credential[]
})

const scanRules: FormRules = {
  ip_range: [
    { required: true, message: 'IP 范围不能为空', trigger: 'blur' }
  ]
}

const scanResult = ref<any>(null)
const selectedSwitches = ref<DiscoveredSwitch[]>([])
const discoveredSwitchesWithPassword = ref<any[]>([])

const addCredential = () => {
  scanForm.credentials.push({
    username: '',
    password: '',
    enable_password: '',
    port: 22
  })
}

const removeCredential = (index: number) => {
  scanForm.credentials.splice(index, 1)
}

const startScan = async () => {
  if (!scanFormRef.value) return

  await scanFormRef.value.validate(async (valid) => {
    if (!valid) return

    // 验证至少有一组完整的认证
    const validCredentials = scanForm.credentials.filter(
      c => c.username && c.password
    )

    if (validCredentials.length === 0) {
      ElMessage.error('请至少填写一组完整的用户名和密码')
      return
    }

    scanning.value = true

    try {
      const response = await apiClient.post('/api/v1/discovery/scan', {
        ip_range: scanForm.ip_range,
        credentials: validCredentials
      })

      scanResult.value = response.data
      discoveredSwitchesWithPassword.value = response.data.switches.map((sw: any, index: number) => ({
        ...sw,
        password: validCredentials[0].password,
        enable_password: validCredentials[0].enable_password
      }))

      if (scanResult.value.discovered === 0) {
        ElMessage.warning('未发现任何交换机，请检查 IP 范围和认证信息')
      } else {
        ElMessage.success(`成功发现 ${scanResult.value.discovered} 个交换机`)
        currentStep.value = 1
      }
    } catch (error: any) {
      ElMessage.error(error.response?.data?.detail || '扫描失败')
    } finally {
      scanning.value = false
    }
  })
}

const handleSelectionChange = (selection: any[]) => {
  selectedSwitches.value = selection.map(sw => {
    const fullSwitch = discoveredSwitchesWithPassword.value.find(
      d => d.ip_address === sw.ip_address
    )
    return fullSwitch || sw
  })
}

const batchAddSwitches = async () => {
  adding.value = true

  try {
    const switchesToAdd = selectedSwitches.value.map(sw => ({
      name: sw.name,
      ip_address: sw.ip_address,
      vendor: sw.vendor,
      model: sw.model || '',
      role: sw.role,
      priority: sw.priority,
      ssh_port: sw.ssh_port,
      username: sw.username,
      password: (sw as any).password,
      enable_password: (sw as any).enable_password || '',
      connection_timeout: 30,
      enabled: true
    }))

    await apiClient.post('/api/v1/discovery/batch-add', switchesToAdd)

    ElMessage.success(`成功添加 ${selectedSwitches.value.length} 个交换机`)

    // 跳转到交换机列表页面
    router.push('/switches')
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '批量添加失败')
  } finally {
    adding.value = false
  }
}

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
</script>

<style scoped>
.discovery-view {
  max-width: 1400px;
  margin: 0 auto;
}

.card-header h2 {
  margin: 0 0 8px 0;
  color: #303133;
}

.subtitle {
  margin: 0;
  color: #909399;
  font-size: 14px;
}

.form-tip {
  font-size: 12px;
  color: #909399;
  margin-top: 5px;
}

.credential-group {
  margin-bottom: 15px;
}

.credential-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.action-buttons {
  margin-top: 20px;
  display: flex;
  justify-content: space-between;
}
</style>
