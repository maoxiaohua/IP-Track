<template>
  <div class="snmp-profiles">
    <el-card>
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center">
          <h2 style="margin: 0">SNMP Profiles Management</h2>
          <el-button type="primary" @click="showCreateDialog = true">
            <el-icon><Plus /></el-icon>
            Add SNMP Profile
          </el-button>
        </div>
      </template>

      <!-- Profile List Table -->
      <el-table :data="profiles" v-loading="loading" stripe style="width: 100%">
        <el-table-column prop="name" label="Profile Name" min-width="150">
          <template #default="{ row }">
            <strong>{{ row.name }}</strong>
          </template>
        </el-table-column>

        <el-table-column label="Version" width="100">
          <template #default="{ row }">
            <el-tag :type="row.version === 'v3' ? 'success' : 'info'" size="small">
              {{ row.version.toUpperCase() }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column prop="username" label="Username" min-width="120">
          <template #default="{ row }">
            {{ row.username || '-' }}
          </template>
        </el-table-column>

        <el-table-column label="Auth/Priv" min-width="150">
          <template #default="{ row }">
            <span v-if="row.version === 'v3'">
              {{ row.auth_protocol || 'SHA' }} / {{ row.priv_protocol || 'AES' }}
            </span>
            <span v-else style="color: #909399">Community-based</span>
          </template>
        </el-table-column>

        <el-table-column prop="port" label="Port" width="80" />

        <el-table-column label="Status" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="row.enabled ? 'success' : 'info'" size="small">
              {{ row.enabled ? 'Enabled' : 'Disabled' }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column prop="subnet_count" label="Subnets" width="100" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.subnet_count > 0" type="warning" size="small">
              {{ row.subnet_count }}
            </el-tag>
            <span v-else style="color: #909399">0</span>
          </template>
        </el-table-column>

        <!-- 使用中的交换机数：改口令、停用、删除之前先看这一列，一眼知道这一下
             会波及多少台设备。后端在它不为 0 时直接拒删，这一列就是那个拒绝理由的出处。 -->
        <el-table-column prop="switch_count" label="使用中的交换机数" width="150" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.switch_count > 0" type="danger" size="small">
              {{ row.switch_count }}
            </el-tag>
            <span v-else style="color: #909399">0</span>
          </template>
        </el-table-column>

        <el-table-column prop="description" label="Description" min-width="150">
          <template #default="{ row }">
            {{ row.description || '-' }}
          </template>
        </el-table-column>

        <el-table-column label="Actions" width="330" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="info" plain @click="testProfile(row)">
              <el-icon><Connection /></el-icon>
              Test
            </el-button>
            <el-button
              size="small"
              type="warning"
              plain
              @click="openAdoptDialog(row)"
            >
              <el-icon><Link /></el-icon>
              引用
            </el-button>
            <el-button size="small" type="primary" @click="editProfile(row)">
              <el-icon><Edit /></el-icon>
              Edit
            </el-button>
            <el-button
              size="small"
              type="danger"
              @click="deleteProfile(row)"
              :disabled="row.subnet_count > 0 || row.switch_count > 0"
            >
              <el-icon><Delete /></el-icon>
              Delete
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- Pagination -->
      <el-pagination
        v-model:current-page="pagination.page"
        v-model:page-size="pagination.pageSize"
        :page-sizes="[10, 20, 50, 100]"
        :total="pagination.total"
        layout="total, sizes, prev, pager, next, jumper"
        @size-change="loadProfiles"
        @current-change="loadProfiles"
        style="margin-top: 20px; justify-content: center"
      />
    </el-card>

    <!-- Create/Edit Dialog -->
    <el-dialog
      v-model="showCreateDialog"
      :title="editMode ? 'Edit SNMP Profile' : 'Create SNMP Profile'"
      width="700px"
      @close="resetForm"
    >
      <el-form :model="profileForm" :rules="formRules" ref="profileFormRef" label-width="140px">
        <el-form-item label="Profile Name" prop="name" required>
          <el-input v-model="profileForm.name" placeholder="e.g., Production-SNMPv3" />
        </el-form-item>

        <el-form-item label="SNMP Version" prop="version" required>
          <el-radio-group v-model="profileForm.version">
            <el-radio value="v3">SNMPv3 (Recommended)</el-radio>
            <el-radio value="v2c">SNMPv2c</el-radio>
          </el-radio-group>
        </el-form-item>

        <!-- SNMPv3 Settings -->
        <template v-if="profileForm.version === 'v3'">
          <el-divider content-position="left">SNMPv3 Authentication</el-divider>

          <el-form-item label="Username" prop="username" required>
            <el-input v-model="profileForm.username" placeholder="SNMP username" />
          </el-form-item>

          <!-- 协议清单必须跟后端 AUTH_PROTOCOL_MAP 一一对应。后端对认不出的协议名
               是**静默回退到 SHA** 的，设备侧只会回一个 WrongDigest，跟口令配错
               长得一模一样。把可选项收全，就不给人写出认不出的值的机会。 -->
          <el-form-item label="Auth Protocol" prop="auth_protocol">
            <el-select v-model="profileForm.auth_protocol" placeholder="Select protocol">
              <el-option label="SHA (Recommended)" value="SHA" />
              <el-option label="MD5" value="MD5" />
              <el-option label="SHA-224" value="SHA-224" />
              <el-option label="SHA-256" value="SHA-256" />
              <el-option label="SHA-384" value="SHA-384" />
              <el-option label="SHA-512" value="SHA-512" />
            </el-select>
          </el-form-item>

          <el-form-item label="Auth Password" prop="auth_password" required>
            <el-input
              v-model="profileForm.auth_password"
              type="password"
              placeholder="Authentication password"
              show-password
            />
          </el-form-item>

          <el-divider content-position="left">SNMPv3 Privacy (Optional)</el-divider>

          <el-form-item label="Privacy Protocol" prop="priv_protocol">
            <el-select v-model="profileForm.priv_protocol" placeholder="Select protocol" clearable>
              <el-option label="AES-128 (Recommended)" value="AES-128" />
              <el-option label="AES-192" value="AES-192" />
              <el-option label="AES-256" value="AES-256" />
              <el-option label="AES" value="AES" />
              <el-option label="DES" value="DES" />
            </el-select>
          </el-form-item>

          <el-form-item label="Privacy Password" prop="priv_password">
            <el-input
              v-model="profileForm.priv_password"
              type="password"
              placeholder="Privacy password (optional)"
              show-password
            />
          </el-form-item>
        </template>

        <!-- SNMPv2c Settings -->
        <template v-else>
          <el-divider content-position="left">SNMPv2c Settings</el-divider>

          <el-form-item label="Community String" prop="community" required>
            <el-input
              v-model="profileForm.community"
              type="password"
              placeholder="Community string (e.g., public)"
              show-password
            />
          </el-form-item>
        </template>

        <el-divider content-position="left">Connection Settings</el-divider>

        <el-form-item label="Port" prop="port">
          <el-input-number v-model="profileForm.port" :min="1" :max="65535" />
        </el-form-item>

        <el-form-item label="Timeout (seconds)" prop="timeout">
          <el-input-number v-model="profileForm.timeout" :min="1" :max="60" />
        </el-form-item>

        <el-form-item label="Retries" prop="retries">
          <el-input-number v-model="profileForm.retries" :min="0" :max="10" />
        </el-form-item>

        <el-form-item label="Description" prop="description">
          <el-input
            v-model="profileForm.description"
            type="textarea"
            :rows="3"
            placeholder="Optional description"
          />
        </el-form-item>

        <el-form-item label="Enabled">
          <el-switch v-model="profileForm.enabled" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="showCreateDialog = false">Cancel</el-button>
        <el-button type="primary" @click="handleSubmit" :loading="submitting">
          {{ editMode ? 'Update' : 'Create' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- Adopt Dialog：把已经用着同一份凭据的历史交换机改成引用这个模板 -->
    <el-dialog
      v-model="showAdoptDialog"
      :title="`把交换机引用到模板「${adoptingProfile?.name ?? ''}」`"
      width="720px"
      @close="resetAdopt"
    >
      <el-alert type="info" :closable="false" show-icon style="margin-bottom: 16px">
        <p>把<strong>已经用着同一份凭据</strong>的交换机改成引用这个模板。凭据一字未改，
           行为不变，只是以后改口令只需改模板一处。</p>
        <p>对不上的交换机会被原样跳过 —— 迁移脚本故意不回填，就是为了避免在没逐一核对
           的情况下改掉全网的凭据来源。</p>
      </el-alert>

      <div v-loading="adoptLoading" style="min-height: 120px">
        <el-alert
          v-if="adoptError"
          :title="adoptError"
          type="error"
          :closable="false"
          show-icon
        />

        <template v-else-if="adoptReport">
          <el-descriptions :column="3" border size="small" style="margin-bottom: 16px">
            <el-descriptions-item label="检查台数">
              {{ adoptReport.examined }}
            </el-descriptions-item>
            <el-descriptions-item label="可以引用">
              <el-tag :type="adoptReport.matched_count > 0 ? 'success' : 'info'" size="small">
                {{ adoptReport.matched_count }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="跳过">
              {{ adoptReport.skipped_count }}
            </el-descriptions-item>
          </el-descriptions>

          <el-table
            v-if="adoptReport.matched.length > 0"
            :data="adoptReport.matched"
            size="small"
            border
            max-height="220"
            style="margin-bottom: 12px"
          >
            <el-table-column prop="name" label="交换机名称" min-width="180" />
            <el-table-column prop="ip_address" label="IP 地址" width="150" />
          </el-table>
          <el-alert
            v-else
            title="没有交换机的凭据跟这个模板完全一致，这次不会改动任何设备。"
            type="warning"
            :closable="false"
            show-icon
            style="margin-bottom: 12px"
          />

          <!-- 跳过原因只给分类计数，不列具体设备：响应里本来就不带
               「哪几台凭据跟模板不一样」，那本身属于敏感信息。 -->
          <div v-if="adoptReport.skipped_count > 0" class="skip-reasons">
            <div class="skip-reasons-title">跳过的交换机（按原因归类）：</div>
            <el-tag
              v-for="(count, reason) in adoptReport.skipped_by_reason"
              :key="reason"
              type="info"
              size="small"
              class="skip-reason-tag"
            >
              {{ ADOPT_SKIP_REASONS[reason] || reason }}：{{ count }}
            </el-tag>
          </div>
        </template>
      </div>

      <template #footer>
        <el-button @click="showAdoptDialog = false">取消</el-button>
        <el-button type="warning" plain @click="refreshAdoptPreview" :loading="adoptLoading">
          重新检查
        </el-button>
        <el-button
          type="primary"
          @click="confirmAdopt"
          :loading="adoptApplying"
          :disabled="adoptLoading || !adoptReport || adoptReport.matched_count === 0"
        >
          确认引用 {{ adoptReport?.matched_count ?? 0 }} 台
        </el-button>
      </template>
    </el-dialog>

    <!-- Test Dialog -->
    <el-dialog v-model="showTestDialog" title="Test SNMP Connection" width="600px">
      <el-form :model="testForm" label-width="120px">
        <el-form-item label="Target IP" required>
          <el-input v-model="testForm.target_ip" placeholder="e.g., 10.0.0.1" />
        </el-form-item>

        <el-form-item label="Profile">
          <el-input v-model="testingProfileName" disabled />
        </el-form-item>
      </el-form>

      <el-alert
        v-if="testResult"
        :title="testResult.message"
        :type="testResult.success ? 'success' : 'error'"
        :closable="false"
        style="margin-bottom: 15px"
      >
        <template v-if="testResult.success && testResult.data">
          <div style="margin-top: 10px">
            <p v-if="testResult.data.system_name">
              <strong>System Name:</strong> {{ testResult.data.system_name }}
            </p>
            <p v-if="testResult.data.location">
              <strong>Location:</strong> {{ testResult.data.location }}
            </p>
            <p v-if="testResult.data.contact">
              <strong>Contact:</strong> {{ testResult.data.contact }}
            </p>
            <p v-if="testResult.data.vendor">
              <strong>Vendor:</strong> {{ testResult.data.vendor }}
            </p>
            <p v-if="testResult.data.machine_type">
              <strong>Machine Type:</strong> {{ testResult.data.machine_type }}
            </p>
          </div>
        </template>
        <template v-else-if="!testResult.success && testResult.error">
          <div style="margin-top: 10px">
            <p><strong>Error:</strong> {{ testResult.error }}</p>
          </div>
        </template>
      </el-alert>

      <template #footer>
        <el-button @click="showTestDialog = false">Close</el-button>
        <el-button type="primary" @click="handleTest" :loading="testing">
          Test Connection
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Edit, Delete, Connection, Link } from '@element-plus/icons-vue'
import {
  getSNMPProfiles,
  createSNMPProfile,
  updateSNMPProfile,
  deleteSNMPProfile,
  adoptSwitchesIntoProfile,
  testSNMPConnection,
  type SNMPProfile,
  type SNMPProfileCreate,
  type SNMPProfileAdoptResponse,
  type SNMPTestResponse
} from '@/api/snmpProfiles'
// 模板一改，其他页面下拉框里显示的还是旧名字。共用的缓存放在 store 里，
// 这里负责在增删改之后把它刷掉。
import { useSNMPProfilesStore } from '@/stores/snmpProfiles'

const snmpProfileStore = useSNMPProfilesStore()

const loading = ref(false)
const submitting = ref(false)
const testing = ref(false)
const profiles = ref<SNMPProfile[]>([])
const showCreateDialog = ref(false)
const showTestDialog = ref(false)
const editMode = ref(false)
const editingProfileId = ref<number | null>(null)
const profileFormRef = ref()
const testResult = ref<SNMPTestResponse | null>(null)
const testingProfileName = ref('')

// 引用（adopt）对话框
const showAdoptDialog = ref(false)
const adoptingProfile = ref<SNMPProfile | null>(null)
const adoptLoading = ref(false)
const adoptApplying = ref(false)
const adoptReport = ref<SNMPProfileAdoptResponse | null>(null)
const adoptError = ref<string | null>(null)

/**
 * 后端给出的跳过原因 -> 给人看的话。
 *
 * 这几个 key 是固定枚举（后端只给分类计数，不给具体是哪台），
 * 认不出的 key 原样显示，免得后端加了新分类这里显示成空白。
 */
const ADOPT_SKIP_REASONS: Record<string, string> = {
  no_credentials: '本机没有任何凭据',
  different_version: 'SNMP 版本不同',
  different_username: '用户名不同',
  different_auth_protocol: '认证协议不同',
  different_priv_protocol: '加密协议不同',
  different_auth_password: '认证口令不同',
  different_priv_password: '加密口令不同'
}

const pagination = reactive({
  page: 1,
  pageSize: 20,
  total: 0
})

const profileForm = reactive<SNMPProfileCreate>({
  name: '',
  version: 'v3',
  username: '',
  auth_protocol: 'SHA',
  auth_password: '',
  priv_protocol: 'AES',
  priv_password: '',
  community: '',
  port: 161,
  timeout: 5,
  retries: 3,
  description: '',
  enabled: true
})

const testForm = reactive({
  target_ip: '',
  profile_id: undefined as number | undefined
})

const formRules = {
  name: [{ required: true, message: 'Profile name is required', trigger: 'blur' }],
  version: [{ required: true, message: 'SNMP version is required', trigger: 'change' }],
  username: [
    {
      required: true,
      validator: (_: any, value: string, callback: any) => {
        if (profileForm.version === 'v3' && !value) {
          callback(new Error('Username is required for SNMPv3'))
        } else {
          callback()
        }
      },
      trigger: 'blur'
    }
  ],
  auth_password: [
    {
      required: true,
      validator: (_: any, value: string, callback: any) => {
        if (profileForm.version === 'v3' && !value && !editMode.value) {
          callback(new Error('Auth password is required for SNMPv3'))
        } else {
          callback()
        }
      },
      trigger: 'blur'
    }
  ],
  community: [
    {
      required: true,
      validator: (_: any, value: string, callback: any) => {
        if (profileForm.version === 'v2c' && !value && !editMode.value) {
          callback(new Error('Community string is required for SNMPv2c'))
        } else {
          callback()
        }
      },
      trigger: 'blur'
    }
  ]
}

// Load profiles
const loadProfiles = async () => {
  loading.value = true
  try {
    const response = await getSNMPProfiles({
      page: pagination.page,
      page_size: pagination.pageSize
    })
    profiles.value = response.items
    pagination.total = response.total
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || 'Failed to load SNMP profiles')
  } finally {
    loading.value = false
  }
}

// Reset form
const resetForm = () => {
  editMode.value = false
  editingProfileId.value = null
  Object.assign(profileForm, {
    name: '',
    version: 'v3',
    username: '',
    auth_protocol: 'SHA',
    auth_password: '',
    priv_protocol: 'AES',
    priv_password: '',
    community: '',
    port: 161,
    timeout: 5,
    retries: 3,
    description: '',
    enabled: true
  })
  profileFormRef.value?.clearValidate()
}

// Edit profile
const editProfile = (profile: SNMPProfile) => {
  editMode.value = true
  editingProfileId.value = profile.id
  Object.assign(profileForm, {
    name: profile.name,
    version: profile.version,
    username: profile.username || '',
    auth_protocol: profile.auth_protocol || 'SHA',
    auth_password: '', // Don't populate password
    priv_protocol: profile.priv_protocol || 'AES',
    priv_password: '', // Don't populate password
    community: '', // Don't populate community
    port: profile.port,
    timeout: profile.timeout,
    retries: profile.retries,
    description: profile.description || '',
    enabled: profile.enabled
  })
  showCreateDialog.value = true
}

// Submit form
const handleSubmit = async () => {
  try {
    await profileFormRef.value.validate()

    submitting.value = true

    if (editMode.value && editingProfileId.value) {
      // Update existing profile
      const updateData: any = { ...profileForm }
      // Remove empty passwords
      if (!updateData.auth_password) delete updateData.auth_password
      if (!updateData.priv_password) delete updateData.priv_password
      if (!updateData.community) delete updateData.community

      await updateSNMPProfile(editingProfileId.value, updateData)
      ElMessage.success('SNMP profile updated successfully')
    } else {
      // Create new profile
      await createSNMPProfile(profileForm)
      ElMessage.success('SNMP profile created successfully')
    }

    showCreateDialog.value = false
    await loadProfiles()
    // 刚改完名字/新增/停用，别的页面下拉框里缓存的那份就旧了，强制刷新。
    await snmpProfileStore.load(true)
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || 'Failed to save SNMP profile')
  } finally {
    submitting.value = false
  }
}

// Delete profile
const deleteProfile = async (profile: SNMPProfile) => {
  try {
    await ElMessageBox.confirm(
      `Are you sure you want to delete profile "${profile.name}"?`,
      'Warning',
      {
        confirmButtonText: 'Delete',
        cancelButtonText: 'Cancel',
        type: 'warning'
      }
    )

    await deleteSNMPProfile(profile.id)
    ElMessage.success('SNMP profile deleted successfully')
    await loadProfiles()
    // 删掉的模板不能再留在别的页面的下拉框里
    await snmpProfileStore.load(true)
  } catch (error: any) {
    if (error !== 'cancel') {
      ElMessage.error(error.response?.data?.detail || 'Failed to delete SNMP profile')
    }
  }
}

// Test profile
const testProfile = (profile: SNMPProfile) => {
  testForm.profile_id = profile.id
  testForm.target_ip = ''
  testingProfileName.value = profile.name
  testResult.value = null
  showTestDialog.value = true
}

// Handle test
const handleTest = async () => {
  if (!testForm.target_ip) {
    ElMessage.warning('Please enter a target IP address')
    return
  }

  testing.value = true
  testResult.value = null

  try {
    const result = await testSNMPConnection({
      target_ip: testForm.target_ip,
      profile_id: testForm.profile_id
    })
    testResult.value = result
  } catch (error: any) {
    ElMessage.error('Failed to test SNMP connection')
  } finally {
    testing.value = false
  }
}

// ---- 引用（adopt）----

/**
 * 打开引用对话框，并立刻跑一次「只看不动」的预检。
 *
 * 预检是 dry_run，不写库。先给人看清这一下会动到哪几台、跳过多少台，
 * 再让人决定要不要真做 —— 这个操作会把被引用交换机本机那份凭据清掉。
 */
const openAdoptDialog = async (profile: SNMPProfile) => {
  adoptingProfile.value = profile
  adoptReport.value = null
  adoptError.value = null
  showAdoptDialog.value = true
  await refreshAdoptPreview()
}

// 重新预检（dry_run=true，不写库）
const refreshAdoptPreview = async () => {
  if (!adoptingProfile.value) return

  adoptLoading.value = true
  adoptError.value = null

  try {
    adoptReport.value = await adoptSwitchesIntoProfile(adoptingProfile.value.id, {
      dry_run: true
    })
  } catch (error: any) {
    adoptReport.value = null
    adoptError.value = error.response?.data?.detail || error.message || '预检失败'
  } finally {
    adoptLoading.value = false
  }
}

// 确认引用：真正写库
const confirmAdopt = async () => {
  const profile = adoptingProfile.value
  const count = adoptReport.value?.matched_count ?? 0
  if (!profile || count === 0) return

  try {
    await ElMessageBox.confirm(
      `将把 ${count} 台交换机改成引用模板「${profile.name}」。` +
        '这些交换机本机保存的那份凭据会被清除，之后一律以模板为准。' +
        '要现在执行吗？',
      '确认引用',
      {
        confirmButtonText: '确认引用',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
  } catch {
    // 用户取消，什么都不做
    return
  }

  adoptApplying.value = true

  try {
    const result = await adoptSwitchesIntoProfile(profile.id, { dry_run: false })
    ElMessage.success(`已让 ${result.matched_count} 台交换机引用该模板`)
    showAdoptDialog.value = false
    await loadProfiles()
    // 别的页面下拉框里还挂着旧的模板信息，这里一并刷掉。
    await snmpProfileStore.load(true)
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || error.message || '引用失败')
  } finally {
    adoptApplying.value = false
  }
}

// 关对话框时把上一次的结果清干净，免得下次打开先闪一眼旧数据
const resetAdopt = () => {
  adoptingProfile.value = null
  adoptReport.value = null
  adoptError.value = null
}

onMounted(() => {
  loadProfiles()
})
</script>

<style scoped>
.snmp-profiles {
  padding: 20px;
}

:deep(.el-table) {
  font-size: 13px;
}

:deep(.el-table th) {
  background-color: #f5f7fa;
  font-weight: 600;
}

:deep(.el-divider__text) {
  font-weight: 600;
  color: var(--primary-color);
}

/* 跳过原因按分类列成标签。左对齐换行，不撑破对话框宽度。 */
.skip-reasons {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.skip-reasons-title {
  font-size: 13px;
  color: #606266;
}

.skip-reason-tag {
  margin: 0;
}
</style>
