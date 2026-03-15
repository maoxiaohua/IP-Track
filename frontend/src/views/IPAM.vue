<template>
  <div class="ipam-view">
    <el-card>
      <template #header>
        <div class="card-header">
          <h2>IPAM - IP 地址管理</h2>
          <div>
            <el-button type="info" @click="showSubnetCalculatorDialog = true" :icon="Tools">
              子网计算器
            </el-button>
            <el-button type="success" @click="exportData" :icon="Download">
              导出数据
            </el-button>
            <el-button type="warning" @click="showBatchImportDialog = true" :icon="Upload">
              批量导入
            </el-button>
            <el-button type="primary" @click="resetForm(); showAddSubnetDialog = true" :icon="Plus">
              添加子网
            </el-button>
          </div>
        </div>
      </template>

      <!-- Statistics Overview -->
      <el-row :gutter="20" style="margin-bottom: 20px">
        <el-col :span="6">
          <el-statistic title="总子网数" :value="dashboard.total_subnets">
            <template #prefix>
              <el-icon style="color: #409eff"><Grid /></el-icon>
            </template>
          </el-statistic>
        </el-col>
        <el-col :span="6">
          <el-statistic title="总 IP 数" :value="dashboard.total_ips">
            <template #prefix>
              <el-icon style="color: #409eff"><Connection /></el-icon>
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
              <el-icon style="color: #e6a23c"><PieChart /></el-icon>
            </template>
          </el-statistic>
        </el-col>
      </el-row>

      <!-- Charts -->
      <el-row :gutter="20" style="margin-bottom: 20px">
        <el-col :span="12">
          <el-card shadow="hover">
            <template #header>
              <h3 style="margin: 0">IP 地址分布</h3>
            </template>
            <Chart :option="ipDistributionOption" height="220px" />
          </el-card>
        </el-col>
        <el-col :span="12">
          <el-card shadow="hover">
            <template #header>
              <h3 style="margin: 0">子网利用率</h3>
            </template>
            <Chart :option="subnetUtilizationOption" height="220px" />
          </el-card>
        </el-col>
      </el-row>

      <!-- Network Search Card -->
      <el-card shadow="hover" style="margin-bottom: 20px">
        <template #header>
          <div style="display: flex; justify-content: space-between; align-items: center;">
            <h3 style="margin: 0">网络搜索 (CIDR)</h3>
            <el-tag type="info" size="small">搜索任意网络的 IP 地址</el-tag>
          </div>
        </template>

        <el-form :inline="true" @submit.prevent="searchNetwork">
          <el-form-item label="网络地址">
            <el-input
              v-model="networkSearchForm.network"
              placeholder="例如: 10.101.63.0/24"
              style="width: 250px"
              clearable
            >
              <template #append>
                <el-button :icon="Search" @click="searchNetwork" :loading="searchingNetwork">
                  搜索
                </el-button>
              </template>
            </el-input>
          </el-form-item>
        </el-form>

        <!-- Search Results -->
        <div v-if="networkSearchResult">
          <el-divider />

          <!-- Network Info -->
          <el-descriptions :column="3" border size="small" style="margin-bottom: 15px">
            <el-descriptions-item label="网络">
              <el-tag type="primary">{{ networkSearchResult.network }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="网络地址">
              {{ networkSearchResult.network_address }}
            </el-descriptions-item>
            <el-descriptions-item label="广播地址">
              {{ networkSearchResult.broadcast_address }}
            </el-descriptions-item>
            <el-descriptions-item label="子网掩码">
              {{ networkSearchResult.netmask }}
            </el-descriptions-item>
            <el-descriptions-item label="可用主机范围">
              {{ networkSearchResult.first_usable }} - {{ networkSearchResult.last_usable }}
            </el-descriptions-item>
            <el-descriptions-item label="可用主机数">
              <el-tag>{{ networkSearchResult.usable_ips }} / {{ networkSearchResult.total_ips }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="在 IPAM 中" :span="3">
              <el-tag :type="networkSearchResult.in_ipam ? 'success' : 'info'">
                {{ networkSearchResult.in_ipam ? '是 - ' + networkSearchResult.subnet_name : '否 - 未管理' }}
              </el-tag>
            </el-descriptions-item>
          </el-descriptions>

          <!-- IP List -->
          <div style="margin-top: 15px">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px">
              <span style="font-weight: bold">IP 地址列表 ({{ networkSearchResult.ips.length }})</span>
              <el-space>
                <el-tag v-if="networkSearchResult.in_ipam" type="success">
                  已使用: {{ networkSearchResult.ips.filter(ip => ip.status === 'used').length }}
                </el-tag>
                <el-tag v-if="networkSearchResult.in_ipam" type="info">
                  可用: {{ networkSearchResult.ips.filter(ip => ip.status === 'available').length }}
                </el-tag>
              </el-space>
            </div>

            <el-table
              :data="paginatedNetworkSearchIPs"
              size="small"
              max-height="400"
              stripe
            >
              <el-table-column prop="ip_address" label="IP 地址" width="140" />
              <el-table-column prop="status" label="状态" width="100" v-if="networkSearchResult.in_ipam">
                <template #default="{ row }">
                  <el-tag
                    :type="row.status === 'used' ? 'success' : row.status === 'available' ? 'info' : 'warning'"
                    size="small"
                  >
                    {{ row.status === 'used' ? '已使用' : row.status === 'available' ? '可用' : row.status }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="is_reachable" label="可达" width="80" v-if="networkSearchResult.in_ipam">
                <template #default="{ row }">
                  <el-tag v-if="row.is_reachable !== null" :type="row.is_reachable ? 'success' : 'danger'" size="small">
                    {{ row.is_reachable ? '是' : '否' }}
                  </el-tag>
                  <span v-else style="color: #909399">-</span>
                </template>
              </el-table-column>
              <el-table-column prop="hostname" label="主机名" min-width="150" v-if="networkSearchResult.in_ipam" />
              <el-table-column prop="mac_address" label="MAC 地址" width="140" v-if="networkSearchResult.in_ipam" />
              <el-table-column prop="switch_name" label="交换机" min-width="180" v-if="networkSearchResult.in_ipam" show-overflow-tooltip />
              <el-table-column prop="switch_port" label="端口" width="100" v-if="networkSearchResult.in_ipam" />
              <el-table-column prop="description" label="描述" min-width="150" v-if="networkSearchResult.in_ipam" show-overflow-tooltip />
            </el-table>

            <!-- Pagination for search results -->
            <el-pagination
              v-if="networkSearchResult.ips.length > networkSearchPagination.pageSize"
              v-model:current-page="networkSearchPagination.currentPage"
              v-model:page-size="networkSearchPagination.pageSize"
              :page-sizes="[20, 50, 100, 200]"
              :total="networkSearchResult.ips.length"
              layout="total, sizes, prev, pager, next"
              style="margin-top: 15px; justify-content: center"
            />
          </div>
        </div>
      </el-card>

      <!-- Subnets Table -->
      <el-table :data="paginatedSubnets" v-loading="loading" stripe style="width: 100%">
        <el-table-column prop="subnet_name" label="子网名称" min-width="200" />

        <el-table-column prop="network" label="网络" width="160">
          <template #default="{ row }">
            <el-tag type="primary">{{ row.network }}</el-tag>
          </template>
        </el-table-column>

        <el-table-column label="IP 统计" width="220">
          <template #default="{ row }">
            <div style="font-size: 12px">
              <div>总数: {{ row.total_ips }}</div>
              <div>已用: <span style="color: #67c23a">{{ row.used_ips }}</span></div>
              <div>可用: <span style="color: #909399">{{ row.available_ips }}</span></div>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="利用率" width="180">
          <template #default="{ row }">
            <el-progress
              :percentage="row.utilization_percent"
              :color="getUtilizationColor(row.utilization_percent)"
            />
          </template>
        </el-table-column>

        <el-table-column prop="vlan_id" label="VLAN" width="90" />

        <el-table-column label="自动扫描" width="110">
          <template #default="{ row }">
            <el-tag :type="row.auto_scan ? 'success' : 'info'" size="small">
              {{ row.auto_scan ? '启用' : '禁用' }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="最后扫描" min-width="200">
          <template #default="{ row }">
            {{ row.last_scan_at ? formatDate(row.last_scan_at) : '从未扫描' }}
          </template>
        </el-table-column>

        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-space :size="5">
              <!-- Primary Actions -->
              <el-tooltip content="查看 IP 地址" placement="top">
                <el-button
                  size="small"
                  type="primary"
                  :icon="View"
                  circle
                  @click="viewSubnetIPs(row)"
                />
              </el-tooltip>

              <el-tooltip content="扫描子网" placement="top">
                <el-button
                  size="small"
                  type="success"
                  :icon="Refresh"
                  circle
                  :loading="scanning[row.subnet_id]"
                  @click="scanSubnet(row)"
                />
              </el-tooltip>

              <!-- Secondary Actions (Dropdown) -->
              <el-dropdown trigger="click" @command="(cmd) => handleSubnetAction(cmd, row)">
                <el-button size="small" :icon="More" circle />
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="edit" :icon="Edit">
                      编辑子网
                    </el-dropdown-item>
                    <el-dropdown-item command="delete" :icon="Delete" divided style="color: #f56c6c">
                      删除子网
                    </el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </el-space>
          </template>
        </el-table-column>
      </el-table>

      <!-- Subnet Pagination -->
      <el-pagination
        v-model:current-page="subnetPagination.currentPage"
        v-model:page-size="subnetPagination.pageSize"
        :page-sizes="[20, 50, 100, 200]"
        :total="subnets.length"
        layout="total, sizes, prev, pager, next, jumper"
        @size-change="handleSubnetPageChange"
        @current-change="handleSubnetPageChange"
        style="margin-top: 20px; justify-content: center"
      />
    </el-card>

    <!-- Add/Edit Subnet Dialog -->
    <el-dialog
      v-model="showAddSubnetDialog"
      :title="editMode ? '编辑子网' : '添加 IP 子网'"
      width="600px"
    >
      <el-form :model="subnetForm" :rules="subnetRules" ref="subnetFormRef" label-width="120px">
        <el-form-item label="子网名称" prop="name">
          <el-input v-model="subnetForm.name" placeholder="例如: 办公网络" />
        </el-form-item>

        <el-form-item label="网络地址" prop="network">
          <el-input v-model="subnetForm.network" placeholder="例如: 10.0.0.0/24" :disabled="editMode">
            <template #append>CIDR</template>
          </el-input>
          <div class="form-tip" v-if="!editMode">
            支持 CIDR 格式，如 10.0.0.0/24 或 192.168.1.0/24
          </div>
          <div class="form-tip" v-else style="color: #e6a23c">
            注意：网络地址创建后不能修改
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
          {{ editMode ? '保存' : '创建' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- Batch Import Dialog -->
    <el-dialog
      v-model="showBatchImportDialog"
      title="批量导入 IP 子网"
      width="800px"
    >
      <el-alert
        title="批量导入说明"
        type="info"
        :closable="false"
        style="margin-bottom: 20px"
      >
        <p style="margin: 5px 0">• 支持一次导入最多 100 个子网</p>
        <p style="margin: 5px 0">• <strong>必填字段</strong>：子网名称、网络地址</p>
        <p style="margin: 5px 0">• <strong>可选字段</strong>：描述、VLAN ID、网关、DNS服务器</p>
        <p style="margin: 5px 0">• 推荐使用 <strong>Excel 导入</strong>，更方便直观</p>
      </el-alert>

      <el-form label-width="120px">
        <el-form-item label="导入方式">
          <el-radio-group v-model="batchImportForm.importMethod">
            <el-radio label="excel">Excel 文件（推荐）</el-radio>
            <el-radio label="text">文本输入</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="导入模式">
          <el-radio-group v-model="batchImportForm.skipExisting">
            <el-radio :label="true">跳过重复网络（推荐）</el-radio>
            <el-radio :label="false">全部导入（重复会失败）</el-radio>
          </el-radio-group>
        </el-form-item>

        <!-- Excel Upload -->
        <template v-if="batchImportForm.importMethod === 'excel'">
          <el-form-item label="Excel 文件">
            <div style="width: 100%">
              <el-upload
                ref="uploadRef"
                :auto-upload="false"
                :limit="1"
                accept=".xlsx,.xls"
                :on-change="handleFileChange"
                :on-remove="handleFileRemove"
                drag
                style="width: 100%"
              >
                <el-icon class="el-icon--upload"><upload-filled /></el-icon>
                <div class="el-upload__text">
                  拖拽文件到此处或 <em>点击上传</em>
                </div>
                <template #tip>
                  <div class="el-upload__tip">
                    只支持 .xlsx 或 .xls 文件，大小不超过 10MB
                  </div>
                </template>
              </el-upload>
              <el-button
                type="success"
                link
                :icon="Download"
                @click="downloadTemplate"
                style="margin-top: 10px"
              >
                下载 Excel 导入模板
              </el-button>
            </div>
          </el-form-item>
        </template>

        <!-- Text Input -->
        <template v-else>
          <el-form-item label="子网数据">
            <el-input
              v-model="batchImportForm.textInput"
              type="textarea"
              :rows="12"
              placeholder="请输入子网数据，每行一个子网（必填字段：名称,网络地址）
示例：
办公网络,10.0.1.0/24,办公室网段,100,10.0.1.1,8.8.8.8
研发网络,10.0.2.0/24,研发部门网段,200,10.0.2.1,8.8.8.8
测试网络,10.0.3.0/24"
            />
            <div class="form-tip" style="margin-top: 8px">
              已输入 {{ batchImportForm.textInput.split('\n').filter(l => l.trim()).length }} 个子网
            </div>
          </el-form-item>
        </template>
      </el-form>

      <template #footer>
        <el-button @click="showBatchImportDialog = false">取消</el-button>
        <el-button type="primary" :loading="importing" @click="handleBatchImport">
          开始导入
        </el-button>
      </template>
    </el-dialog>

    <!-- Batch Import Result Dialog -->
    <el-dialog
      v-model="showImportResultDialog"
      title="批量导入结果"
      width="700px"
    >
      <el-result
        :icon="importResult.success === importResult.total ? 'success' : 'warning'"
        :title="`导入完成: ${importResult.success}/${importResult.total} 成功`"
      >
        <template #sub-title>
          <div style="margin-top: 10px">
            <p>成功：{{ importResult.success }} 个</p>
            <p v-if="importResult.skipped > 0" style="color: #e6a23c">跳过：{{ importResult.skipped }} 个（重复）</p>
            <p v-if="importResult.failed > 0" style="color: #f56c6c">失败：{{ importResult.failed }} 个</p>
          </div>
        </template>
        <template #extra>
          <el-button type="primary" @click="showImportResultDialog = false; loadData()">
            确定
          </el-button>
        </template>
      </el-result>

      <!-- Error Details -->
      <el-collapse v-if="importResult.errors && importResult.errors.length > 0" style="margin-top: 20px">
        <el-collapse-item title="查看错误详情" name="errors">
          <el-table :data="importResult.errors" size="small" max-height="300">
            <el-table-column prop="index" label="行号" width="80">
              <template #default="{ row }">
                {{ row.index + 1 }}
              </template>
            </el-table-column>
            <el-table-column prop="network" label="网络" width="150" />
            <el-table-column prop="name" label="名称" width="150" />
            <el-table-column prop="error" label="错误信息" />
          </el-table>
        </el-collapse-item>
      </el-collapse>
    </el-dialog>

    <!-- Subnet Calculator Dialog -->
    <el-dialog
      v-model="showSubnetCalculatorDialog"
      title="子网计算器"
      width="700px"
    >
      <el-form label-width="120px">
        <el-form-item label="IP 地址">
          <el-input
            v-model="calculatorForm.ipAddress"
            placeholder="例如: 10.101.63.25"
            @keyup.enter="calculateSubnet"
          />
        </el-form-item>

        <el-form-item label="子网掩码">
          <el-input
            v-model="calculatorForm.netmask"
            placeholder="例如: 255.255.255.0 或 24 或 /24"
            @keyup.enter="calculateSubnet"
          >
            <template #append>
              <el-button :icon="Tools" @click="calculateSubnet" :loading="calculating">
                计算
              </el-button>
            </template>
          </el-input>
          <div class="form-tip">支持: 点分十进制 (255.255.255.0)、CIDR 前缀 (24 或 /24)</div>
        </el-form-item>
      </el-form>

      <!-- Calculation Results -->
      <div v-if="calculatorResult">
        <el-divider>计算结果</el-divider>

        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="IP 地址">
            <el-tag type="primary">{{ calculatorResult.ip_address }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="CIDR 表示">
            <el-tag type="success">{{ calculatorResult.cidr }}</el-tag>
          </el-descriptions-item>

          <el-descriptions-item label="网络地址">
            {{ calculatorResult.network_address }}
          </el-descriptions-item>
          <el-descriptions-item label="广播地址">
            {{ calculatorResult.broadcast_address }}
          </el-descriptions-item>

          <el-descriptions-item label="子网掩码">
            {{ calculatorResult.netmask }}
          </el-descriptions-item>
          <el-descriptions-item label="通配符掩码">
            {{ calculatorResult.wildcard_mask }}
          </el-descriptions-item>

          <el-descriptions-item label="第一个可用 IP">
            <span style="color: #67c23a; font-weight: bold">{{ calculatorResult.first_usable_ip }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="最后可用 IP">
            <span style="color: #e6a23c; font-weight: bold">{{ calculatorResult.last_usable_ip }}</span>
          </el-descriptions-item>

          <el-descriptions-item label="主机总数">
            <el-tag>{{ calculatorResult.total_hosts }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="可用主机数">
            <el-tag type="success">{{ calculatorResult.usable_hosts }}</el-tag>
          </el-descriptions-item>

          <el-descriptions-item label="IP 类别">
            {{ calculatorResult.ip_class }}
          </el-descriptions-item>
          <el-descriptions-item label="私有网络">
            <el-tag :type="calculatorResult.is_private ? 'success' : 'warning'">
              {{ calculatorResult.is_private ? '是' : '否' }}
            </el-tag>
          </el-descriptions-item>

          <el-descriptions-item label="二进制 IP" :span="2">
            <code style="font-size: 11px; color: #606266">{{ calculatorResult.binary_ip }}</code>
          </el-descriptions-item>

          <el-descriptions-item label="二进制掩码" :span="2">
            <code style="font-size: 11px; color: #606266">{{ calculatorResult.binary_netmask }}</code>
          </el-descriptions-item>

          <el-descriptions-item label="十六进制 IP" :span="2">
            <code style="color: #409eff">{{ calculatorResult.hex_ip }}</code>
          </el-descriptions-item>
        </el-descriptions>
      </div>

      <template #footer>
        <el-button @click="showSubnetCalculatorDialog = false">关闭</el-button>
        <el-button type="primary" @click="calculateSubnet" :loading="calculating">
          重新计算
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import {
  Plus, Grid, Connection, Check, PieChart, View, Refresh, Delete, Download, Edit, Upload, UploadFilled, Search, Tools, More
} from '@element-plus/icons-vue'
import apiClient from '@/api/index'
import Chart from '@/components/Chart.vue'
import { exportToExcel } from '@/utils/export'

const router = useRouter()
const loading = ref(false)
const saving = ref(false)
const showAddSubnetDialog = ref(false)
const editMode = ref(false)
const editingSubnetId = ref<number | null>(null)
const subnetFormRef = ref<FormInstance>()
const scanning = ref<Record<number, boolean>>({})
const uploadRef = ref()

// Batch import related
const showBatchImportDialog = ref(false)
const showImportResultDialog = ref(false)
const importing = ref(false)
const batchImportForm = reactive({
  importMethod: 'excel',  // 'excel' or 'text'
  textInput: '',
  skipExisting: true,
  excelFile: null as File | null
})
const importResult = reactive({
  total: 0,
  success: 0,
  failed: 0,
  skipped: 0,
  errors: [] as any[]
})

// Network Search related
const showSubnetCalculatorDialog = ref(false)
const searchingNetwork = ref(false)
const calculating = ref(false)

const networkSearchForm = reactive({
  network: ''
})

const networkSearchResult = ref<any>(null)

const networkSearchPagination = reactive({
  currentPage: 1,
  pageSize: 50
})

const paginatedNetworkSearchIPs = computed(() => {
  if (!networkSearchResult.value || !networkSearchResult.value.ips) {
    return []
  }
  const start = (networkSearchPagination.currentPage - 1) * networkSearchPagination.pageSize
  const end = start + networkSearchPagination.pageSize
  return networkSearchResult.value.ips.slice(start, end)
})

const calculatorForm = reactive({
  ipAddress: '',
  netmask: ''
})

const calculatorResult = ref<any>(null)


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

// Subnet pagination
const subnetPagination = reactive({
  currentPage: 1,
  pageSize: 20
})

// Paginated subnets - computed property for client-side pagination
const paginatedSubnets = computed(() => {
  const start = (subnetPagination.currentPage - 1) * subnetPagination.pageSize
  const end = start + subnetPagination.pageSize
  return subnets.value.slice(start, end)
})

const subnetForm = reactive({
  name: '',
  network: '',
  description: '',
  vlan_id: null as number | null,
  gateway: '',
  dns_servers: '',
  enabled: true,
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

// Chart options
const ipDistributionOption = computed(() => ({
  tooltip: {
    trigger: 'item',
    formatter: '{b}: {c} ({d}%)'
  },
  legend: {
    orient: 'vertical',
    left: 'left'
  },
  series: [
    {
      name: 'IP 分布',
      type: 'pie',
      radius: '50%',
      data: [
        { value: dashboard.value.used_ips, name: '已使用', itemStyle: { color: '#67c23a' } },
        { value: dashboard.value.available_ips, name: '可用', itemStyle: { color: '#909399' } },
        { value: dashboard.value.offline_ips, name: '离线', itemStyle: { color: '#f56c6c' } }
      ],
      emphasis: {
        itemStyle: {
          shadowBlur: 10,
          shadowOffsetX: 0,
          shadowColor: 'rgba(0, 0, 0, 0.5)'
        }
      }
    }
  ]
}))

const subnetUtilizationOption = computed(() => {
  // Handle case where subnets might be undefined or null
  const validSubnets = subnets.value || []

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: {
        type: 'shadow'
      }
    },
    xAxis: {
      type: 'category',
      data: validSubnets.map(s => s.subnet_name),
      axisLabel: {
        rotate: 45,
        interval: 0
      }
    },
    yAxis: {
      type: 'value',
      max: 100,
      axisLabel: {
        formatter: '{value}%'
      }
    },
    series: [
      {
        name: '利用率',
        type: 'bar',
        data: validSubnets.map(s => ({
          value: s.utilization_percent,
          itemStyle: {
            color: s.utilization_percent < 50 ? '#67c23a' : s.utilization_percent < 80 ? '#e6a23c' : '#f56c6c'
          }
        })),
        label: {
          show: true,
          position: 'top',
          formatter: '{c}%'
        }
      }
    ]
  }
})

const loadDashboard = async () => {
  loading.value = true
  try {
    const response = await apiClient.get('/api/v1/ipam/dashboard')
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
      // Prepare data - convert empty strings to null for optional fields
      const data = {
        ...subnetForm,
        gateway: subnetForm.gateway || null,
        dns_servers: subnetForm.dns_servers || null,
        vlan_id: subnetForm.vlan_id || null
      }

      if (editMode.value && editingSubnetId.value) {
        // Update existing subnet
        await apiClient.put(`/api/v1/ipam/subnets/${editingSubnetId.value}`, data)
        ElMessage.success('子网更新成功')
      } else {
        // Create new subnet
        await apiClient.post('/api/v1/ipam/subnets', data)
        ElMessage.success('子网创建成功')
      }

      showAddSubnetDialog.value = false
      resetForm()
      loadDashboard()
    } catch (error: any) {
      console.error('子网操作错误:', error.response?.data)

      // Format error message properly
      let errorMsg = editMode.value ? '更新子网失败' : '创建子网失败'
      if (error.response?.data?.detail) {
        if (Array.isArray(error.response.data.detail)) {
          // Pydantic validation errors
          errorMsg = error.response.data.detail.map((e: any) => e.msg).join(', ')
        } else if (typeof error.response.data.detail === 'string') {
          errorMsg = error.response.data.detail
        }
      }

      ElMessage.error(errorMsg)
    } finally {
      saving.value = false
    }
  })
}

// Batch import handling
const handleBatchImport = async () => {
  if (batchImportForm.importMethod === 'excel') {
    // Excel import
    if (!batchImportForm.excelFile) {
      ElMessage.warning('请先选择要导入的 Excel 文件')
      return
    }

    importing.value = true

    try {
      const formData = new FormData()
      formData.append('file', batchImportForm.excelFile)

      const response = await apiClient.post(
        `/api/v1/ipam/subnets/import/excel?skip_existing=${batchImportForm.skipExisting}`,
        formData,
        {
          headers: {
            'Content-Type': 'multipart/form-data'
          }
        }
      )

      // Update result
      Object.assign(importResult, response.data)

      // Close import dialog and show result
      showBatchImportDialog.value = false
      showImportResultDialog.value = true

      // Reset form
      batchImportForm.excelFile = null
      if (uploadRef.value) {
        uploadRef.value.clearFiles()
      }

      // Show summary message
      if (response.data.success === response.data.total) {
        ElMessage.success(`成功导入 ${response.data.success} 个子网`)
      } else {
        ElMessage.warning(
          `导入完成：${response.data.success} 成功，${response.data.failed} 失败，${response.data.skipped} 跳过`
        )
      }
    } catch (error: any) {
      console.error('Excel 导入错误:', error)
      ElMessage.error(error.response?.data?.detail || 'Excel 导入失败')
    } finally {
      importing.value = false
    }
  } else {
    // Text import
    const lines = batchImportForm.textInput.split('\n').filter(l => l.trim())

    if (lines.length === 0) {
      ElMessage.warning('请输入要导入的子网数据')
      return
    }

    if (lines.length > 100) {
      ElMessage.error('一次最多导入 100 个子网')
      return
    }

    importing.value = true

    try {
      // Parse CSV lines into subnet objects
      const subnets = lines.map((line, index) => {
        const fields = line.split(',').map(f => f.trim())

        if (fields.length < 2) {
          throw new Error(`第 ${index + 1} 行格式错误：至少需要名称和网络地址`)
        }

        return {
          name: fields[0] || `子网-${index + 1}`,
          network: fields[1],
          description: fields[2] || null,
          vlan_id: fields[3] ? parseInt(fields[3]) : null,
          gateway: fields[4] || null,
          dns_servers: fields[5] || null,
          enabled: true,
          auto_scan: true,
          scan_interval: 3600
        }
      })

      // Call batch import API
      const response = await apiClient.post('/api/v1/ipam/subnets/batch', {
        subnets: subnets,
        skip_existing: batchImportForm.skipExisting
      })

      // Update result
      Object.assign(importResult, response.data)

      // Close import dialog and show result
      showBatchImportDialog.value = false
      showImportResultDialog.value = true

      // Reset form
      batchImportForm.textInput = ''

      // Show summary message
      if (response.data.success === response.data.total) {
        ElMessage.success(`成功导入 ${response.data.success} 个子网`)
      } else {
        ElMessage.warning(
          `导入完成：${response.data.success} 成功，${response.data.failed} 失败，${response.data.skipped} 跳过`
        )
      }
    } catch (error: any) {
      console.error('批量导入错误:', error)
      ElMessage.error(error.response?.data?.detail || '批量导入失败')
    } finally {
      importing.value = false
    }
  }
}

// File handling
const handleFileChange = (file: any) => {
  batchImportForm.excelFile = file.raw
}

const handleFileRemove = () => {
  batchImportForm.excelFile = null
}

// Download template
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
  } catch (error) {
    console.error('模板下载错误:', error)
    ElMessage.error('模板下载失败')
  }
}

// Handle dropdown menu actions
const handleSubnetAction = (command: string, subnet: any) => {
  if (command === 'edit') {
    editSubnet(subnet)
  } else if (command === 'delete') {
    deleteSubnet(subnet)
  }
}

const editSubnet = (subnet: any) => {
  editMode.value = true
  editingSubnetId.value = subnet.subnet_id

  // Populate form with existing data
  Object.assign(subnetForm, {
    name: subnet.subnet_name,
    network: subnet.network,
    description: subnet.description || '',
    vlan_id: subnet.vlan_id,
    gateway: subnet.gateway || '',
    dns_servers: subnet.dns_servers || '',
    enabled: subnet.enabled,
    auto_scan: subnet.auto_scan,
    scan_interval: subnet.scan_interval || 3600
  })

  showAddSubnetDialog.value = true
}

const resetForm = () => {
  editMode.value = false
  editingSubnetId.value = null
  Object.assign(subnetForm, {
    name: '',
    network: '',
    description: '',
    vlan_id: null,
    gateway: '',
    dns_servers: '',
    enabled: true,
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
    const response = await apiClient.post('/api/v1/ipam/scan', {
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

    await apiClient.delete(`/api/v1/ipam/subnets/${subnet.subnet_id}`)
    ElMessage.success('子网已删除')
    loadDashboard()
  } catch (error: any) {
    if (error !== 'cancel') {
      ElMessage.error(error.response?.data?.detail || '删除失败')
    }
  }
}

const exportData = () => {
  if (subnets.value.length === 0) {
    ElMessage.warning('没有数据可导出')
    return
  }

  const exportData = subnets.value.map(subnet => ({
    '子网名称': subnet.subnet_name,
    '网络': subnet.network,
    '总 IP 数': subnet.total_ips,
    '已使用': subnet.used_ips,
    '可用': subnet.available_ips,
    '保留': subnet.reserved_ips,
    '离线': subnet.offline_ips,
    '利用率 (%)': subnet.utilization_percent,
    '在线设备': subnet.reachable_count,
    'VLAN': subnet.vlan_id || '-',
    '最后扫描': subnet.last_scan_at ? formatDate(subnet.last_scan_at) : '从未扫描'
  }))

  const timestamp = new Date().toISOString().slice(0, 19).replace(/:/g, '-')
  exportToExcel(exportData, `IPAM_子网统计_${timestamp}`, 'IPAM 数据')
  ElMessage.success('数据导出成功')
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

const handleSubnetPageChange = () => {
  // Page change handler - computed property will automatically update
  // No additional logic needed as we're using client-side pagination
}

// Network Search methods
const searchNetwork = async () => {
  if (!networkSearchForm.network) {
    ElMessage.warning('请输入网络地址')
    return
  }

  // Validate CIDR format
  if (!/^(\d{1,3}\.){3}\d{1,3}\/\d{1,2}$/.test(networkSearchForm.network)) {
    ElMessage.error('请输入有效的 CIDR 格式，如 10.101.63.0/24')
    return
  }

  searchingNetwork.value = true
  try {
    const response = await apiClient.post('/api/v1/ipam/network-search', {
      network: networkSearchForm.network
    })
    networkSearchResult.value = response.data
    networkSearchPagination.currentPage = 1
    ElMessage.success(`搜索完成，找到 ${response.data.ips.length} 个 IP 地址`)
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '网络搜索失败')
    console.error('Network search error:', error)
  } finally {
    searchingNetwork.value = false
  }
}

// Subnet Calculator methods
const calculateSubnet = async () => {
  if (!calculatorForm.ipAddress) {
    ElMessage.warning('请输入 IP 地址')
    return
  }

  calculating.value = true
  try {
    const response = await apiClient.post('/api/v1/ipam/subnet-calculator', {
      ip_address: calculatorForm.ipAddress,
      netmask: calculatorForm.netmask || null
    })
    calculatorResult.value = response.data
    ElMessage.success('计算完成')
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '子网计算失败')
    console.error('Subnet calculation error:', error)
  } finally {
    calculating.value = false
  }
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
}

.form-tip {
  font-size: 12px;
  color: #909399;
  margin-top: 5px;
}
</style>
