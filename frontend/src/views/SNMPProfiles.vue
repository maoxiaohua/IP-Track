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

        <el-table-column prop="description" label="Description" min-width="150">
          <template #default="{ row }">
            {{ row.description || '-' }}
          </template>
        </el-table-column>

        <el-table-column label="Actions" width="250" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="info" plain @click="testProfile(row)">
              <el-icon><Connection /></el-icon>
              Test
            </el-button>
            <el-button size="small" type="primary" @click="editProfile(row)">
              <el-icon><Edit /></el-icon>
              Edit
            </el-button>
            <el-button
              size="small"
              type="danger"
              @click="deleteProfile(row)"
              :disabled="row.subnet_count > 0"
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

          <el-form-item label="Auth Protocol" prop="auth_protocol">
            <el-select v-model="profileForm.auth_protocol" placeholder="Select protocol">
              <el-option label="SHA (Recommended)" value="SHA" />
              <el-option label="SHA-256" value="SHA-256" />
              <el-option label="MD5" value="MD5" />
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
              <el-option label="AES (Recommended)" value="AES" />
              <el-option label="AES-256" value="AES-256" />
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
import { Plus, Edit, Delete, Connection } from '@element-plus/icons-vue'
import {
  getSNMPProfiles,
  createSNMPProfile,
  updateSNMPProfile,
  deleteSNMPProfile,
  testSNMPConnection,
  type SNMPProfile,
  type SNMPProfileCreate,
  type SNMPTestResponse
} from '@/api/snmpProfiles'

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
  color: #409eff;
}
</style>
