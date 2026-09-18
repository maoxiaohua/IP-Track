<template>
  <div class="switches-view">
    <el-card>
      <template #header>
        <div class="card-header">
          <h2>Switch Management</h2>
          <div class="header-actions">
            <el-button type="primary" @click="loadSwitches" :loading="loading">
              <el-icon><Refresh /></el-icon>
              刷新列表
            </el-button>
            <el-button type="success" @click="refreshHostnames" :loading="refreshingHostnames">
              刷新 Hostname
            </el-button>
            <el-button type="warning" @click="refreshDeviceInfo" :loading="refreshingDeviceInfo">
              <el-icon><Monitor /></el-icon>
              刷新设备信息
            </el-button>
            <el-dropdown trigger="click" @command="(cmd: string) => exportSwitches(cmd as 'excel' | 'csv')">
              <el-button type="success" :loading="exportingSwitches">
                <el-icon><Download /></el-icon>
                导出
                <el-icon class="el-icon--right"><ArrowDown /></el-icon>
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="excel">导出 Excel (.xlsx)</el-dropdown-item>
                  <el-dropdown-item command="csv">导出 CSV</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <el-button type="primary" @click="openAddDialog">
              <el-icon><Plus /></el-icon>
              Add Switch
            </el-button>
          </div>
        </div>
      </template>

      <!-- Duplicate Switch Warning -->
      <el-alert
        v-if="duplicateCount > 0"
        type="warning"
        :closable="false"
        show-icon
        style="margin-bottom: 12px;"
      >
        <template #title>
          发现 <strong>{{ duplicateCount }}</strong> 组可能的重复交换机（相同序列号或主机名）
        </template>
      </el-alert>

      <!-- Search Bar -->
      <div class="search-bar">
        <div class="search-controls">
          <el-input
            v-model="searchQuery"
            placeholder="搜索交换机名称 / IP / 序列号..."
            clearable
            @clear="handleSearch"
            @keyup.enter="handleSearch"
            class="search-input"
          >
            <template #prefix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>
          <el-button type="primary" @click="handleSearch" :loading="loading">
            搜索
          </el-button>
          <el-button
            :type="showPendingTrunkOnly ? 'warning' : 'info'"
            @click="togglePendingTrunkFilter"
          >
            {{ showPendingTrunkOnly ? '只看待处理: 开' : '只看待处理: 关' }}
          </el-button>
        </div>

        <div class="sort-controls">
          <span class="sort-label">排序</span>
          <el-select
            v-model="selectedSortField"
            placeholder="默认顺序"
            clearable
            class="sort-field-select"
            @change="handleSortFieldChange"
            @clear="clearSort"
          >
            <el-option
              v-for="option in sortFieldOptions"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
          <el-radio-group v-if="selectedSortField && !selectedSortField.startsWith('collection_status_')" v-model="sortOrder" @change="handleSortOrderChange">
            <el-radio-button
              v-for="option in sortDirectionOptions"
              :key="option.value"
              :label="option.value"
            >
              {{ option.label }}
            </el-radio-button>
          </el-radio-group>
          <el-button v-if="selectedSortField" text @click="clearSort">
            恢复默认
          </el-button>
          <span class="sort-hint">{{ currentSortHint }}</span>
        </div>
      </div>

      <!-- Batch Operation Toolbar -->
      <div v-if="selectedSwitches.length > 0" class="batch-toolbar">
        <div class="batch-info">
          <el-tag type="primary">已选择 {{ selectedSwitches.length }} 个交换机</el-tag>
        </div>
        <div class="batch-actions">
          <el-button size="small" type="success" @click="handleBatchEnable">
            <el-icon><Check /></el-icon>
            批量启用
          </el-button>
          <el-button size="small" type="warning" @click="handleBatchDisable">
            <el-icon><Close /></el-icon>
            批量禁用
          </el-button>
          <el-button size="small" type="primary" @click="openBatchSnmpDialog">
            <el-icon><Setting /></el-icon>
            批量配置 SNMP
          </el-button>
          <el-button size="small" type="danger" @click="handleBatchDelete">
            <el-icon><Delete /></el-icon>
            批量删除
          </el-button>
        </div>
      </div>

      <SwitchList
        :switches="switches"
        :loading="loading"
        @refresh="loadSwitches"
        @add="openAddDialog"
        @edit="handleEdit"
        @delete="handleDelete"
        @test="handleTest"
        @selection-change="handleSelectionChange"
        @sort-change="handleSortChange"
      />

      <!-- Pagination -->
      <div class="pagination-container">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :page-sizes="[20, 50, 100, 200]"
          :total="totalSwitches"
          layout="total, sizes, prev, pager, next, jumper"
          @size-change="handlePageSizeChange"
          @current-change="handlePageChange"
        />
      </div>
    </el-card>

    <!-- Add/Edit Switch Dialog -->
    <el-dialog
      v-model="showAddDialog"
      :title="editingSwitch ? 'Edit Switch' : 'Add New Switch'"
      width="600px"
    >
      <el-form :model="switchForm" :rules="switchRules" ref="switchFormRef" label-width="160px">
        <el-form-item label="Name" prop="name">
          <el-input v-model="switchForm.name" placeholder="e.g., Core-Switch-01" />
        </el-form-item>

        <el-form-item label="IP Address" prop="ip_address">
          <el-input v-model="switchForm.ip_address" placeholder="e.g., 192.168.1.1" />
        </el-form-item>

        <el-form-item label="Vendor" prop="vendor">
          <el-select v-model="switchForm.vendor" placeholder="Select vendor">
            <el-option label="Cisco" value="cisco" />
            <el-option label="Dell" value="dell" />
            <el-option label="Alcatel-Lucent" value="alcatel" />
          </el-select>
        </el-form-item>

        <el-form-item label="Model" prop="model">
          <el-input v-model="switchForm.model" placeholder="e.g., Catalyst 3850" />
        </el-form-item>

        <el-divider content-position="left">CLI 配置</el-divider>

        <el-form-item label="启用 CLI 认证" prop="cli_enabled">
          <el-switch v-model="switchForm.cli_enabled" />
          <span style="margin-left: 8px; color: #909399;">启用后可通过 SSH 或 Telnet 执行命令</span>
        </el-form-item>

        <template v-if="switchForm.cli_enabled">
          <el-form-item label="CLI 协议" prop="cli_transport">
            <el-select v-model="switchForm.cli_transport" style="width: 180px">
              <el-option label="SSH" value="ssh" />
              <el-option label="Telnet" value="telnet" />
            </el-select>
          </el-form-item>

          <el-form-item label="CLI 端口" prop="ssh_port">
            <el-input-number v-model="switchForm.ssh_port" :min="1" :max="65535" />
          </el-form-item>

          <el-form-item label="用户名" prop="username">
            <el-input v-model="switchForm.username" placeholder="CLI username" />
          </el-form-item>

          <el-form-item label="密码" prop="password">
            <el-input
              v-model="switchForm.password"
              type="password"
              placeholder="CLI password"
              show-password
            />
            <div v-if="editingSwitch && switchForm.password === ''" style="color: #909399; font-size: 12px; margin-top: 4px;">
              当前已配置密码（留空则不修改）
            </div>
          </el-form-item>

          <el-form-item label="Enable 密码" prop="enable_password">
            <el-input
              v-model="switchForm.enable_password"
              type="password"
              placeholder="Enable password (optional)"
              show-password
            />
          </el-form-item>
        </template>

        <el-divider content-position="left">数据收集设置</el-divider>

        <el-form-item label="自动收集 ARP" prop="auto_collect_arp">
          <el-switch v-model="switchForm.auto_collect_arp" />
        </el-form-item>

        <el-form-item label="自动收集 MAC" prop="auto_collect_mac">
          <el-switch v-model="switchForm.auto_collect_mac" />
        </el-form-item>

        <el-divider content-position="left">SNMP 配置</el-divider>

        <el-form-item label="SNMP 启用" prop="snmp_enabled">
          <el-switch v-model="switchForm.snmp_enabled" />
        </el-form-item>

        <template v-if="switchForm.snmp_enabled">
          <el-form-item label="SNMP 版本" prop="snmp_version">
            <el-select v-model="switchForm.snmp_version" disabled>
              <el-option label="SNMPv3" value="3" />
            </el-select>
          </el-form-item>

          <el-form-item label="SNMP 端口" prop="snmp_port">
            <el-input-number v-model="switchForm.snmp_port" :min="1" :max="65535" />
          </el-form-item>

          <el-form-item label="凭据来源" prop="snmp_profile_id">
            <el-select
              v-model="switchForm.snmp_profile_id"
              placeholder="本机自带（不引用模板）"
              style="width: 100%"
            >
              <el-option label="本机自带（不引用模板）" :value="null" />
              <el-option
                v-for="p in snmpProfileStore.enabledProfiles()"
                :key="p.id"
                :label="`模板：${p.name}（${p.version} · ${p.auth_protocol || '—'} / ${p.priv_protocol || '—'}）`"
                :value="p.id"
              />
            </el-select>
            <div style="color: #909399; font-size: 12px; margin-top: 4px;">
              选中模板后，下面这台设备自己的凭据字段会被模板取代；以后改口令只改模板一处，
              所有引用它的交换机同时生效。
            </div>
          </el-form-item>

          <!--
            引用模板时整段隐藏，而不是显示成空值：
            后端在 snmp_profile_id 非空时本来就忽略这些字段，显示出来只会让人以为
            「这里填的还算数」。留一段说明告诉人去哪儿改。
          -->
          <el-alert
            v-if="switchForm.snmp_profile_id"
            type="info"
            :closable="false"
            show-icon
            style="margin-bottom: 18px;"
          >
            <template #title>
              凭据取自模板「{{ snmpProfileStore.byId(switchForm.snmp_profile_id)?.name }}」，
              用户名、协议、口令都在模板上维护。
            </template>
          </el-alert>

          <template v-if="!switchForm.snmp_profile_id">
          <el-form-item label="SNMP 用户名" prop="snmp_username">
            <el-input v-model="switchForm.snmp_username" placeholder="SNMP username" />
          </el-form-item>

          <el-form-item label="认证协议" prop="snmp_auth_protocol">
            <el-select v-model="switchForm.snmp_auth_protocol">
              <el-option label="MD5" value="MD5" />
              <el-option label="SHA" value="SHA" />
              <el-option label="SHA-224" value="SHA-224" />
              <el-option label="SHA-256" value="SHA-256" />
              <el-option label="SHA-384" value="SHA-384" />
              <el-option label="SHA-512" value="SHA-512" />
            </el-select>
          </el-form-item>

          <el-form-item label="认证密码" prop="snmp_auth_password">
            <el-input
              v-model="switchForm.snmp_auth_password"
              type="password"
              placeholder="至少8位字符"
              show-password
            />
            <div v-if="editingSwitch && switchForm.snmp_auth_password === ''" style="color: #909399; font-size: 12px; margin-top: 4px;">
              当前已配置密码（留空则不修改）
            </div>
          </el-form-item>

          <el-form-item label="加密协议" prop="snmp_priv_protocol">
            <el-select v-model="switchForm.snmp_priv_protocol">
              <el-option label="DES" value="DES" />
              <el-option label="AES-128" value="AES-128" />
              <el-option label="AES-192" value="AES-192" />
              <el-option label="AES-256" value="AES-256" />
            </el-select>
          </el-form-item>

          <el-form-item label="加密密码（可选）" prop="snmp_priv_password">
            <el-input
              v-model="switchForm.snmp_priv_password"
              type="password"
              placeholder="留空则不启用加密"
              show-password
            />
            <div v-if="editingSwitch && switchForm.snmp_priv_password === ''" style="color: #909399; font-size: 12px; margin-top: 4px;">
              新建时留空则不启用加密；编辑现有设备时留空则保持现有配置
            </div>
          </el-form-item>
          </template>
        </template>

        <el-form-item label="Enabled" prop="enabled">
          <el-switch v-model="switchForm.enabled" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="showAddDialog = false">Cancel</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">
          {{ editingSwitch ? 'Update' : 'Create' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- Batch SNMP Configuration Dialog -->
    <el-dialog
      v-model="showBatchSnmpDialog"
      title="批量配置 SNMPv3"
      width="600px"
    >
      <el-alert
        type="info"
        :closable="false"
        style="margin-bottom: 20px;"
      >
        <template #title>
          将为 {{ selectedSwitches.length }} 个交换机配置 SNMPv3 认证信息
        </template>
      </el-alert>

      <el-form :model="batchSnmpForm" :rules="batchSnmpRules" ref="batchSnmpFormRef" label-width="160px">
        <el-form-item label="SNMP 版本" prop="snmp_version">
          <el-select v-model="batchSnmpForm.snmp_version" disabled>
            <el-option label="SNMPv3" value="3" />
          </el-select>
        </el-form-item>

        <el-form-item label="SNMP 端口" prop="snmp_port">
          <el-input-number v-model="batchSnmpForm.snmp_port" :min="1" :max="65535" />
        </el-form-item>

        <el-form-item label="凭据来源" prop="snmp_profile_id">
          <el-select
            v-model="batchSnmpForm.snmp_profile_id"
            placeholder="本机自带（不引用模板）"
            style="width: 100%"
          >
            <el-option label="本机自带（不引用模板）" :value="null" />
            <el-option
              v-for="p in snmpProfileStore.enabledProfiles()"
              :key="p.id"
              :label="`模板：${p.name}（${p.version} · ${p.auth_protocol || '—'} / ${p.priv_protocol || '—'}）`"
              :value="p.id"
            />
          </el-select>
          <div style="color: #909399; font-size: 12px; margin-top: 4px;">
            选中模板时，下面这些逐台凭据字段不生效，{{ selectedSwitches.length }} 台交换机统一改为引用该模板。
          </div>
        </el-form-item>

        <el-alert
          v-if="batchSnmpForm.snmp_profile_id"
          type="info"
          :closable="false"
          show-icon
          style="margin-bottom: 18px;"
        >
          <template #title>
            将把 {{ selectedSwitches.length }} 台交换机改挂到模板
            「{{ snmpProfileStore.byId(batchSnmpForm.snmp_profile_id)?.name }}」，
            它们各自原有的凭据副本会被清除。
          </template>
        </el-alert>

        <template v-if="!batchSnmpForm.snmp_profile_id">
        <el-form-item label="用户名" prop="snmp_username">
          <el-input v-model="batchSnmpForm.snmp_username" placeholder="SNMP username" />
        </el-form-item>

        <el-form-item label="认证协议" prop="snmp_auth_protocol">
          <el-select v-model="batchSnmpForm.snmp_auth_protocol">
            <el-option label="MD5" value="MD5" />
            <el-option label="SHA" value="SHA" />
            <el-option label="SHA-224" value="SHA-224" />
            <el-option label="SHA-256" value="SHA-256" />
            <el-option label="SHA-384" value="SHA-384" />
            <el-option label="SHA-512" value="SHA-512" />
          </el-select>
        </el-form-item>

        <el-form-item label="认证密码" prop="snmp_auth_password">
          <el-input
            v-model="batchSnmpForm.snmp_auth_password"
            type="password"
            placeholder="至少8位字符"
            show-password
          />
        </el-form-item>

        <el-form-item label="加密协议" prop="snmp_priv_protocol">
          <el-select v-model="batchSnmpForm.snmp_priv_protocol">
            <el-option label="DES" value="DES" />
            <el-option label="AES-128" value="AES-128" />
            <el-option label="AES-192" value="AES-192" />
            <el-option label="AES-256" value="AES-256" />
          </el-select>
        </el-form-item>

        <el-form-item label="加密密码（可选）" prop="snmp_priv_password">
          <el-input
            v-model="batchSnmpForm.snmp_priv_password"
            type="password"
            placeholder="留空则按仅认证模式配置"
            show-password
          />
        </el-form-item>
        </template>
      </el-form>

      <template #footer>
        <el-button @click="showBatchSnmpDialog = false">取消</el-button>
        <el-button type="primary" :loading="batchConfiguring" @click="handleBatchSnmpConfig">
          确认配置
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, computed, watch, h } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { Plus, Refresh, Check, Close, Setting, Delete, Monitor, Search, Download, ArrowDown } from '@element-plus/icons-vue'
import { switchesApi, type Switch, type SwitchCreate } from '@/api/switches'
import SwitchList from '@/components/SwitchList.vue'
import { API_BASE_URL } from '@/api/index'
// 已保存的 SNMP 凭据模板，用于新增/编辑/批量配置时的「凭据来源」下拉。
// 集中在一个 store 里，模板页改完名字这里调 load(true) 就能同步。
import { useSNMPProfilesStore } from '@/stores/snmpProfiles'

const snmpProfileStore = useSNMPProfilesStore()

const switches = ref<Switch[]>([])
const loading = ref(false)
const saving = ref(false)
const refreshingHostnames = ref(false)
const refreshingDeviceInfo = ref(false)
const exportingSwitches = ref(false)
const showAddDialog = ref(false)
const editingSwitch = ref<Switch | null>(null)
const duplicateCount = ref(0)
const switchFormRef = ref<FormInstance>()

// Pagination and search states
const searchQuery = ref('')
const currentPage = ref(1)
const pageSize = ref(100)
const totalSwitches = ref(0)
const showPendingTrunkOnly = ref(false)
const collectionStatusFilter = ref('')
type SortField = 'name' | 'ip_address' | 'model' | 'last_collection_time' | 'last_successful_collection_time' | 'connection_status'
type SortOption = SortField | 'collection_status_success' | 'collection_status_failed' | 'collection_status_partial'

const sortBy = ref<SortField | null>(null)
const selectedSortField = ref<SortOption | null>(null)
const sortOrder = ref<'asc' | 'desc'>('asc')

const sortFieldOptions: Array<{ label: string; value: SortOption }> = [
  { label: '名称', value: 'name' },
  { label: 'IP 地址', value: 'ip_address' },
  { label: '厂商 / 型号', value: 'model' },
  { label: '采集成功', value: 'collection_status_success' },
  { label: '采集失败', value: 'collection_status_failed' },
  { label: '采集部分成功', value: 'collection_status_partial' },
  { label: '最后采集成功时间', value: 'last_successful_collection_time' },
  { label: '连接状态', value: 'connection_status' }
]

const sortDirectionOptions = computed(() => {
  if (selectedSortField.value?.startsWith('collection_status_')) {
    return []
  }

  if (selectedSortField.value === 'last_collection_time' || selectedSortField.value === 'last_successful_collection_time') {
    return [
      { label: '旧到新', value: 'asc' },
      { label: '新到旧', value: 'desc' }
    ]
  }

  if (selectedSortField.value === 'connection_status') {
    return [
      { label: '离线优先', value: 'asc' },
      { label: '在线优先', value: 'desc' }
    ]
  }

  return [
    { label: '正序', value: 'asc' },
    { label: '倒序', value: 'desc' }
  ]
})

const currentSortHint = computed(() => {
  if (!selectedSortField.value) {
    return '当前: 默认顺序'
  }

  const fieldLabel = sortFieldOptions.find(option => option.value === selectedSortField.value)?.label || '默认顺序'
  const directionLabel = sortDirectionOptions.value.find(option => option.value === sortOrder.value)?.label || '正序'
  return `当前: ${fieldLabel} · ${directionLabel}`
})

// Batch operation states
const selectedSwitches = ref<Switch[]>([])
const showBatchSnmpDialog = ref(false)
const batchConfiguring = ref(false)
const batchSnmpFormRef = ref<FormInstance>()

const defaultCliPort = (transport?: 'ssh' | 'telnet') => transport === 'telnet' ? 23 : 22

const switchForm = reactive<SwitchCreate>({
  name: '',
  ip_address: '',
  vendor: 'cisco',
  model: '',
  cli_enabled: false,
  cli_transport: 'ssh',
  ssh_port: 22,
  username: '',
  password: '',
  enable_password: '',
  connection_timeout: 30,
  enabled: true,
  auto_collect_arp: true,
  auto_collect_mac: true,
  snmp_enabled: true,
  snmp_version: '3',
  snmp_port: 161,
  // null = 本机自带凭据，不引用模板。这是新增时的默认值：
  // 让「没选模板」和「选了某模板」在类型上就分得开。
  snmp_profile_id: null,
  snmp_username: '',
  snmp_auth_protocol: 'SHA',
  snmp_auth_password: '',
  snmp_priv_protocol: 'AES128',
  snmp_priv_password: ''
})

watch(
  () => switchForm.cli_transport,
  (newTransport, oldTransport) => {
    const previousDefaultPort = defaultCliPort(oldTransport)
    if (
      switchForm.ssh_port === undefined ||
      switchForm.ssh_port === null ||
      switchForm.ssh_port === previousDefaultPort
    ) {
      switchForm.ssh_port = defaultCliPort(newTransport)
    }
  }
)

const switchRules: FormRules = {
  name: [{ required: true, message: 'Name is required', trigger: 'blur' }],
  ip_address: [{ required: true, message: 'IP address is required', trigger: 'blur' }],
  vendor: [{ required: true, message: 'Vendor is required', trigger: 'change' }]
}

// Batch SNMP configuration form
const batchSnmpForm = reactive({
  snmp_version: '3',
  snmp_port: 161,
  // null = 不引用模板，走下面这套逐台凭据；非空 = 这批判全部改挂到该模板。
  // 显式标注 number | null，否则字面量 null 会被推断成只有 null 一种类型。
  snmp_profile_id: null as number | null,
  snmp_username: '',
  snmp_auth_protocol: 'SHA',
  snmp_auth_password: '',
  snmp_priv_protocol: 'AES128',
  snmp_priv_password: ''
})

// 规则随「凭据来源」切换：选了模板，下面那几个字段在模板上，本表单里既不显示
// 也不校验。写成 computed 而不是依赖「隐藏的 el-form-item 会自动注销」——
// 后者一旦有人把 v-if 改成 v-show 就会变成「看不见的必填项拦住提交」。
const batchSnmpRules = computed<FormRules>(() => {
  if (batchSnmpForm.snmp_profile_id) return {}

  return {
    snmp_username: [{ required: true, message: 'SNMP 用户名必填', trigger: 'blur' }],
    snmp_auth_password: [
      { required: true, message: '认证密码必填', trigger: 'blur' },
      { min: 8, message: '密码至少8位字符', trigger: 'blur' }
    ],
    snmp_priv_password: [
      {
        validator: (_rule: any, value: string, callback: (error?: Error) => void) => {
          if (value && value.length < 8) {
            callback(new Error('密码至少8位字符'))
            return
          }
          callback()
        },
        trigger: 'blur'
      }
    ]
  }
})

const loadSwitches = async () => {
  loading.value = true
  try {
    const params = {
      skip: (currentPage.value - 1) * pageSize.value,
      limit: pageSize.value,
      search: searchQuery.value.trim() || undefined,
      trunk_review_completed: showPendingTrunkOnly.value ? false : undefined,
      collection_status: collectionStatusFilter.value || undefined,
      sort_by: sortBy.value || undefined,
      sort_order: sortBy.value ? sortOrder.value : undefined
    }
    const result = await switchesApi.list(params)
    switches.value = result.items
    totalSwitches.value = result.total
  } catch (error) {
    ElMessage.error('Failed to load switches')
  } finally {
    loading.value = false
  }
}

const checkDuplicates = async () => {
  try {
    const result = await switchesApi.duplicates()
    duplicateCount.value = result.total_duplicate_groups
  } catch {
    // Ignore errors - duplicate check is non-critical
  }
}

const handleSearch = () => {
  currentPage.value = 1 // Reset to first page when searching
  loadSwitches()
}

const handlePageChange = (page: number) => {
  currentPage.value = page
  loadSwitches()
}

const handlePageSizeChange = (size: number) => {
  pageSize.value = size
  currentPage.value = 1 // Reset to first page when changing page size
  loadSwitches()
}

const togglePendingTrunkFilter = () => {
  showPendingTrunkOnly.value = !showPendingTrunkOnly.value
  currentPage.value = 1
  selectedSwitches.value = []
  loadSwitches()
}

const handleSortFieldChange = (newVal: SortOption) => {
  if (newVal?.startsWith('collection_status_')) {
    sortBy.value = null
    const statusMap: Record<string, string> = {
      collection_status_success: 'success',
      collection_status_failed: 'failed',
      collection_status_partial: 'partial'
    }
    collectionStatusFilter.value = statusMap[newVal] || ''
  } else {
    sortBy.value = newVal as SortField | null
    collectionStatusFilter.value = ''
  }
  currentPage.value = 1
  loadSwitches()
}

const handleSortOrderChange = (newOrder: 'asc' | 'desc') => {
  sortOrder.value = newOrder
  currentPage.value = 1
  loadSwitches()
}

const clearSort = () => {
  selectedSortField.value = null
  sortBy.value = null
  sortOrder.value = 'asc'
  collectionStatusFilter.value = ''
  currentPage.value = 1
  loadSwitches()
}

const handleSortChange = (newSortBy: string, newSortOrder: 'asc' | 'desc' | null) => {
  const allowedSortFields = ['name', 'ip_address', 'model', 'last_collection_time', 'last_successful_collection_time', 'connection_status']
  selectedSortField.value = newSortOrder && allowedSortFields.includes(newSortBy)
    ? newSortBy as SortOption
    : null
  sortBy.value = selectedSortField.value as SortField | null
  sortOrder.value = newSortOrder || 'asc'
  collectionStatusFilter.value = ''
  currentPage.value = 1
  loadSwitches()
}

const openAddDialog = async () => {
  resetForm()
  // 缓存里已有就不重复请求；模板页刚改过的话那边会 force 刷新。
  await snmpProfileStore.load()
  showAddDialog.value = true
}

const openBatchSnmpDialog = async () => {
  await snmpProfileStore.load()
  showBatchSnmpDialog.value = true
}

const resetForm = () => {
  Object.assign(switchForm, {
    name: '',
    ip_address: '',
    vendor: 'cisco',
    model: '',
    cli_enabled: false,
    cli_transport: 'ssh',
    ssh_port: 22,
    username: '',
    password: '',
    enable_password: '',
    connection_timeout: 30,
    enabled: true,
    auto_collect_arp: true,
    auto_collect_mac: true,
    snmp_enabled: true,
    snmp_version: '3',
    snmp_port: 161,
    snmp_profile_id: null,
    snmp_username: '',
    snmp_auth_protocol: 'SHA',
    snmp_auth_password: '',
    snmp_priv_protocol: 'AES128',
    snmp_priv_password: ''
  })
  editingSwitch.value = null
  switchFormRef.value?.clearValidate()
}

const handleEdit = (switchItem: Switch) => {
  editingSwitch.value = switchItem
  Object.assign(switchForm, {
    name: switchItem.name,
    ip_address: switchItem.ip_address,
    vendor: switchItem.vendor,
    model: switchItem.model || '',
    cli_enabled: switchItem.cli_enabled || false,
    cli_transport: switchItem.cli_transport || 'ssh',
    ssh_port: switchItem.ssh_port ?? defaultCliPort(switchItem.cli_transport || 'ssh'),
    username: switchItem.username,
    password: '',
    enable_password: '',
    connection_timeout: switchItem.connection_timeout,
    enabled: switchItem.enabled,
    auto_collect_arp: switchItem.auto_collect_arp !== undefined ? switchItem.auto_collect_arp : true,
    auto_collect_mac: switchItem.auto_collect_mac !== undefined ? switchItem.auto_collect_mac : true,
    snmp_enabled: switchItem.snmp_enabled || false,
    snmp_version: switchItem.snmp_version || '3',
    snmp_port: switchItem.snmp_port || 161,
    snmp_profile_id: switchItem.snmp_profile_id ?? null,
    snmp_username: switchItem.snmp_username || '',
    snmp_auth_protocol: switchItem.snmp_auth_protocol || 'SHA',
    snmp_auth_password: '',
    snmp_priv_protocol: switchItem.snmp_priv_protocol || 'AES128',
    snmp_priv_password: ''
  })
  showAddDialog.value = true
}

const handleSave = async () => {
  if (!switchFormRef.value) return

  await switchFormRef.value.validate(async (valid) => {
    if (!valid) return

    saving.value = true
    try {
      if (editingSwitch.value) {
        // For update, create a proper update object
        const updateData: any = {}

        // Copy all fields from switchForm
        Object.keys(switchForm).forEach(key => {
          const value = (switchForm as any)[key]
          // Only include non-empty values for update
          if (value !== '' && value !== null && value !== undefined) {
            updateData[key] = value
          } else if (typeof value === 'boolean') {
            // Include boolean values even if false
            updateData[key] = value
          }
        })

        // snmp_profile_id 必须显式带上，null 也要带。
        // 上面的循环把 null 当「空值」丢掉了，而后端把「字段不在请求里」解释成
        // 「不改动现有绑定」—— 两者语义正好相反，不补这一行，界面上就永远解不了绑。
        updateData.snmp_profile_id = switchForm.snmp_profile_id ?? null

        await switchesApi.update(editingSwitch.value.id, updateData)
        ElMessage.success('Switch updated successfully')
      } else {
        await switchesApi.create(switchForm)
        ElMessage.success('Switch created successfully')
      }
      showAddDialog.value = false
      resetForm()
      await loadSwitches()
    } catch (error: any) {
      // Error toast is shown by global response interceptor (index.ts)
    } finally {
      saving.value = false
    }
  })
}

const handleDelete = async (switchItem: Switch) => {
  try {
    await ElMessageBox.confirm(
      `Are you sure you want to delete switch "${switchItem.name}"?`,
      'Confirm Delete',
      {
        confirmButtonText: 'Delete',
        cancelButtonText: 'Cancel',
        type: 'warning'
      }
    )

    await switchesApi.delete(switchItem.id)
    ElMessage.success('Switch deleted successfully')
    await loadSwitches()
  } catch (error: any) {
    if (error !== 'cancel') {
      ElMessage.error('Failed to delete switch')
    }
  }
}

const handleTest = async (switchItem: Switch) => {
  const loading = ElMessage.info({
    message: 'Testing connection...',
    duration: 0
  })

  try {
    const result = await switchesApi.test(switchItem.id)
    loading.close()

    if (result.success) {
      ElMessage.success('Connection successful!')
    } else {
      // 失败时用弹窗而不是 toast：后端返回的中文说明可能上百字（含处置建议），
      // toast 会截断成一行看不出所以然，而且用户没法复制去排障。
      const details = result.details || {}
      const lines: any[] = [
        h('div', { style: 'line-height: 1.6;' }, result.message || '连接测试失败')
      ]

      // 备注：说明 SNMP 失败不等于采集失败（ARP/MAC 默认走 SSH CLI）
      if (details.collection_note) {
        lines.push(h('div', {
          style: 'margin-top: 8px; color: #909399; font-size: 12px; line-height: 1.6;'
        }, details.collection_note))
      }

      // 排障上下文：SNMP 版本 / 用户名 / 协议，一眼看出用的是哪套凭据
      const ctx: string[] = []
      if (details.target_ip) ctx.push(`目标：${details.target_ip}`)
      if (details.snmp_version) ctx.push(`版本：v${details.snmp_version}`)
      if (details.snmp_username) ctx.push(`用户：${details.snmp_username}`)
      if (details.snmp_auth_protocol) ctx.push(`认证协议：${details.snmp_auth_protocol}`)
      if (details.snmp_priv_protocol) ctx.push(`加密协议：${details.snmp_priv_protocol}`)
      if (ctx.length) {
        lines.push(h('div', {
          style: 'margin-top: 8px; color: #909399; font-size: 12px;'
        }, ctx.join('　')))
      }

      // pysnmp 英文原文照样给出，排障时可以直接搜索
      if (details.raw_error) {
        lines.push(h('div', {
          style: 'margin-top: 8px; color: #909399; font-size: 12px; font-family: monospace;'
        }, `原始错误：${details.raw_error}`))
      }

      ElMessageBox.alert(h('div', null, lines), '连接测试失败', {
        type: 'error',
        confirmButtonText: '知道了',
        // 报错内容需要能选中复制，默认的居中样式不方便看
        customStyle: { maxWidth: '560px' }
      }).catch(() => { /* 用户关闭弹窗，无需处理 */ })
    }
  } catch (error) {
    loading.close()
    ElMessage.error('Failed to test connection')
  }
}

const refreshHostnames = async () => {
  try {
    await ElMessageBox.confirm(
      '这将通过 SNMP 连接到所有启用且配置了 SNMP 的交换机并更新它们的 hostname，可能需要几分钟时间。是否继续？',
      '确认刷新 Hostname',
      {
        confirmButtonText: '确认',
        cancelButtonText: '取消',
        type: 'info'
      }
    )

    refreshingHostnames.value = true
    let progressMsg: any = null
    let eventSource: EventSource | null = null

    try {
      // 使用 EventSource 接收 SSE 实时进度
      eventSource = new EventSource(`${API_BASE_URL}/api/v1/discovery/refresh-hostnames`)

      eventSource.onmessage = async (event) => {
        try {
          const data = JSON.parse(event.data)

          if (data.type === 'start') {
            // 收到开始事件，显示初始进度消息
            progressMsg = ElMessage.info({
              message: `开始刷新 ${data.total} 个交换机的 hostname...`,
              duration: 0,
              showClose: false
            })
            console.log(`🚀 开始刷新 ${data.total} 个交换机的 hostname`)
          } else if (data.type === 'progress') {
            // 更新进度
            const percentage = ((data.completed / data.total) * 100).toFixed(0)
            const remainingMin = Math.floor(data.estimated_remaining_seconds / 60)
            const remainingSec = data.estimated_remaining_seconds % 60
            const timeStr = remainingMin > 0
              ? `${remainingMin}分${remainingSec}秒`
              : `${remainingSec}秒`

            const progressText = `正在处理: ${data.current_switch.name} (${data.current_switch.ip})
进度: ${data.completed}/${data.total} (${percentage}%)
✅ 已更新: ${data.updated} | ❌ 失败: ${data.failed}
${data.estimated_remaining_seconds > 0 ? `⏱️ 预计剩余: ${timeStr}` : '即将完成...'}`

            if (progressMsg) {
              progressMsg.close()
            }
            progressMsg = ElMessage.info({
              message: progressText,
              duration: 0,
              showClose: false
            })
          } else if (data.type === 'complete') {
            // 完成
            eventSource?.close()
            if (progressMsg) {
              progressMsg.close()
            }

            const duration = data.elapsed_seconds
            const minutes = Math.floor(duration / 60)
            const seconds = duration % 60
            const durationStr = minutes > 0 ? `${minutes}分${seconds}秒` : `${seconds}秒`

            const message = `刷新完成！(耗时 ${durationStr})

总计: ${data.total} 个交换机
✅ 成功更新: ${data.updated} 个
${data.failed > 0 ? `❌ 失败: ${data.failed} 个` : ''}`

            if (data.updated > 0) {
              ElMessage.success({
                message,
                duration: 5000,
                customClass: 'hostname-result-message'
              })
              // 重新加载交换机列表
              await loadSwitches()
            } else if (data.failed > 0) {
              ElMessage.warning({
                message,
                duration: 5000
              })
            } else {
              ElMessage.info({
                message: `刷新完成！所有 ${data.total} 个交换机的 hostname 都已是最新`,
                duration: 3000
              })
            }

            // 显示详细结果
            if (data.results && data.results.length > 0) {
              const failedItems = data.results.filter((r: any) => r.status === 'failed')
              const updatedItems = data.results.filter((r: any) => r.status === 'updated')

              if (failedItems.length > 0) {
                console.group('❌ 刷新 Hostname 失败详情:')
                failedItems.forEach((item: any) => {
                  console.log(`${item.ip} (${item.name}): ${item.error || '未知错误'}`)
                })
                console.groupEnd()
              }

              if (updatedItems.length > 0) {
                console.group(`✅ 成功更新 ${updatedItems.length} 个 Hostname:`)
                updatedItems.forEach((item: any) => {
                  console.log(`${item.ip}: ${item.old_name} → ${item.new_name} (via ${item.method})`)
                })
                console.groupEnd()
              }
            }

            refreshingHostnames.value = false
          } else if (data.type === 'error') {
            // 错误
            eventSource?.close()
            if (progressMsg) {
              progressMsg.close()
            }
            ElMessage.error({
              message: `刷新 hostname 失败: ${data.error}`,
              duration: 5000
            })
            console.error('Refresh hostname error:', data.error)
            refreshingHostnames.value = false
          }
        } catch (error) {
          console.error('Failed to parse SSE message:', error)
        }
      }

      eventSource.onerror = (error) => {
        console.error('SSE connection error:', error)
        eventSource?.close()
        if (progressMsg) {
          progressMsg.close()
        }
        ElMessage.error({
          message: '连接服务器失败，请检查网络或稍后重试',
          duration: 5000
        })
        refreshingHostnames.value = false
      }

    } catch (error: any) {
      if (eventSource) {
        eventSource.close()
      }
      if (progressMsg) {
        progressMsg.close()
      }
      const errorMsg = error.message || '未知错误'
      ElMessage.error({
        message: `刷新 hostname 失败: ${errorMsg}`,
        duration: 5000
      })
      console.error('Refresh hostname error:', error)
      refreshingHostnames.value = false
    }
  } catch (error: any) {
    if (error !== 'cancel') {
      console.error('Error:', error)
    }
  }
}

const refreshDeviceInfo = async () => {
  try {
    await ElMessageBox.confirm(
      '这将通过 SNMP 连接所有已配置 SNMP 的交换机，更新主机名、厂商和型号信息，可能需要几分钟。是否继续？',
      '确认刷新设备信息',
      { confirmButtonText: '确认', cancelButtonText: '取消', type: 'info' }
    )

    refreshingDeviceInfo.value = true
    let progressMsg: any = null
    let eventSource: EventSource | null = null

    try {
      eventSource = new EventSource(`${API_BASE_URL}/api/v1/discovery/refresh-device-info`)

      eventSource.onmessage = async (event) => {
        try {
          const data = JSON.parse(event.data)

          if (data.type === 'start') {
            progressMsg = ElMessage.info({
              message: `开始刷新 ${data.total} 个交换机的设备信息...`,
              duration: 0,
              showClose: false
            })
          } else if (data.type === 'progress') {
            const pct = ((data.completed / data.total) * 100).toFixed(0)
            const remSec = data.estimated_remaining_seconds
            const timeStr = remSec >= 60
              ? `${Math.floor(remSec / 60)}分${remSec % 60}秒`
              : `${remSec}秒`

            progressMsg?.close()
            progressMsg = ElMessage.info({
              message: `正在处理: ${data.current_switch.name} (${data.current_switch.ip})\n进度: ${data.completed}/${data.total} (${pct}%)   ✅ 已更新: ${data.updated} | ❌ 失败: ${data.failed}${remSec > 0 ? `\n⏱️ 预计剩余: ${timeStr}` : ''}`,
              duration: 0,
              showClose: false
            })
          } else if (data.type === 'complete') {
            eventSource?.close()
            progressMsg?.close()

            const elapsed = data.elapsed_seconds
            const durationStr = elapsed >= 60
              ? `${Math.floor(elapsed / 60)}分${elapsed % 60}秒`
              : `${elapsed}秒`

            if (data.updated > 0) {
              ElMessage.success({
                message: `刷新完成！(耗时 ${durationStr})\n总计: ${data.total} 个交换机  ✅ 更新: ${data.updated} 个  ❌ 失败: ${data.failed > 0 ? data.failed : 0} 个`,
                duration: 5000
              })
              await loadSwitches()
            } else if (data.failed > 0) {
              ElMessage.warning({
                message: `刷新完成，${data.failed} 个交换机失败，${data.total - data.failed} 个无变化`,
                duration: 4000
              })
            } else {
              ElMessage.info({ message: `刷新完成，所有交换机信息已是最新`, duration: 3000 })
            }

            // Log changes to console
            const updated = data.results?.filter((r: any) => r.status === 'updated') || []
            if (updated.length > 0) {
              console.group(`✅ 设备信息更新详情 (${updated.length} 个):`)
              updated.forEach((r: any) => {
                const parts = Object.entries(r.changes || {})
                  .map(([k, v]: any) => `${k}: ${v.from} → ${v.to}`)
                  .join(', ')
                console.log(`${r.ip}: ${parts}`)
              })
              console.groupEnd()
            }

            refreshingDeviceInfo.value = false
          } else if (data.type === 'error') {
            eventSource?.close()
            progressMsg?.close()
            ElMessage.error(`刷新设备信息失败: ${data.error}`)
            refreshingDeviceInfo.value = false
          }
        } catch (e) {
          console.error('Failed to parse SSE message:', e)
        }
      }

      eventSource.onerror = () => {
        eventSource?.close()
        progressMsg?.close()
        ElMessage.error('连接服务器失败，请检查网络或稍后重试')
        refreshingDeviceInfo.value = false
      }
    } catch (err: any) {
      eventSource?.close()
      progressMsg?.close()
      ElMessage.error(`刷新设备信息失败: ${err.message || '未知错误'}`)
      refreshingDeviceInfo.value = false
    }
  } catch (error: any) {
    if (error !== 'cancel') console.error('Error:', error)
  }
}

// Export switches list
const exportSwitches = async (format: 'excel' | 'csv') => {
  if (exportingSwitches.value) return
  exportingSwitches.value = true
  try {
    ElMessage.info('正在导出交换机列表...')
    const { exportToExcel, exportToCSV } = await import('@/utils/export')
    const data = await switchesApi.exportSwitches()
    if (!data || data.length === 0) {
      ElMessage.warning('没有交换机数据可导出')
      return
    }
    const filename = `交换机列表_${new Date().toISOString().slice(0, 10)}`
    if (format === 'excel') {
      await exportToExcel(data, filename, '交换机列表')
    } else {
      exportToCSV(data, filename)
    }
    ElMessage.success(`成功导出 ${data.length} 台交换机`)
  } catch (error: any) {
    console.error('Failed to export switches:', error)
    ElMessage.error(error.response?.data?.detail || '导出交换机列表失败')
  } finally {
    exportingSwitches.value = false
  }
}

// Batch operation handlers
const handleSelectionChange = (selection: Switch[]) => {
  selectedSwitches.value = selection
  console.log('Selection changed:', selection.length, 'switches selected')
}

const isBatchErrorResult = (result: unknown): result is { error: true } => {
  return Boolean(result && typeof result === 'object' && 'error' in result)
}

const handleBatchEnable = async () => {
  const switchesToEnable = [...selectedSwitches.value]
  const totalCount = switchesToEnable.length

  if (totalCount === 0) {
    ElMessage.warning('请先选择要启用的交换机')
    return
  }

  try {
    await ElMessageBox.confirm(
      `确认要启用选中的 ${totalCount} 个交换机吗？`,
      '批量启用',
      { confirmButtonText: '确认', cancelButtonText: '取消', type: 'info' }
    )

    // 分批处理，每批10个
    const batchSize = 10
    let successCount = 0

    for (let i = 0; i < switchesToEnable.length; i += batchSize) {
      const batch = switchesToEnable.slice(i, i + batchSize)
      const promises = batch.map(sw =>
        switchesApi.update(sw.id, { enabled: true }).catch(err => {
          console.error(`Failed to enable switch ${sw.id}:`, err)
          return { error: true }
        })
      )
      const results = await Promise.all(promises)
      successCount += results.filter(result => !isBatchErrorResult(result)).length

      if (i + batchSize < switchesToEnable.length) {
        await new Promise(resolve => setTimeout(resolve, 200))
      }
    }

    ElMessage.success(`成功启用 ${successCount} 个交换机`)
    await loadSwitches()
  } catch (error: any) {
    if (error !== 'cancel') {
      ElMessage.error('批量启用失败')
    }
  }
}

const handleBatchDisable = async () => {
  const switchesToDisable = [...selectedSwitches.value]
  const totalCount = switchesToDisable.length

  if (totalCount === 0) {
    ElMessage.warning('请先选择要禁用的交换机')
    return
  }

  try {
    await ElMessageBox.confirm(
      `确认要禁用选中的 ${totalCount} 个交换机吗？`,
      '批量禁用',
      { confirmButtonText: '确认', cancelButtonText: '取消', type: 'warning' }
    )

    // 分批处理，每批10个
    const batchSize = 10
    let successCount = 0

    for (let i = 0; i < switchesToDisable.length; i += batchSize) {
      const batch = switchesToDisable.slice(i, i + batchSize)
      const promises = batch.map(sw =>
        switchesApi.update(sw.id, { enabled: false }).catch(err => {
          console.error(`Failed to disable switch ${sw.id}:`, err)
          return { error: true }
        })
      )
      const results = await Promise.all(promises)
      successCount += results.filter(result => !isBatchErrorResult(result)).length

      if (i + batchSize < switchesToDisable.length) {
        await new Promise(resolve => setTimeout(resolve, 200))
      }
    }

    ElMessage.success(`成功禁用 ${successCount} 个交换机`)
    await loadSwitches()
  } catch (error: any) {
    if (error !== 'cancel') {
      ElMessage.error('批量禁用失败')
    }
  }
}

const handleBatchDelete = async () => {
  const switchesToDelete = [...selectedSwitches.value]
  const totalCount = switchesToDelete.length

  if (totalCount === 0) {
    ElMessage.warning('请先选择要删除的交换机')
    return
  }

  try {
    await ElMessageBox.confirm(
      `确认要删除选中的 ${totalCount} 个交换机吗？此操作不可恢复！`,
      '批量删除',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'error' }
    )

    // 分批处理，每批10个
    const batchSize = 10
    let successCount = 0

    for (let i = 0; i < switchesToDelete.length; i += batchSize) {
      const batch = switchesToDelete.slice(i, i + batchSize)
      const promises = batch.map(sw =>
        switchesApi.delete(sw.id).catch(err => {
          console.error(`Failed to delete switch ${sw.id}:`, err)
          return { error: true }
        })
      )
      const results = await Promise.all(promises)
      successCount += results.filter(result => !isBatchErrorResult(result)).length

      if (i + batchSize < switchesToDelete.length) {
        await new Promise(resolve => setTimeout(resolve, 200))
      }
    }

    ElMessage.success(`成功删除 ${successCount} 个交换机`)
    selectedSwitches.value = []
    await loadSwitches()
  } catch (error: any) {
    if (error !== 'cancel') {
      ElMessage.error('批量删除失败')
    }
  }
}

const handleBatchSnmpConfig = async () => {
  if (!batchSnmpFormRef.value) return

  await batchSnmpFormRef.value.validate(async (valid) => {
    if (!valid) return

    // 保存选中的交换机列表，防止在配置过程中被清空
    const switchesToConfigure = [...selectedSwitches.value]
    const totalCount = switchesToConfigure.length

    if (totalCount === 0) {
      ElMessage.warning('请先选择要配置的交换机')
      return
    }

    batchConfiguring.value = true

    // 显示进度消息
    const loadingMsg = ElMessage.info({
      message: `正在配置 ${totalCount} 个交换机，请稍候...`,
      duration: 0
    })

    try {
      // snmp_profile_id 每次都显式给出（null 也发）：后端把「字段不在请求里」
      // 当成「不改动绑定」，不显式发 null 就没法把设备从模板上摘下来。
      const updateData: Record<string, any> = {
        snmp_enabled: true,
        snmp_version: batchSnmpForm.snmp_version,
        snmp_port: batchSnmpForm.snmp_port,
        snmp_profile_id: batchSnmpForm.snmp_profile_id ?? null
      }

      // 引用模板时逐台凭据字段一律不发：后端本来就忽略它们，发过去只会让
      // 「这批量到底用了哪份口令」变得含糊。
      if (!batchSnmpForm.snmp_profile_id) {
        updateData.snmp_username = batchSnmpForm.snmp_username
        updateData.snmp_auth_protocol = batchSnmpForm.snmp_auth_protocol
        updateData.snmp_auth_password = batchSnmpForm.snmp_auth_password
        updateData.snmp_priv_protocol = batchSnmpForm.snmp_priv_protocol
        updateData.snmp_priv_password = batchSnmpForm.snmp_priv_password
      }

      // 分批处理，每批10个交换机，避免并发请求过多
      const batchSize = 10
      let successCount = 0
      let failCount = 0

      for (let i = 0; i < switchesToConfigure.length; i += batchSize) {
        const batch = switchesToConfigure.slice(i, i + batchSize)

        // 更新进度消息
        loadingMsg.close()
        const progressMsg = ElMessage.info({
          message: `正在配置 ${i + 1}-${Math.min(i + batchSize, totalCount)}/${totalCount} 个交换机...`,
          duration: 0
        })

        try {
          const promises = batch.map(sw =>
            switchesApi.update(sw.id, updateData).catch(err => {
              console.error(`Failed to configure switch ${sw.id}:`, err)
              return { error: true, switch: sw }
            })
          )

          const results = await Promise.all(promises)

          // 统计成功和失败数量
          results.forEach(result => {
            if (isBatchErrorResult(result)) {
              failCount++
            } else {
              successCount++
            }
          })

          progressMsg.close()
        } catch (error) {
          progressMsg.close()
          console.error('Batch error:', error)
          failCount += batch.length
        }

        // 批次之间短暂延迟，避免服务器过载
        if (i + batchSize < switchesToConfigure.length) {
          await new Promise(resolve => setTimeout(resolve, 200))
        }
      }

      // 显示最终结果
      if (failCount === 0) {
        ElMessage.success(`成功为 ${successCount} 个交换机配置 SNMP`)
      } else if (successCount > 0) {
        ElMessage.warning(`配置完成：成功 ${successCount} 个，失败 ${failCount} 个`)
      } else {
        ElMessage.error(`配置失败：所有 ${failCount} 个交换机都配置失败`)
      }

      showBatchSnmpDialog.value = false

      // Reset form
      Object.assign(batchSnmpForm, {
        snmp_version: '3',
        snmp_port: 161,
        snmp_profile_id: null,
        snmp_username: '',
        snmp_auth_protocol: 'SHA',
        snmp_auth_password: '',
        snmp_priv_protocol: 'AES128',
        snmp_priv_password: ''
      })
      batchSnmpFormRef.value?.clearValidate()

      await loadSwitches()
    } catch (error: any) {
      loadingMsg.close()
      ElMessage.error('批量配置 SNMP 失败: ' + (error.message || '未知错误'))
      console.error('Batch SNMP config error:', error)
    } finally {
      batchConfiguring.value = false
    }
  })
}

onMounted(() => {
  loadSwitches()
  checkDuplicates()
  // 预取凭据模板列表，免得打开对话框时下拉框先空一下再冒出来。
  // store 内部有缓存，这个页面来回切也只请求一次。
  snmpProfileStore.load()
})
</script>

<style scoped>
.switches-view {
  max-width: 1400px;
  margin: 0 auto;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-actions {
  display: flex;
  gap: 10px;
}

.card-header h2 {
  margin: 0;
  color: #303133;
}

.search-bar {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
  align-items: center;
  flex-wrap: wrap;
}

.search-controls {
  display: flex;
  gap: 10px;
  align-items: center;
  flex: 1 1 420px;
  flex-wrap: wrap;
}

.search-input {
  max-width: 420px;
}


.sort-controls {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 10px 14px;
  background: #f5f7fa;
  border: 1px solid #e4e7ed;
  border-radius: 10px;
}

.sort-label {
  font-size: 13px;
  color: #606266;
  font-weight: 600;
}

.sort-field-select {
  width: 150px;
}

.sort-hint {
  font-size: 12px;
  color: #909399;
}

.pagination-container {
  display: flex;
  justify-content: center;
  margin-top: 20px;
  padding: 10px 0;
}

.batch-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  margin-bottom: 16px;
  background-color: #f5f7fa;
  border-radius: 4px;
  border: 1px solid #e4e7ed;
}

.batch-info {
  display: flex;
  align-items: center;
}

.batch-actions {
  display: flex;
  gap: 8px;
}

@media (max-width: 900px) {
  .search-controls,
  .sort-controls {
    width: 100%;
  }

  .search-input,
  .sort-field-select {
    width: 100%;
    max-width: none;
  }
}
</style>
