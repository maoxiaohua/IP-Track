<template>
  <div class="ipam-simple-view">
    <el-card>
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center">
          <h2 style="margin: 0">IP Address Management</h2>
          <div style="display: flex; gap: 10px">
            <el-button type="info" plain @click="exportToExcel">
              <el-icon><Download /></el-icon>
              导出 Excel
            </el-button>
            <el-button type="success" @click="showBatchImportDialog = true">
              <el-icon><Upload /></el-icon>
              批量导入
            </el-button>
            <el-button type="primary" @click="showAddSubnetDialog = true">
              <el-icon><Plus /></el-icon>
              添加子网
            </el-button>
          </div>
        </div>
      </template>

      <!-- Search Bar -->
      <el-row style="margin-bottom: 20px">
        <el-col :span="12">
          <el-input
            v-model="searchText"
            placeholder="搜索子网（网络地址或子网名称）..."
            clearable
          >
            <template #prefix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>
        </el-col>
      </el-row>

      <!-- Subnet Table (SolarWinds Style) -->
      <el-table
        :data="paginatedSubnets"
        stripe
        v-loading="loading"
        style="width: 100%"
        @row-click="handleRowClick"
        :row-style="{ cursor: 'pointer' }"
      >
        <el-table-column label="Subnet" min-width="200">
          <template #default="{ row }">
            <router-link
              :to="`/ipam/subnets/${row.subnet_id}`"
              style="color: #409eff; text-decoration: none; font-weight: 500"
              @click.stop
            >
              {{ row.network }}
            </router-link>
          </template>
        </el-table-column>

        <el-table-column label="Address" width="150">
          <template #default="{ row }">
            {{ getNetworkAddress(row.network) }}
          </template>
        </el-table-column>

        <el-table-column label="Mask" width="150">
          <template #default="{ row }">
            {{ getSubnetMask(row.network) }}
          </template>
        </el-table-column>

        <el-table-column label="Subnet Size" width="120" align="right">
          <template #default="{ row }">
            {{ row.total_ips || 0 }}
          </template>
        </el-table-column>

        <el-table-column label="Available Addresses" width="160" align="right">
          <template #default="{ row }">
            <span style="color: #67c23a; font-weight: 500">{{ row.available_ips || 0 }}</span>
          </template>
        </el-table-column>

        <el-table-column label="Reserved Addresses" width="160" align="right">
          <template #default="{ row }">
            <span style="color: #f56c6c">{{ row.reserved_ips || 0 }}</span>
          </template>
        </el-table-column>

        <el-table-column label="Used Addresses" width="150" align="right">
          <template #default="{ row }">
            <span style="color: #409eff; font-weight: 500">{{ row.used_ips || 0 }}</span>
          </template>
        </el-table-column>

        <el-table-column label="Last Scan" min-width="180">
          <template #default="{ row }">
            {{ row.last_scan_at ? formatDateTime(row.last_scan_at) : 'Never' }}
          </template>
        </el-table-column>

        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button
              size="small"
              type="primary"
              @click.stop="editSubnet(row)"
            >
              编辑
            </el-button>
            <el-button
              size="small"
              type="success"
              :loading="scanning[row.subnet_id]"
              @click.stop="scanSubnet(row)"
            >
              扫描
            </el-button>
            <el-button
              size="small"
              @click.stop="deleteSubnet(row)"
              type="danger"
              link
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- Pagination -->
      <el-pagination
        v-model:current-page="pagination.currentPage"
        v-model:page-size="pagination.pageSize"
        :page-sizes="[20, 50, 100, 200]"
        :total="filteredSubnets.length"
        layout="total, sizes, prev, pager, next, jumper"
        style="margin-top: 20px; justify-content: center"
      />
    </el-card>

    <!-- Add/Edit Subnet Dialog -->
    <el-dialog
      v-model="showAddSubnetDialog"
      :title="editMode ? '编辑 IP 子网' : '添加 IP 子网'"
      width="600px"
    >
      <el-form :model="subnetForm" ref="subnetFormRef" label-width="120px">
        <el-form-item label="子网名称" required>
          <el-input v-model="subnetForm.name" placeholder="例如: 办公网络" />
        </el-form-item>
        <el-form-item label="网络地址" required>
          <el-input
            v-model="subnetForm.network"
            placeholder="例如: 10.0.0.0/24"
            :disabled="editMode"
          />
        </el-form-item>
        <el-form-item label="网关">
          <el-input v-model="subnetForm.gateway" placeholder="例如: 10.0.0.1" />
        </el-form-item>
        <el-form-item label="VLAN ID">
          <el-input-number v-model="subnetForm.vlan_id" :min="1" :max="4094" />
        </el-form-item>
        <el-form-item label="DNS 服务器">
          <el-input v-model="subnetForm.dns_servers" placeholder="例如: 8.8.8.8,8.8.4.4" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="subnetForm.description" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAddSubnetDialog = false">取消</el-button>
        <el-button type="primary" @click="handleSubmitSubnet">
          {{ editMode ? '保存' : '确定' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- Batch Import Dialog -->
    <el-dialog
      v-model="showBatchImportDialog"
      title="批量导入子网"
      width="800px"
      @close="resetBatchImport"
    >
      <el-alert
        title="导入说明"
        type="info"
        :closable="false"
        style="margin-bottom: 20px"
      >
        <p style="margin: 5px 0">• 推荐使用 <strong>Excel 导入</strong>，更方便直观</p>
        <p style="margin: 5px 0">• 文本导入格式: 网段名称,网络地址,网关,VLAN ID,DNS,描述</p>
        <p style="margin: 5px 0">• 最少需要: 网段名称,网络地址</p>
      </el-alert>

      <!-- Import Method Selection -->
      <el-form-item label="导入方式" style="margin-bottom: 20px">
        <el-radio-group v-model="importMethod">
          <el-radio value="excel">Excel 文件（推荐）</el-radio>
          <el-radio value="text">文本粘贴</el-radio>
        </el-radio-group>
      </el-form-item>

      <!-- Excel Upload -->
      <template v-if="importMethod === 'excel'">
        <el-form-item label="Excel 文件">
          <el-upload
            ref="uploadRef"
            :auto-upload="false"
            :limit="1"
            :on-change="handleFileChange"
            :on-remove="handleFileRemove"
            accept=".xlsx,.xls"
            drag
          >
            <el-icon class="el-icon--upload"><Upload /></el-icon>
            <div class="el-upload__text">
              拖拽文件到这里或 <em>点击上传</em>
            </div>
            <template #tip>
              <div class="el-upload__tip">
                只支持 .xlsx 或 .xls 格式的Excel文件
              </div>
            </template>
          </el-upload>
        </el-form-item>

        <el-button
          type="info"
          plain
          size="small"
          @click="downloadTemplate"
          style="margin-top: 10px"
        >
          <el-icon><Download /></el-icon>
          下载 Excel 导入模板
        </el-button>
      </template>

      <!-- Text Input -->
      <template v-else>
        <el-input
          v-model="batchImportText"
          type="textarea"
          :rows="12"
          placeholder="办公网络,10.0.1.0/24,10.0.1.1,100,8.8.8.8,办公区域&#10;数据中心,172.16.0.0/16,172.16.0.1,200,8.8.8.8;8.8.4.4,DC核心网络&#10;访客网络,192.168.10.0/24,192.168.10.1,300,,访客WiFi"
          :disabled="batchImporting"
        />
      </template>

      <!-- Import Result Display -->
      <div v-if="batchImportResult" style="margin-top: 20px">
        <el-divider />
        <h4 style="margin-bottom: 10px">导入结果</h4>
        <el-descriptions :column="2" border>
          <el-descriptions-item label="总计">{{ batchImportResult.total }}</el-descriptions-item>
          <el-descriptions-item label="成功">
            <el-tag type="success">{{ batchImportResult.success }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="跳过（重复）">
            <el-tag type="warning">{{ batchImportResult.skipped }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="失败">
            <el-tag type="danger">{{ batchImportResult.failed }}</el-tag>
          </el-descriptions-item>
        </el-descriptions>

        <!-- Error Details -->
        <div v-if="batchImportResult.errors && batchImportResult.errors.length > 0" style="margin-top: 15px">
          <h5 style="color: #f56c6c">错误详情:</h5>
          <el-table :data="batchImportResult.errors" size="small" max-height="200">
            <el-table-column prop="index" label="行号" width="80" />
            <el-table-column prop="network" label="网络" width="150" />
            <el-table-column prop="error" label="错误信息" />
          </el-table>
        </div>
      </div>

      <template #footer>
        <el-button @click="showBatchImportDialog = false" :disabled="batchImporting">
          关闭
        </el-button>
        <el-button
          type="primary"
          @click="handleBatchImport"
          :loading="batchImporting"
          :disabled="importMethod === 'excel' ? !excelFile : !batchImportText.trim()"
        >
          {{ batchImporting ? '导入中...' : '开始导入' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Upload, Download, Search } from '@element-plus/icons-vue'
import apiClient from '@/api/index'

interface Subnet {
  subnet_id: number
  subnet_name: string
  network: string
  vlan_id?: number
  gateway?: string
  total_ips: number
  available_ips: number
  used_ips: number
  reserved_ips: number
  utilization_percent: number
  last_scan_at?: string
}

const router = useRouter()
const subnets = ref<Subnet[]>([])
const loading = ref(false)
const scanning = ref<Record<number, boolean>>({})
const showAddSubnetDialog = ref(false)
const showBatchImportDialog = ref(false)
const editMode = ref(false)
const editingSubnetId = ref<number | null>(null)
const subnetFormRef = ref()
const batchImporting = ref(false)
const batchImportText = ref('')
const batchImportResult = ref<any>(null)
const importMethod = ref('excel')
const excelFile = ref<File | null>(null)
const uploadRef = ref()
const searchText = ref('')  // Subnet search

const pagination = ref({
  currentPage: 1,
  pageSize: 200  // Default to 200 rows per page
})

const subnetForm = ref({
  name: '',
  network: '',
  gateway: '',
  vlan_id: undefined as number | undefined,
  dns_servers: '',
  description: '',
  enabled: true,
  auto_scan: true,
  scan_interval: 3600
})

// Filtered subnets based on search text
const filteredSubnets = computed(() => {
  if (!searchText.value.trim()) {
    return subnets.value
  }

  const search = searchText.value.toLowerCase().trim()
  return subnets.value.filter((subnet: Subnet) => {
    const networkMatch = subnet.network.toLowerCase().includes(search)
    const nameMatch = subnet.subnet_name?.toLowerCase().includes(search) || false
    return networkMatch || nameMatch
  })
})

// Paginated subnets from filtered results
const paginatedSubnets = computed(() => {
  const start = (pagination.value.currentPage - 1) * pagination.value.pageSize
  const end = start + pagination.value.pageSize
  return filteredSubnets.value.slice(start, end)
})

// Load subnets
const loadSubnets = async () => {
  loading.value = true
  try {
    const response = await apiClient.get('/api/v1/ipam/dashboard')
    subnets.value = response.data.subnets || []

    // Sort by utilization descending
    subnets.value.sort((a, b) => {
      const aUtil = a.utilization_percent ?? 0
      const bUtil = b.utilization_percent ?? 0
      return bUtil - aUtil
    })
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '加载子网失败')
  } finally {
    loading.value = false
  }
}

// Add/Edit subnet
const handleSubmitSubnet = async () => {
  try {
    if (editMode.value && editingSubnetId.value) {
      // Edit existing subnet - exclude 'network' field (not allowed to modify)
      const { network, ...updateData } = subnetForm.value

      // Clean up empty strings - convert to null for proper API validation
      const cleanedData = {
        ...updateData,
        gateway: updateData.gateway?.trim() || null,
        dns_servers: updateData.dns_servers?.trim() || null,
        description: updateData.description?.trim() || null,
        vlan_id: updateData.vlan_id || null
      }

      console.log('Updating subnet with data:', cleanedData)
      await apiClient.put(`/api/v1/ipam/subnets/${editingSubnetId.value}`, cleanedData)
      ElMessage.success('子网更新成功')
    } else {
      // Add new subnet
      const cleanedData = {
        ...subnetForm.value,
        gateway: subnetForm.value.gateway?.trim() || null,
        dns_servers: subnetForm.value.dns_servers?.trim() || null,
        description: subnetForm.value.description?.trim() || null,
        vlan_id: subnetForm.value.vlan_id || null
      }
      await apiClient.post('/api/v1/ipam/subnets', cleanedData)
      ElMessage.success('子网添加成功')
    }
    showAddSubnetDialog.value = false
    resetForm()
    await loadSubnets()
  } catch (error: any) {
    console.error('Subnet submit error:', error.response?.data)
    ElMessage.error(error.response?.data?.detail || (editMode.value ? '更新子网失败' : '添加子网失败'))
  }
}

// Edit subnet
const editSubnet = async (subnet: Subnet) => {
  editMode.value = true
  editingSubnetId.value = subnet.subnet_id

  // Load complete subnet data from API
  try {
    loading.value = true
    const response = await apiClient.get(`/api/v1/ipam/subnets/${subnet.subnet_id}`)
    const fullSubnetData = response.data

    // Populate form with complete data from API
    subnetForm.value = {
      name: fullSubnetData.name || '',
      network: fullSubnetData.network || '',
      gateway: fullSubnetData.gateway || '',
      vlan_id: fullSubnetData.vlan_id,
      dns_servers: fullSubnetData.dns_servers || '',
      description: fullSubnetData.description || '',
      enabled: fullSubnetData.enabled !== undefined ? fullSubnetData.enabled : true,
      auto_scan: fullSubnetData.auto_scan !== undefined ? fullSubnetData.auto_scan : true,
      scan_interval: fullSubnetData.scan_interval || 3600
    }

    showAddSubnetDialog.value = true
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '加载子网详细信息失败')
  } finally {
    loading.value = false
  }
}

// Reset form
const resetForm = () => {
  editMode.value = false
  editingSubnetId.value = null
  subnetForm.value = {
    name: '',
    network: '',
    gateway: '',
    vlan_id: undefined,
    dns_servers: '',
    description: '',
    enabled: true,
    auto_scan: true,
    scan_interval: 3600
  }
}

// Scan subnet
const scanSubnet = async (subnet: Subnet) => {
  scanning.value[subnet.subnet_id] = true
  try {
    await apiClient.post('/api/v1/ipam/scan', {
      subnet_id: subnet.subnet_id,
      scan_type: 'full'
    })
    ElMessage.success(`子网 ${subnet.network} 扫描已启动`)
    setTimeout(() => loadSubnets(), 5000)
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '扫描失败')
  } finally {
    scanning.value[subnet.subnet_id] = false
  }
}

// Delete subnet
const deleteSubnet = async (subnet: Subnet) => {
  try {
    await ElMessageBox.confirm(
      `确定要删除子网 ${subnet.network} 吗？此操作将删除该子网下的所有 IP 地址记录。`,
      '警告',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
    await apiClient.delete(`/api/v1/ipam/subnets/${subnet.subnet_id}`)
    ElMessage.success('子网删除成功')
    await loadSubnets()
  } catch (error: any) {
    if (error !== 'cancel') {
      ElMessage.error(error.response?.data?.detail || '删除失败')
    }
  }
}

// Handle row click
const handleRowClick = (row: Subnet) => {
  router.push(`/ipam/subnets/${row.subnet_id}`)
}

// Get network address from CIDR
const getNetworkAddress = (cidr: string): string => {
  return cidr.split('/')[0]
}

// Get subnet mask from CIDR
const getSubnetMask = (cidr: string): string => {
  const prefix = parseInt(cidr.split('/')[1])
  const mask = []
  for (let i = 0; i < 4; i++) {
    const n = Math.min(prefix - i * 8, 8)
    mask.push(256 - Math.pow(2, 8 - Math.max(n, 0)))
  }
  return mask.join('.')
}

// Format datetime
const formatDateTime = (dateStr: string): string => {
  try {
    const date = new Date(dateStr)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMins = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMs / 3600000)
    const diffDays = Math.floor(diffMs / 86400000)

    if (diffMins < 1) return 'Just now'
    if (diffMins < 60) return `${diffMins} minutes ago`
    if (diffHours < 24) return `${diffHours} hours ago`
    if (diffDays < 7) return `${diffDays} days ago`

    return date.toLocaleDateString('zh-CN')
  } catch {
    return dateStr
  }
}

// Parse batch import text
const parseBatchImportText = (text: string) => {
  const lines = text.trim().split('\n').filter(line => line.trim())
  const subnets = []

  for (const line of lines) {
    const parts = line.split(',').map(p => p.trim())

    if (parts.length < 2) {
      continue // Skip invalid lines
    }

    const subnet: any = {
      name: parts[0] || '',
      network: parts[1] || '',
      gateway: parts[2] || null,
      vlan_id: parts[3] ? parseInt(parts[3]) : null,
      dns_servers: parts[4] || null,
      description: parts[5] || null,
      enabled: true,
      auto_scan: true,
      scan_interval: 3600
    }

    // Clean up empty strings
    if (subnet.gateway === '') subnet.gateway = null
    if (subnet.dns_servers === '') subnet.dns_servers = null
    if (subnet.description === '') subnet.description = null
    if (!subnet.vlan_id || isNaN(subnet.vlan_id)) subnet.vlan_id = null

    subnets.push(subnet)
  }

  return subnets
}

// Handle batch import
const handleBatchImport = async () => {
  if (importMethod.value === 'excel') {
    // Excel import
    if (!excelFile.value) {
      ElMessage.warning('请先选择要导入的 Excel 文件')
      return
    }

    try {
      batchImporting.value = true
      batchImportResult.value = null

      const formData = new FormData()
      formData.append('file', excelFile.value)

      const response = await apiClient.post(
        `/api/v1/ipam/subnets/import/excel?skip_existing=true`,
        formData,
        {
          headers: {
            'Content-Type': 'multipart/form-data'
          }
        }
      )

      batchImportResult.value = response.data

      // Show success message
      if (response.data.success > 0) {
        ElMessage.success(`成功导入 ${response.data.success} 个子网`)
        await loadSubnets()
      }

      if (response.data.failed > 0) {
        ElMessage.warning(`${response.data.failed} 个子网导入失败，请查看错误详情`)
      }

      if (response.data.skipped > 0) {
        ElMessage.info(`跳过 ${response.data.skipped} 个重复的子网`)
      }

      // Reset file
      excelFile.value = null
      if (uploadRef.value) {
        uploadRef.value.clearFiles()
      }

    } catch (error: any) {
      console.error('Excel 导入错误:', error)
      ElMessage.error(error.response?.data?.detail || 'Excel 导入失败')
    } finally {
      batchImporting.value = false
    }
  } else {
    // Text import
    if (!batchImportText.value.trim()) {
      ElMessage.warning('请输入要导入的子网信息')
      return
    }

    try {
      batchImporting.value = true
      batchImportResult.value = null

      // Parse input text
      const subnets = parseBatchImportText(batchImportText.value)

      if (subnets.length === 0) {
        ElMessage.error('未能解析出有效的子网信息，请检查格式')
        return
      }

      // Call batch import API
      const response = await apiClient.post('/api/v1/ipam/subnets/batch', {
        subnets: subnets,
        skip_existing: true
      })

      batchImportResult.value = response.data

      // Show success message
      if (response.data.success > 0) {
        ElMessage.success(`成功导入 ${response.data.success} 个子网`)
        await loadSubnets()
      }

      if (response.data.failed > 0) {
        ElMessage.warning(`${response.data.failed} 个子网导入失败，请查看错误详情`)
      }

      if (response.data.skipped > 0) {
        ElMessage.info(`跳过 ${response.data.skipped} 个重复的子网`)
      }

    } catch (error: any) {
      console.error('Batch import error:', error)
      ElMessage.error(error.response?.data?.detail || '批量导入失败')
    } finally {
      batchImporting.value = false
    }
  }
}

// Reset batch import dialog
const resetBatchImport = () => {
  batchImportText.value = ''
  batchImportResult.value = null
  batchImporting.value = false
  excelFile.value = null
  if (uploadRef.value) {
    uploadRef.value.clearFiles()
  }
}

// File handling
const handleFileChange = (file: any) => {
  excelFile.value = file.raw
}

const handleFileRemove = () => {
  excelFile.value = null
}

// Download Excel template
const downloadTemplate = async () => {
  try {
    const response = await apiClient.get('/api/v1/ipam/subnets/template/download', {
      responseType: 'blob'
    })

    const url = window.URL.createObjectURL(new Blob([response.data]))
    const link = document.createElement('a')
    link.href = url
    link.setAttribute('download', 'IPAM子网导入模板.xlsx')
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)

    ElMessage.success('模板下载成功')
  } catch (error: any) {
    console.error('下载模板失败:', error)
    ElMessage.error(error.response?.data?.detail || '下载模板失败')
  }
}

// Export to Excel
const exportToExcel = () => {
  if (subnets.value.length === 0) {
    ElMessage.warning('没有数据可导出')
    return
  }

  // Prepare data for export
  const exportData = subnets.value.map(subnet => ({
    '子网名称': subnet.subnet_name,
    '网络地址': subnet.network,
    'VLAN ID': subnet.vlan_id || '',
    '网关': subnet.gateway || '',
    '总IP数': subnet.total_ips,
    '已使用': subnet.used_ips,
    '可用': subnet.available_ips,
    '保留': subnet.reserved_ips,
    '利用率(%)': subnet.utilization_percent?.toFixed(2) || '0.00',
    '最后扫描': subnet.last_scan_at ? formatDateTime(subnet.last_scan_at) : '从未扫描'
  }))

  // Convert to CSV for simple export
  const headers = Object.keys(exportData[0])
  const csvContent = [
    headers.join(','),
    ...exportData.map(row => headers.map(header => {
      const value = row[header as keyof typeof row]
      // Escape commas and quotes
      return typeof value === 'string' && value.includes(',')
        ? `"${value.replace(/"/g, '""')}"`
        : value
    }).join(','))
  ].join('\n')

  // Create blob and download
  const blob = new Blob(['\ufeff' + csvContent], { type: 'text/csv;charset=utf-8;' })
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  const timestamp = new Date().toISOString().slice(0, 19).replace(/:/g, '-')
  link.href = url
  link.setAttribute('download', `IPAM子网列表_${timestamp}.csv`)
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  window.URL.revokeObjectURL(url)

  ElMessage.success('数据导出成功')
}

onMounted(() => {
  loadSubnets()
})
</script>

<style scoped>
.ipam-simple-view {
  padding: 20px;
}

:deep(.el-table__row) {
  transition: all 0.2s;
}

:deep(.el-table__row:hover) {
  background-color: #f5f7fa;
}
</style>
