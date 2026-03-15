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
                  <span>SSH 认证组 {{ index + 1 }}</span>
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
                  <el-form-item label="SSH用户名" :prop="`credentials.${index}.username`">
                    <el-input v-model="cred.username" placeholder="SSH 用户名" />
                  </el-form-item>
                </el-col>
                <el-col :span="12">
                  <el-form-item label="SSH密码" :prop="`credentials.${index}.password`">
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
                      placeholder="Enable 密码（可选）"
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

          <el-divider content-position="left">SNMP 认证配置（用于设备识别）</el-divider>
          <div class="form-tip" style="margin-bottom: 12px">
            SNMP 用于获取设备的主机名、厂商和型号信息，SSH 用于网络连接验证
          </div>

          <el-card shadow="hover" style="margin-bottom: 15px">
            <el-row :gutter="20">
              <el-col :span="12">
                <el-form-item label="SNMP 版本">
                  <el-select v-model="snmpConfig.snmp_version" style="width: 100%">
                    <el-option label="SNMPv3（推荐）" value="3" />
                    <el-option label="SNMPv2c" value="2c" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="SNMP 端口">
                  <el-input-number v-model="snmpConfig.snmp_port" :min="1" :max="65535" style="width: 100%" />
                </el-form-item>
              </el-col>
            </el-row>

            <template v-if="snmpConfig.snmp_version === '3'">
              <el-row :gutter="20">
                <el-col :span="12">
                  <el-form-item label="SNMP 用户名">
                    <el-input v-model="snmpConfig.snmp_username" placeholder="SNMPv3 用户名" />
                  </el-form-item>
                </el-col>
                <el-col :span="12">
                  <el-form-item label="认证协议">
                    <el-select v-model="snmpConfig.snmp_auth_protocol" style="width: 100%">
                      <el-option label="SHA" value="SHA" />
                      <el-option label="MD5" value="MD5" />
                      <el-option label="SHA256" value="SHA256" />
                    </el-select>
                  </el-form-item>
                </el-col>
              </el-row>
              <el-row :gutter="20">
                <el-col :span="12">
                  <el-form-item label="认证密码">
                    <el-input
                      v-model="snmpConfig.snmp_auth_password"
                      type="password"
                      placeholder="至少8个字符"
                      show-password
                    />
                  </el-form-item>
                </el-col>
                <el-col :span="12">
                  <el-form-item label="加密协议">
                    <el-select v-model="snmpConfig.snmp_priv_protocol" style="width: 100%">
                      <el-option label="AES128（推荐）" value="AES128" />
                      <el-option label="AES192" value="AES192" />
                      <el-option label="AES256" value="AES256" />
                      <el-option label="DES" value="DES" />
                    </el-select>
                  </el-form-item>
                </el-col>
              </el-row>
              <el-row :gutter="20">
                <el-col :span="12">
                  <el-form-item label="加密密码">
                    <el-input
                      v-model="snmpConfig.snmp_priv_password"
                      type="password"
                      placeholder="至少8个字符"
                      show-password
                    />
                  </el-form-item>
                </el-col>
              </el-row>
            </template>

            <template v-if="snmpConfig.snmp_version === '2c'">
              <el-row :gutter="20">
                <el-col :span="12">
                  <el-form-item label="Community">
                    <el-input v-model="snmpConfig.snmp_community" placeholder="SNMP Community String" />
                  </el-form-item>
                </el-col>
              </el-row>
            </template>
          </el-card>

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

        <!-- Progress Display -->
        <el-card v-if="scanning" shadow="never" style="margin-top: 20px" class="progress-card">
          <template #header>
            <div style="display: flex; align-items: center; gap: 10px;">
              <el-icon class="is-loading"><Loading /></el-icon>
              <span>扫描进度</span>
            </div>
          </template>
          
          <div class="progress-stats">
            <el-statistic title="总计 IP" :value="progressStats.totalIPs" />
            <el-statistic title="已发现" :value="progressStats.discovered">
              <template #suffix>
                <span style="color: #67C23A">台</span>
              </template>
            </el-statistic>
            <el-statistic title="失败" :value="progressStats.failed">
              <template #suffix>
                <span style="color: #F56C6C">台</span>
              </template>
            </el-statistic>
          </div>

          <el-divider style="margin: 15px 0" />

          <div class="progress-log">
            <div class="log-title">实时日志</div>
            <div class="log-container" ref="logContainer">
              <div 
                v-for="(log, index) in progressLogs" 
                :key="index" 
                class="log-item"
                :class="`log-${log.type}`"
              >
                <span class="log-time">{{ log.time }}</span>
                <span class="log-ip">{{ log.ip }}</span>
                <span class="log-message">{{ log.message }}</span>
              </div>
              <div v-if="progressLogs.length === 0" class="log-empty">
                等待扫描开始...
              </div>
            </div>
          </div>
        </el-card>
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
          <el-table-column prop="ssh_port" label="SSH端口" width="100" />
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
          :title="`即将添加 ${selectedSwitches.length} 个交换机到系统（SNMP 认证已在第一步配置）`"
          type="info"
          :closable="false"
          style="margin-bottom: 20px"
        />

        <el-card shadow="hover">
          <template #header>
            <h3 style="margin: 0">选中的交换机列表</h3>
          </template>
          <el-table :data="selectedSwitches" stripe style="width: 100%">
            <el-table-column prop="name" label="名称" />
            <el-table-column prop="ip_address" label="IP 地址" />
            <el-table-column prop="vendor" label="厂商" />
            <el-table-column prop="model" label="型号" />
            <el-table-column prop="username" label="SSH用户名" />
          </el-table>
        </el-card>

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
import { ref, reactive, nextTick, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Search, Plus, Delete, Loading } from '@element-plus/icons-vue'
import apiClient, { API_BASE_URL } from '@/api'

const router = useRouter()
const currentStep = ref(0)
const scanning = ref(false)
const adding = ref(false)
const scanFormRef = ref<FormInstance>()
const logContainer = ref<HTMLElement>()

interface Credential {
  username: string
  password: string
  enable_password: string
  port: number
}

interface DiscoveredSwitch {
  name: string
  ip_address: string
  vendor: string
  model: string
  ssh_port: number
  username: string
}

interface ProgressLog {
  time: string
  ip: string
  message: string
  type: 'info' | 'success' | 'warning' | 'error'
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

// SNMP configuration for batch adding
const snmpConfig = reactive({
  snmp_version: '3',
  snmp_port: 161,
  snmp_username: '',
  snmp_auth_protocol: 'SHA',
  snmp_auth_password: '',
  snmp_priv_protocol: 'AES128',
  snmp_priv_password: '',
  snmp_community: ''  // For SNMPv2c
})

const scanRules: FormRules = {
  ip_range: [
    { required: true, message: 'IP 范围不能为空', trigger: 'blur' }
  ]
}

const scanResult = ref<any>(null)
const selectedSwitches = ref<DiscoveredSwitch[]>([])
const discoveredSwitchesWithPassword = ref<any[]>([])

// Progress tracking
const progressStats = reactive({
  totalIPs: 0,
  discovered: 0,
  failed: 0
})

const progressLogs = ref<ProgressLog[]>([])
let eventSource: EventSource | null = null
let scanCompleted = false  // true once 'complete'/'done' received; prevents onerror false-alarm

// Track IP status to avoid duplicate counting
const discoveredIPs = new Set<string>()
const failedIPs = new Set<string>()

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

const formatTime = () => {
  const now = new Date()
  return `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}`
}

const addLog = (ip: string, message: string, type: ProgressLog['type'] = 'info') => {
  progressLogs.value.push({
    time: formatTime(),
    ip,
    message,
    type
  })
  
  // Auto scroll to bottom
  nextTick(() => {
    if (logContainer.value) {
      logContainer.value.scrollTop = logContainer.value.scrollHeight
    }
  })
  
  // Keep only last 100 logs
  if (progressLogs.value.length > 100) {
    progressLogs.value.shift()
  }
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
    scanCompleted = false
    progressLogs.value = []
    progressStats.totalIPs = 0
    progressStats.discovered = 0
    progressStats.failed = 0
    discoveredIPs.clear()
    failedIPs.clear()
    sessionStorage.removeItem('discovery_session_id')

    try {
      // Start scan with streaming
      const response = await apiClient.post('/api/v1/discovery/scan-stream', {
        ip_range: scanForm.ip_range,
        credentials: validCredentials,
        snmp_config: {
          snmp_version: snmpConfig.snmp_version,
          snmp_port: snmpConfig.snmp_port,
          snmp_username: snmpConfig.snmp_version === '3' ? snmpConfig.snmp_username : undefined,
          snmp_auth_protocol: snmpConfig.snmp_version === '3' ? snmpConfig.snmp_auth_protocol : undefined,
          snmp_auth_password: snmpConfig.snmp_version === '3' ? snmpConfig.snmp_auth_password : undefined,
          snmp_priv_protocol: snmpConfig.snmp_version === '3' ? snmpConfig.snmp_priv_protocol : undefined,
          snmp_priv_password: snmpConfig.snmp_version === '3' ? snmpConfig.snmp_priv_password : undefined,
          snmp_community: snmpConfig.snmp_version === '2c' ? snmpConfig.snmp_community : undefined
        }
      })

      const sessionId = response.data.session_id
      
      addLog('系统', '扫描任务已启动', 'info')

      // Connect to SSE stream with full URL
      const sseUrl = `${API_BASE_URL}/api/v1/discovery/progress/${sessionId}`
      console.log('Connecting to SSE:', sseUrl)
      eventSource = new EventSource(sseUrl)

      eventSource.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          
          switch (data.type) {
            case 'start':
              progressStats.totalIPs = data.total_ips
              addLog('系统', `开始扫描 ${data.total_ips} 个 IP 地址`, 'info')
              break
              
            case 'attempt':
              const status = data.attempt > 1 ? `重试 ${data.attempt}/${data.max_attempts}` : '连接中'
              addLog(data.ip, `${status}...`, 'info')
              break
              
            case 'success':
              // Only count each IP once
              if (!discoveredIPs.has(data.ip)) {
                discoveredIPs.add(data.ip)
                progressStats.discovered++
              }
              addLog(data.ip, `发现: ${data.name} (${data.vendor})`, 'success')
              break
              
            case 'failed':
              // Only count as failed if not already discovered
              if (!discoveredIPs.has(data.ip) && !failedIPs.has(data.ip)) {
                failedIPs.add(data.ip)
                progressStats.failed++
              }
              addLog(data.ip, `失败: ${data.error}`, 'error')
              break
              
            case 'complete':
            case 'done':
              scanCompleted = true
              addLog('系统', `扫描完成! 发现 ${data.total_found} 台交换机`, 'success')
              if (eventSource) {
                eventSource.close()
                eventSource = null
              }
              // Use data embedded in the SSE event directly — no second HTTP request needed.
              if (data.switches) {
                scanResult.value = {
                  total_scanned: data.total_scanned ?? data.total_found,
                  discovered: data.total_found,
                  switches: data.switches
                }
                discoveredSwitchesWithPassword.value = data.switches.map((sw: any) => ({
                  ...sw,
                  password: validCredentials[0]?.password ?? '',
                  enable_password: validCredentials[0]?.enable_password ?? ''
                }))
                sessionStorage.setItem('discovery_session_id', sessionId)
                if (data.total_found === 0) {
                  ElMessage.warning('未发现任何交换机，请检查 IP 范围和认证信息')
                } else {
                  ElMessage.success(`成功发现 ${data.total_found} 个交换机`)
                  currentStep.value = 1
                }
                scanning.value = false
              } else {
                // Fallback: event has no embedded switches, fetch via REST
                handleScanComplete(sessionId, validCredentials)
              }
              break
              
            case 'error':
              ElMessage.error(data.message || '扫描出错')
              addLog('系统', `错误: ${data.message}`, 'error')
              scanning.value = false
              if (eventSource) {
                eventSource.close()
                eventSource = null
              }
              break
          }
        } catch (err) {
          console.error('Error parsing SSE message:', err)
        }
      }

      eventSource.onerror = (error) => {
        if (scanCompleted) {
          // Normal SSE stream close after scan completion — not an error
          if (eventSource) {
            eventSource.close()
            eventSource = null
          }
          return
        }
        // Actual connection error before scan finished
        console.error('SSE error:', error)
        addLog('系统', 'SSE 连接错误，但扫描可能仍在继续...', 'warning')
        if (eventSource) {
          eventSource.close()
          eventSource = null
        }
        // Poll for results instead
        setTimeout(() => {
          if (scanning.value) {
            pollForResults(sessionId, validCredentials)
          }
        }, 2000)
      }

    } catch (error: any) {
      ElMessage.error(error.response?.data?.detail || '扫描启动失败')
      addLog('系统', `启动失败: ${error.response?.data?.detail || error.message}`, 'error')
      scanning.value = false
    }
  })
}

const pollForResults = async (sessionId: string, validCredentials: Credential[]) => {
  // Fallback polling mechanism if SSE fails
  let attempts = 0
  const maxAttempts = 60 // 2 minutes max
  
  const checkResults = async () => {
    try {
      const resultResponse = await apiClient.get(`/api/v1/discovery/result/${sessionId}`)
      if (resultResponse.data && resultResponse.data.switches) {
        await handleScanComplete(sessionId, validCredentials)
        return true
      }
    } catch (error) {
      // Result not ready yet
    }
    
    attempts++
    if (attempts < maxAttempts && scanning.value) {
      setTimeout(checkResults, 2000)
    } else if (attempts >= maxAttempts) {
      addLog('系统', '扫描超时，请检查后端日志', 'error')
      scanning.value = false
    }
  }
  
  checkResults()
}

const handleScanComplete = async (sessionId: string, validCredentials: Credential[]) => {
  try {
    // Close SSE connection
    if (eventSource) {
      eventSource.close()
      eventSource = null
    }

    // Fetch final results
    const resultResponse = await apiClient.get(`/api/v1/discovery/result/${sessionId}`)
    
    scanResult.value = resultResponse.data
    discoveredSwitchesWithPassword.value = resultResponse.data.switches.map((sw: any) => ({
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
    ElMessage.error(error.response?.data?.detail || '获取扫描结果失败')
  } finally {
    scanning.value = false
  }
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
  // Critical check: ensure we have switches selected
  if (!selectedSwitches.value || selectedSwitches.value.length === 0) {
    ElMessage.error('请先选择要添加的交换机')
    return
  }

  // Verify passwords are attached (防御性检查)
  const firstSwitch = selectedSwitches.value[0] as any
  if (!firstSwitch.password) {
    ElMessage.error('交换机密码信息缺失，请返回重新扫描')
    currentStep.value = 0
    return
  }

  // Validate SNMP configuration
  if (snmpConfig.snmp_version === '3') {
    if (!snmpConfig.snmp_username || !snmpConfig.snmp_auth_password || !snmpConfig.snmp_priv_password) {
      ElMessage.error('请填写完整的 SNMPv3 配置（用户名、认证密码、加密密码）')
      return
    }
    if (snmpConfig.snmp_auth_password.length < 8 || snmpConfig.snmp_priv_password.length < 8) {
      ElMessage.error('SNMP 认证密码和加密密码至少需要 8 个字符')
      return
    }
  } else if (snmpConfig.snmp_version === '2c') {
    if (!snmpConfig.snmp_community) {
      ElMessage.error('请填写 SNMP Community String')
      return
    }
  }

  adding.value = true

  try {
    const switchesToAdd = selectedSwitches.value.map(sw => ({
      name: sw.name,
      ip_address: sw.ip_address,
      vendor: sw.vendor,
      model: sw.model || '',
      ssh_port: sw.ssh_port,
      username: sw.username,
      password: (sw as any).password,
      enable_password: (sw as any).enable_password || '',
      connection_timeout: 30,
      enabled: true,
      cli_enabled: true,  // Enable CLI since we have SSH credentials
      auto_collect_arp: true,
      auto_collect_mac: true,
      // SNMP configuration
      snmp_enabled: true,
      snmp_version: snmpConfig.snmp_version,
      snmp_port: snmpConfig.snmp_port,
      snmp_username: snmpConfig.snmp_version === '3' ? snmpConfig.snmp_username : undefined,
      snmp_auth_protocol: snmpConfig.snmp_version === '3' ? snmpConfig.snmp_auth_protocol : undefined,
      snmp_auth_password: snmpConfig.snmp_version === '3' ? snmpConfig.snmp_auth_password : undefined,
      snmp_priv_protocol: snmpConfig.snmp_version === '3' ? snmpConfig.snmp_priv_protocol : undefined,
      snmp_priv_password: snmpConfig.snmp_version === '3' ? snmpConfig.snmp_priv_password : undefined,
      snmp_community: snmpConfig.snmp_version === '2c' ? snmpConfig.snmp_community : undefined
    }))

    console.log('Sending batch-add request with', switchesToAdd.length, 'switches')
    const response = await apiClient.post('/api/v1/discovery/batch-add', switchesToAdd)
    console.log('Batch-add response:', response.data)

    ElMessage.success(`成功添加 ${selectedSwitches.value.length} 个交换机`)
    sessionStorage.removeItem('discovery_session_id')

    // 跳转到交换机列表页面
    router.push('/switches')
  } catch (error: any) {
    console.error('Batch-add error:', error)
    const errorMsg = error.response?.data?.detail || error.message || '批量添加失败'
    ElMessage.error(`批量添加失败: ${errorMsg}`)
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

// Restore results if the user navigated away and came back
onMounted(async () => {
  const savedSessionId = sessionStorage.getItem('discovery_session_id')
  if (!savedSessionId || currentStep.value !== 0 || scanning.value) return
  try {
    const res = await apiClient.get(`/api/v1/discovery/result/${savedSessionId}`)
    if (res.data && res.data.switches && res.data.discovered > 0) {
      scanResult.value = res.data
      discoveredSwitchesWithPassword.value = res.data.switches.map((sw: any) => ({
        ...sw,
        password: '',
        enable_password: ''
      }))
      currentStep.value = 1
      ElMessage.info('已恢复上次扫描结果，密码字段需重新填写后方可添加')
    }
  } catch {
    sessionStorage.removeItem('discovery_session_id')
  }
})
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

/* Progress Card Styles */
.progress-card {
  background: #f5f7fa;
  border: 1px solid #e4e7ed;
}

.progress-stats {
  display: flex;
  justify-content: space-around;
  gap: 20px;
}

.progress-log {
  margin-top: 10px;
}

.log-title {
  font-size: 14px;
  font-weight: 600;
  color: #606266;
  margin-bottom: 10px;
}

.log-container {
  background: #fff;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  padding: 10px;
  max-height: 300px;
  overflow-y: auto;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 12px;
}

.log-item {
  padding: 4px 0;
  border-bottom: 1px solid #f0f0f0;
  display: flex;
  gap: 10px;
}

.log-item:last-child {
  border-bottom: none;
}

.log-time {
  color: #909399;
  min-width: 70px;
}

.log-ip {
  color: #409eff;
  min-width: 120px;
  font-weight: 500;
}

.log-message {
  flex: 1;
  color: #606266;
}

.log-success .log-message {
  color: #67c23a;
}

.log-error .log-message {
  color: #f56c6c;
}

.log-warning .log-message {
  color: #e6a23c;
}

.log-empty {
  color: #909399;
  text-align: center;
  padding: 20px;
}

.is-loading {
  animation: rotating 2s linear infinite;
}

@keyframes rotating {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}
</style>
