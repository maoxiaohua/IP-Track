<template>
  <div class="command-templates-view">
    <el-card>
      <template #header>
        <div class="card-header">
          <h2>交换机命令模板管理</h2>
          <p>配置不同厂商交换机的 ARP 和 MAC 收集命令</p>
          <div>
            <el-button type="primary" @click="showAddDialog = true" :icon="Plus">
              添加模板
            </el-button>
            <el-button type="primary" @click="loadTemplates" :icon="Refresh">
              刷新
            </el-button>
          </div>
        </div>
      </template>

      <!-- Templates Table -->
      <el-table
        :data="templates"
        v-loading="loading"
        stripe
        style="width: 100%"
      >
        <el-table-column prop="id" label="ID" width="60" />

        <el-table-column prop="vendor" label="厂商" width="100">
          <template #default="{ row }">
            <el-tag :type="getVendorTagType(row.vendor)">
              {{ row.vendor.toUpperCase() }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column prop="model_pattern" label="型号模式" width="120" />

        <el-table-column prop="device_type" label="设备类型" width="140">
          <template #default="{ row }">
            <el-text size="small">{{ row.device_type }}</el-text>
          </template>
        </el-table-column>

        <el-table-column label="ARP" width="200">
          <template #default="{ row }">
            <div v-if="row.arp_enabled && row.arp_command">
              <el-tag type="success" size="small">启用</el-tag>
              <el-text size="small" style="margin-left: 5px">{{ row.arp_parser_type }}</el-text>
            </div>
            <el-tag v-else type="info" size="small">禁用</el-tag>
          </template>
        </el-table-column>

        <el-table-column label="MAC" width="200">
          <template #default="{ row }">
            <div v-if="row.mac_enabled && row.mac_command">
              <el-tag type="success" size="small">启用</el-tag>
              <el-text size="small" style="margin-left: 5px">{{ row.mac_parser_type }}</el-text>
            </div>
            <el-tag v-else type="info" size="small">禁用</el-tag>
          </template>
        </el-table-column>

        <el-table-column prop="priority" label="优先级" width="90">
          <template #default="{ row }">
            <el-tag :type="getPriorityTagType(row.priority)">
              {{ row.priority }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column prop="enabled" label="状态" width="90">
          <template #default="{ row }">
            <el-switch
              v-model="row.enabled"
              @change="toggleEnabled(row)"
              :disabled="loading"
            />
          </template>
        </el-table-column>

        <el-table-column label="内置" width="80">
          <template #default="{ row }">
            <el-tag v-if="row.is_builtin" type="warning" size="small">内置</el-tag>
            <el-tag v-else type="" size="small">自定义</el-tag>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="320" fixed="right">
          <template #default="{ row }">
            <el-button
              size="small"
              @click="showTemplateDetails(row)"
              :icon="View"
            >
              查看
            </el-button>
            <el-button
              size="small"
              type="primary"
              @click="showTestDialog(row)"
              :icon="Connection"
            >
              测试
            </el-button>
            <el-button
              size="small"
              @click="showEditDialog(row)"
              :icon="Edit"
            >
              编辑
            </el-button>
            <el-button
              v-if="!row.is_builtin"
              size="small"
              type="danger"
              @click="deleteTemplate(row)"
              :icon="Delete"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- Add/Edit Dialog -->
    <el-dialog
      v-model="showAddDialog"
      :title="editingTemplate ? '编辑模板' : '添加模板'"
      width="800px"
      @close="resetForm"
    >
      <el-form :model="templateForm" :rules="formRules" ref="formRef" label-width="140px">
        <el-form-item label="厂商" prop="vendor">
          <el-input v-model="templateForm.vendor" placeholder="例如: alcatel, dell, cisco, huawei" />
        </el-form-item>

        <el-form-item label="型号模式" prop="model_pattern">
          <el-input v-model="templateForm.model_pattern" placeholder="例如: 7220, os10, s5700 (支持通配符 *)" />
        </el-form-item>

        <el-form-item label="名称模式">
          <el-input v-model="templateForm.name_pattern" placeholder="可选：匹配交换机名称" />
        </el-form-item>

        <el-form-item label="NetMiko设备类型" prop="device_type">
          <el-select v-model="templateForm.device_type" placeholder="选择设备类型" style="width: 100%">
            <el-option label="Nokia SR Linux (nokia_srl)" value="nokia_srl" />
            <el-option label="Dell OS10 (dell_os10)" value="dell_os10" />
            <el-option label="Cisco IOS (cisco_ios)" value="cisco_ios" />
            <el-option label="Cisco NX-OS (cisco_nxos)" value="cisco_nxos" />
            <el-option label="Huawei (huawei)" value="huawei" />
            <el-option label="HP ProCurve (hp_procurve)" value="hp_procurve" />
            <el-option label="Arista EOS (arista_eos)" value="arista_eos" />
            <el-option label="Juniper JunOS (juniper_junos)" value="juniper_junos" />
          </el-select>
        </el-form-item>

        <el-divider content-position="left">ARP 配置</el-divider>

        <el-form-item label="启用ARP收集">
          <el-switch v-model="templateForm.arp_enabled" />
        </el-form-item>

        <el-form-item label="ARP命令" v-if="templateForm.arp_enabled">
          <el-input v-model="templateForm.arp_command" placeholder="例如: show arpnd arp-entries" />
        </el-form-item>

        <el-form-item label="ARP解析器类型" v-if="templateForm.arp_enabled">
          <el-select v-model="templateForm.arp_parser_type" placeholder="选择解析器" style="width: 100%">
            <el-option
              v-for="parser in availableParsers.arp"
              :key="parser.type"
              :label="parser.name"
              :value="parser.type"
            >
              <span>{{ parser.name }}</span>
              <span style="float: right; color: #8492a6; font-size: 13px">{{ parser.type }}</span>
            </el-option>
          </el-select>
        </el-form-item>

        <el-divider content-position="left">MAC 配置</el-divider>

        <el-form-item label="启用MAC收集">
          <el-switch v-model="templateForm.mac_enabled" />
        </el-form-item>

        <el-form-item label="MAC命令" v-if="templateForm.mac_enabled">
          <el-input v-model="templateForm.mac_command" placeholder="例如: show mac-address-table" />
        </el-form-item>

        <el-form-item label="MAC解析器类型" v-if="templateForm.mac_enabled">
          <el-select v-model="templateForm.mac_parser_type" placeholder="选择解析器" style="width: 100%">
            <el-option
              v-for="parser in availableParsers.mac"
              :key="parser.type"
              :label="parser.name"
              :value="parser.type"
            >
              <span>{{ parser.name }}</span>
              <span style="float: right; color: #8492a6; font-size: 13px">{{ parser.type }}</span>
            </el-option>
          </el-select>
        </el-form-item>

        <el-divider />

        <el-form-item label="优先级" prop="priority">
          <el-input-number v-model="templateForm.priority" :min="1" :max="1000" />
          <el-text size="small" type="info" style="margin-left: 10px">数字越大优先级越高</el-text>
        </el-form-item>

        <el-form-item label="描述">
          <el-input v-model="templateForm.description" type="textarea" :rows="2" />
        </el-form-item>

        <el-form-item label="启用">
          <el-switch v-model="templateForm.enabled" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="showAddDialog = false">取消</el-button>
        <el-button type="primary" @click="saveTemplate" :loading="saving">
          {{ editingTemplate ? '保存' : '创建' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- Test Dialog -->
    <el-dialog
      v-model="showTestDialogVisible"
      title="测试命令模板"
      width="600px"
    >
      <el-form :model="testForm" label-width="120px">
        <el-form-item label="交换机IP">
          <el-input v-model="testForm.switch_ip" placeholder="例如: 10.56.4.1" />
        </el-form-item>

        <el-form-item label="用户名">
          <el-input v-model="testForm.switch_username" placeholder="SSH用户名" />
        </el-form-item>

        <el-form-item label="密码">
          <el-input v-model="testForm.switch_password" type="password" show-password placeholder="SSH密码" />
        </el-form-item>

        <el-form-item label="测试类型">
          <el-radio-group v-model="testForm.test_type">
            <el-radio label="arp" :disabled="!currentTestTemplate?.arp_enabled">ARP收集</el-radio>
            <el-radio label="mac" :disabled="!currentTestTemplate?.mac_enabled">MAC收集</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-alert
          v-if="testResult"
          :title="testResult.message"
          :type="testResult.success ? 'success' : 'error'"
          :description="testResult.success ? `收集到 ${testResult.entries_count} 条记录` : testResult.error"
          style="margin-bottom: 20px"
          show-icon
        />

        <el-form-item v-if="testResult?.success && testResult.sample_output" label="示例输出">
          <el-input
            v-model="testResult.sample_output"
            type="textarea"
            :rows="5"
            readonly
          />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="showTestDialogVisible = false">关闭</el-button>
        <el-button type="primary" @click="runTest" :loading="testing">
          开始测试
        </el-button>
      </template>
    </el-dialog>

    <!-- Details Dialog -->
    <el-dialog
      v-model="showDetailsDialog"
      title="模板详情"
      width="700px"
    >
      <el-descriptions v-if="currentTemplate" :column="2" border>
        <el-descriptions-item label="ID">{{ currentTemplate.id }}</el-descriptions-item>
        <el-descriptions-item label="厂商">{{ currentTemplate.vendor }}</el-descriptions-item>
        <el-descriptions-item label="型号模式">{{ currentTemplate.model_pattern }}</el-descriptions-item>
        <el-descriptions-item label="名称模式">{{ currentTemplate.name_pattern || '-' }}</el-descriptions-item>
        <el-descriptions-item label="设备类型">{{ currentTemplate.device_type }}</el-descriptions-item>
        <el-descriptions-item label="优先级">{{ currentTemplate.priority }}</el-descriptions-item>

        <el-descriptions-item label="ARP启用">
          <el-tag :type="currentTemplate.arp_enabled ? 'success' : 'info'" size="small">
            {{ currentTemplate.arp_enabled ? '是' : '否' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="ARP命令" :span="2">
          <el-text>{{ currentTemplate.arp_command || '-' }}</el-text>
        </el-descriptions-item>
        <el-descriptions-item label="ARP解析器">{{ currentTemplate.arp_parser_type || '-' }}</el-descriptions-item>

        <el-descriptions-item label="MAC启用">
          <el-tag :type="currentTemplate.mac_enabled ? 'success' : 'info'" size="small">
            {{ currentTemplate.mac_enabled ? '是' : '否' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="MAC命令" :span="2">
          <el-text>{{ currentTemplate.mac_command || '-' }}</el-text>
        </el-descriptions-item>
        <el-descriptions-item label="MAC解析器">{{ currentTemplate.mac_parser_type || '-' }}</el-descriptions-item>

        <el-descriptions-item label="描述" :span="2">{{ currentTemplate.description || '-' }}</el-descriptions-item>
        <el-descriptions-item label="内置模板">
          <el-tag :type="currentTemplate.is_builtin ? 'warning' : ''" size="small">
            {{ currentTemplate.is_builtin ? '是' : '否' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="启用状态">
          <el-tag :type="currentTemplate.enabled ? 'success' : 'info'" size="small">
            {{ currentTemplate.enabled ? '启用' : '禁用' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="创建时间" :span="2">{{ formatDate(currentTemplate.created_at) }}</el-descriptions-item>
      </el-descriptions>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh, Edit, Delete, View, Connection } from '@element-plus/icons-vue'
import type { CommandTemplate, TestConnectionRequest, TestConnectionResponse, AvailableParsers } from '@/api/commandTemplates'
import {
  getCommandTemplates,
  createCommandTemplate,
  updateCommandTemplate,
  deleteCommandTemplate as deleteTemplateApi,
  testCommandTemplate,
  getAvailableParsers
} from '@/api/commandTemplates'

const templates = ref<CommandTemplate[]>([])
const availableParsers = ref<AvailableParsers>({ arp: [], mac: [] })
const loading = ref(false)
const saving = ref(false)
const testing = ref(false)

const showAddDialog = ref(false)
const showDetailsDialog = ref(false)
const showTestDialogVisible = ref(false)

const currentTemplate = ref<CommandTemplate | null>(null)
const currentTestTemplate = ref<CommandTemplate | null>(null)
const editingTemplate = ref<CommandTemplate | null>(null)

const formRef = ref()
const templateForm = ref<CommandTemplate>({
  vendor: '',
  model_pattern: '',
  name_pattern: '',
  device_type: '',
  arp_command: '',
  arp_parser_type: '',
  arp_enabled: true,
  mac_command: '',
  mac_parser_type: '',
  mac_enabled: true,
  priority: 150,
  description: '',
  enabled: true
})

const testForm = ref({
  switch_ip: '',
  switch_username: '',
  switch_password: '',
  template_id: 0,
  test_type: 'arp' as 'arp' | 'mac'
})

const testResult = ref<TestConnectionResponse | null>(null)

const formRules = {
  vendor: [{ required: true, message: '请输入厂商名称', trigger: 'blur' }],
  model_pattern: [{ required: true, message: '请输入型号模式', trigger: 'blur' }],
  device_type: [{ required: true, message: '请选择设备类型', trigger: 'change' }],
  priority: [{ required: true, message: '请输入优先级', trigger: 'blur' }]
}

onMounted(() => {
  loadTemplates()
  loadParsers()
})

const loadParsers = async () => {
  try {
    const response = await getAvailableParsers()
    availableParsers.value = response.data
  } catch (error: any) {
    ElMessage.error('加载解析器列表失败: ' + error.message)
  }
}

const loadTemplates = async () => {
  loading.value = true
  try {
    const response = await getCommandTemplates()
    templates.value = response.data
  } catch (error: any) {
    ElMessage.error('加载模板失败: ' + error.message)
  } finally {
    loading.value = false
  }
}

const showTemplateDetails = (template: CommandTemplate) => {
  currentTemplate.value = template
  showDetailsDialog.value = true
}

const showEditDialog = (template: CommandTemplate) => {
  editingTemplate.value = template
  templateForm.value = { ...template }
  showAddDialog.value = true
}

const showTestDialog = (template: CommandTemplate) => {
  currentTestTemplate.value = template
  testForm.value.template_id = template.id!
  testForm.value.test_type = template.arp_enabled ? 'arp' : 'mac'
  testResult.value = null
  showTestDialogVisible.value = true
}

const resetForm = () => {
  editingTemplate.value = null
  templateForm.value = {
    vendor: '',
    model_pattern: '',
    name_pattern: '',
    device_type: '',
    arp_command: '',
    arp_parser_type: '',
    arp_enabled: true,
    mac_command: '',
    mac_parser_type: '',
    mac_enabled: true,
    priority: 150,
    description: '',
    enabled: true
  }
  formRef.value?.resetFields()
}

const saveTemplate = async () => {
  await formRef.value?.validate()
  saving.value = true

  try {
    if (editingTemplate.value) {
      await updateCommandTemplate(editingTemplate.value.id!, templateForm.value)
      ElMessage.success('模板更新成功')
    } else {
      await createCommandTemplate(templateForm.value)
      ElMessage.success('模板创建成功')
    }
    showAddDialog.value = false
    loadTemplates()
  } catch (error: any) {
    ElMessage.error('保存失败: ' + error.message)
  } finally {
    saving.value = false
  }
}

const toggleEnabled = async (template: CommandTemplate) => {
  try {
    await updateCommandTemplate(template.id!, { enabled: template.enabled })
    ElMessage.success(template.enabled ? '已启用' : '已禁用')
  } catch (error: any) {
    template.enabled = !template.enabled // Revert on error
    ElMessage.error('更新失败: ' + error.message)
  }
}

const deleteTemplate = async (template: CommandTemplate) => {
  try {
    await ElMessageBox.confirm(
      `确定要删除模板 "${template.vendor} - ${template.model_pattern}" 吗？`,
      '确认删除',
      {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )

    await deleteTemplateApi(template.id!)
    ElMessage.success('删除成功')
    loadTemplates()
  } catch (error: any) {
    if (error !== 'cancel') {
      ElMessage.error('删除失败: ' + error.message)
    }
  }
}

const runTest = async () => {
  if (!testForm.value.switch_ip || !testForm.value.switch_username || !testForm.value.switch_password) {
    ElMessage.warning('请填写所有必填项')
    return
  }

  testing.value = true
  testResult.value = null

  try {
    const response = await testCommandTemplate(testForm.value as TestConnectionRequest)
    testResult.value = response.data

    if (response.data.success) {
      ElMessage.success('测试成功')
    } else {
      ElMessage.error('测试失败: ' + response.data.error)
    }
  } catch (error: any) {
    ElMessage.error('测试失败: ' + error.message)
    testResult.value = {
      success: false,
      message: '测试连接失败',
      entries_count: 0,
      sample_output: '',
      error: error.message
    }
  } finally {
    testing.value = false
  }
}

const getVendorTagType = (vendor: string) => {
  const types: Record<string, any> = {
    alcatel: 'warning',
    nokia: 'warning',
    dell: 'success',
    cisco: 'primary',
    huawei: 'danger'
  }
  return types[vendor.toLowerCase()] || 'info'
}

const getPriorityTagType = (priority: number) => {
  if (priority >= 200) return 'danger'
  if (priority >= 150) return 'warning'
  return 'info'
}

const formatDate = (dateStr?: string) => {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleString('zh-CN')
}
</script>

<style scoped>
.command-templates-view {
  padding: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}

.card-header h2 {
  margin: 0 0 5px 0;
  color: #303133;
}

.card-header p {
  margin: 0;
  color: #909399;
  font-size: 14px;
}

.form-tip {
  font-size: 12px;
  color: #909399;
  margin-top: 5px;
}
</style>
