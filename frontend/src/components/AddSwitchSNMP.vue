<template>
  <el-dialog
    v-model="dialogVisible"
    title="添加交换机 (SNMP认证)"
    width="600px"
    @close="handleClose"
  >
    <el-form :model="form" :rules="rules" ref="formRef" label-width="140px">
      <el-divider content-position="left">基本信息</el-divider>
      
      <el-form-item label="交换机名称" prop="name">
        <el-input v-model="form.name" placeholder="例如: Core-SW-01" />
      </el-form-item>
      
      <el-form-item label="IP地址" prop="ip_address">
        <el-input v-model="form.ip_address" placeholder="例如: 10.71.192.1" />
      </el-form-item>
      
      <el-form-item label="厂商" prop="vendor">
        <el-select v-model="form.vendor" placeholder="选择厂商">
          <el-option label="Cisco" value="cisco" />
          <el-option label="Dell" value="dell" />
          <el-option label="Alcatel" value="alcatel" />
        </el-select>
      </el-form-item>
      
      <el-form-item label="型号" prop="model">
        <el-input v-model="form.model" placeholder="例如: S4048-ON" />
      </el-form-item>
      
      <el-form-item label="角色" prop="role">
        <el-select v-model="form.role">
          <el-option label="Access" value="access" />
          <el-option label="Aggregation" value="aggregation" />
          <el-option label="Core" value="core" />
        </el-select>
      </el-form-item>
      
      <el-form-item label="优先级" prop="priority">
        <el-input-number v-model="form.priority" :min="1" :max="100" />
        <span class="help-text">1=最高优先级, 100=最低优先级</span>
      </el-form-item>
      
      <el-divider content-position="left">SNMPv3 认证</el-divider>
      
      <el-form-item label="SNMP端口" prop="snmp_port">
        <el-input-number v-model="form.snmp_port" :min="1" :max="65535" />
      </el-form-item>
      
      <el-form-item label="SNMP用户名" prop="snmp_username">
        <el-input v-model="form.snmp_username" placeholder="SNMPv3用户名" />
      </el-form-item>
      
      <el-form-item label="认证协议" prop="snmp_auth_protocol">
        <el-select v-model="form.snmp_auth_protocol">
          <el-option label="SHA" value="SHA" />
          <el-option label="MD5" value="MD5" />
          <el-option label="SHA256" value="SHA256" />
        </el-select>
      </el-form-item>
      
      <el-form-item label="认证密码" prop="snmp_auth_password">
        <el-input
          v-model="form.snmp_auth_password"
          type="password"
          placeholder="至少8个字符"
          show-password
        />
      </el-form-item>
      
      <el-form-item label="加密协议" prop="snmp_priv_protocol">
        <el-select v-model="form.snmp_priv_protocol">
          <el-option label="AES128" value="AES128" />
          <el-option label="AES192" value="AES192" />
          <el-option label="AES256" value="AES256" />
          <el-option label="DES" value="DES" />
        </el-select>
      </el-form-item>
      
      <el-form-item label="加密密码" prop="snmp_priv_password">
        <el-input
          v-model="form.snmp_priv_password"
          type="password"
          placeholder="至少8个字符"
          show-password
        />
      </el-form-item>
      
      <el-form-item label="启用" prop="enabled">
        <el-switch v-model="form.enabled" />
      </el-form-item>
    </el-form>
    
    <template #footer>
      <span class="dialog-footer">
        <el-button @click="handleClose">取消</el-button>
        <el-button type="primary" @click="handleTest" :loading="testing">
          测试连接
        </el-button>
        <el-button type="success" @click="handleSubmit" :loading="submitting">
          添加交换机
        </el-button>
      </span>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { testSNMPConnection } from '@/api/snmp'

const dialogVisible = ref(false)
const formRef = ref<FormInstance>()
const submitting = ref(false)
const testing = ref(false)

const form = reactive({
  name: '',
  ip_address: '',
  vendor: 'cisco',
  model: '',
  role: 'access',
  priority: 50,
  enabled: true,
  snmp_enabled: true,
  snmp_version: '3',
  snmp_port: 161,
  snmp_username: '',
  snmp_auth_protocol: 'SHA',
  snmp_auth_password: '',
  snmp_priv_protocol: 'AES128',
  snmp_priv_password: ''
})

const rules = reactive<FormRules>({
  name: [
    { required: true, message: '请输入交换机名称', trigger: 'blur' }
  ],
  ip_address: [
    { required: true, message: '请输入IP地址', trigger: 'blur' },
    { pattern: /^(\d{1,3}\.){3}\d{1,3}$/, message: '请输入有效的IP地址', trigger: 'blur' }
  ],
  vendor: [
    { required: true, message: '请选择厂商', trigger: 'change' }
  ],
  snmp_username: [
    { required: true, message: '请输入SNMP用户名', trigger: 'blur' }
  ],
  snmp_auth_password: [
    { required: true, message: '请输入认证密码', trigger: 'blur' },
    { min: 8, message: '密码至少8个字符', trigger: 'blur' }
  ],
  snmp_priv_password: [
    { required: true, message: '请输入加密密码', trigger: 'blur' },
    { min: 8, message: '密码至少8个字符', trigger: 'blur' }
  ]
})

const emit = defineEmits(['success'])

const show = () => {
  dialogVisible.value = true
}

const handleClose = () => {
  formRef.value?.resetFields()
  dialogVisible.value = false
}

const handleTest = async () => {
  if (!formRef.value) return
  
  try {
    await formRef.value.validate()
    testing.value = true
    
    const result = await testSNMPConnection({
      target_ip: form.ip_address,
      snmp_version: form.snmp_version,
      snmp_username: form.snmp_username,
      snmp_auth_protocol: form.snmp_auth_protocol,
      snmp_auth_password: form.snmp_auth_password,
      snmp_priv_protocol: form.snmp_priv_protocol,
      snmp_priv_password: form.snmp_priv_password,
      snmp_port: form.snmp_port
    })
    
    if (result.success) {
      ElMessage.success('SNMP连接成功！')
    } else {
      ElMessage.error(`连接失败: ${result.message}`)
    }
  } catch (error: any) {
    console.error('测试失败:', error)
    ElMessage.error(error.message || '测试失败')
  } finally {
    testing.value = false
  }
}

const handleSubmit = async () => {
  if (!formRef.value) return
  
  try {
    await formRef.value.validate()
    submitting.value = true
    
    const response = await fetch('http://localhost:8100/api/v1/switches', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(form)
    })
    
    if (!response.ok) {
      const error = await response.json()
      throw new Error(error.detail || '添加失败')
    }
    
    ElMessage.success('交换机添加成功！')
    emit('success')
    handleClose()
  } catch (error: any) {
    console.error('添加失败:', error)
    ElMessage.error(error.message || '添加失败')
  } finally {
    submitting.value = false
  }
}

defineExpose({ show })
</script>

<style scoped>
.help-text {
  margin-left: 10px;
  color: #909399;
  font-size: 12px;
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
</style>
