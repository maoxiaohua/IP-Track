<template>
  <div class="switches-view">
    <el-card>
      <template #header>
        <div class="card-header">
          <h2>Switch Management</h2>
          <el-button type="primary" @click="showAddDialog = true">
            <el-icon><Plus /></el-icon>
            Add Switch
          </el-button>
        </div>
      </template>

      <SwitchList
        :switches="switches"
        :loading="loading"
        @refresh="loadSwitches"
        @edit="handleEdit"
        @delete="handleDelete"
        @test="handleTest"
      />
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

        <el-form-item label="Role" prop="role">
          <el-select v-model="switchForm.role" placeholder="Select role">
            <el-option label="Core (三层核心)" value="core" />
            <el-option label="Aggregation (汇聚)" value="aggregation" />
            <el-option label="Access (接入)" value="access" />
          </el-select>
        </el-form-item>

        <el-form-item label="Priority" prop="priority">
          <el-input-number v-model="switchForm.priority" :min="1" :max="100" />
          <span style="margin-left: 8px; color: #909399;">1=highest, 100=lowest</span>
        </el-form-item>

        <el-form-item label="SSH Port" prop="ssh_port">
          <el-input-number v-model="switchForm.ssh_port" :min="1" :max="65535" />
        </el-form-item>

        <el-form-item label="Username" prop="username">
          <el-input v-model="switchForm.username" placeholder="SSH username" />
        </el-form-item>

        <el-form-item label="Password" prop="password">
          <el-input
            v-model="switchForm.password"
            type="password"
            placeholder="SSH password"
            show-password
          />
        </el-form-item>

        <el-form-item label="Enable Password" prop="enable_password">
          <el-input
            v-model="switchForm.enable_password"
            type="password"
            placeholder="Enable password (Cisco only)"
            show-password
          />
        </el-form-item>

        <el-form-item label="Connection Timeout" prop="connection_timeout">
          <el-input-number v-model="switchForm.connection_timeout" :min="5" :max="300" />
          <span style="margin-left: 8px; color: #909399;">seconds</span>
        </el-form-item>

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
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { switchesApi, type Switch, type SwitchCreate } from '@/api/switches'
import SwitchList from '@/components/SwitchList.vue'

const switches = ref<Switch[]>([])
const loading = ref(false)
const saving = ref(false)
const showAddDialog = ref(false)
const editingSwitch = ref<Switch | null>(null)
const switchFormRef = ref<FormInstance>()

const switchForm = reactive<SwitchCreate>({
  name: '',
  ip_address: '',
  vendor: 'cisco',
  model: '',
  role: 'access',
  priority: 50,
  ssh_port: 22,
  username: '',
  password: '',
  enable_password: '',
  connection_timeout: 30,
  enabled: true
})

const switchRules: FormRules = {
  name: [{ required: true, message: 'Name is required', trigger: 'blur' }],
  ip_address: [{ required: true, message: 'IP address is required', trigger: 'blur' }],
  vendor: [{ required: true, message: 'Vendor is required', trigger: 'change' }],
  username: [{ required: true, message: 'Username is required', trigger: 'blur' }],
  password: [{ required: true, message: 'Password is required', trigger: 'blur' }]
}

const loadSwitches = async () => {
  loading.value = true
  try {
    switches.value = await switchesApi.list()
  } catch (error) {
    ElMessage.error('Failed to load switches')
  } finally {
    loading.value = false
  }
}

const resetForm = () => {
  Object.assign(switchForm, {
    name: '',
    ip_address: '',
    vendor: 'cisco',
    model: '',
    role: 'access',
    priority: 50,
    ssh_port: 22,
    username: '',
    password: '',
    enable_password: '',
    connection_timeout: 30,
    enabled: true
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
    role: switchItem.role || 'access',
    priority: switchItem.priority || 50,
    ssh_port: switchItem.ssh_port,
    username: switchItem.username,
    password: '',
    enable_password: '',
    connection_timeout: switchItem.connection_timeout,
    enabled: switchItem.enabled
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
        await switchesApi.update(editingSwitch.value.id, switchForm)
        ElMessage.success('Switch updated successfully')
      } else {
        await switchesApi.create(switchForm)
        ElMessage.success('Switch created successfully')
      }
      showAddDialog.value = false
      resetForm()
      await loadSwitches()
    } catch (error) {
      ElMessage.error('Failed to save switch')
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
      ElMessage.error(`Connection failed: ${result.message}`)
    }
  } catch (error) {
    loading.close()
    ElMessage.error('Failed to test connection')
  }
}

onMounted(() => {
  loadSwitches()
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

.card-header h2 {
  margin: 0;
  color: #303133;
}
</style>
