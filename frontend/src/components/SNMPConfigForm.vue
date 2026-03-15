<template>
  <div class="snmp-config-form">
    <el-form
      ref="formRef"
      :model="formData"
      :rules="rules"
      label-width="160px"
      label-position="left"
    >
      <!-- SNMP 启用开关 -->
      <el-form-item label="启用 SNMP">
        <el-switch
          v-model="formData.snmp_enabled"
          active-text="启用"
          inactive-text="禁用"
        />
      </el-form-item>

      <template v-if="formData.snmp_enabled">
        <!-- SNMP 版本选择 -->
        <el-form-item label="SNMP 版本" prop="snmp_version">
          <el-radio-group v-model="formData.snmp_version">
            <el-radio label="3">SNMPv3 (推荐)</el-radio>
            <el-radio label="2c">SNMPv2c</el-radio>
          </el-radio-group>
          <div class="form-tip">
            <el-icon><InfoFilled /></el-icon>
            SNMPv3 提供更好的安全性（加密和认证）
          </div>
        </el-form-item>

        <!-- SNMPv3 配置 -->
        <template v-if="formData.snmp_version === '3'">
          <el-divider content-position="left">SNMPv3 认证配置</el-divider>

          <el-form-item label="用户名" prop="snmp_username">
            <el-input
              v-model="formData.snmp_username"
              placeholder="请输入 SNMP 用户名"
              clearable
            />
          </el-form-item>

          <el-form-item label="认证协议" prop="snmp_auth_protocol">
            <el-select v-model="formData.snmp_auth_protocol" placeholder="选择认证协议">
              <el-option label="SHA (推荐)" value="SHA" />
              <el-option label="SHA256" value="SHA256" />
              <el-option label="MD5" value="MD5" />
              <el-option label="SHA384" value="SHA384" />
              <el-option label="SHA512" value="SHA512" />
            </el-select>
          </el-form-item>

          <el-form-item label="认证密码" prop="snmp_auth_password">
            <el-input
              v-model="formData.snmp_auth_password"
              type="password"
              placeholder="至少 8 位字符"
              show-password
              clearable
            />
          </el-form-item>

          <el-divider content-position="left">SNMPv3 加密配置</el-divider>

          <el-form-item label="加密协议" prop="snmp_priv_protocol">
            <el-select v-model="formData.snmp_priv_protocol" placeholder="选择加密协议">
              <el-option label="AES128 (推荐)" value="AES128" />
              <el-option label="AES192" value="AES192" />
              <el-option label="AES256" value="AES256" />
              <el-option label="AES" value="AES" />
              <el-option label="DES" value="DES" />
            </el-select>
          </el-form-item>

          <el-form-item label="加密密码" prop="snmp_priv_password">
            <el-input
              v-model="formData.snmp_priv_password"
              type="password"
              placeholder="至少 8 位字符"
              show-password
              clearable
            />
          </el-form-item>
        </template>

        <!-- SNMPv2c 配置 -->
        <template v-if="formData.snmp_version === '2c'">
          <el-divider content-position="left">SNMPv2c 配置</el-divider>

          <el-form-item label="Community 字符串" prop="snmp_community">
            <el-input
              v-model="formData.snmp_community"
              placeholder="请输入 Community 字符串（如: public）"
              clearable
            />
            <div class="form-tip warning">
              <el-icon><WarningFilled /></el-icon>
              SNMPv2c 不加密，建议仅在内网使用
            </div>
          </el-form-item>
        </template>

        <!-- SNMP 端口 -->
        <el-form-item label="SNMP 端口" prop="snmp_port">
          <el-input-number
            v-model="formData.snmp_port"
            :min="1"
            :max="65535"
            :step="1"
          />
          <span class="form-tip">默认: 161</span>
        </el-form-item>
      </template>

      <!-- 操作按钮 -->
      <el-form-item>
        <el-space>
          <el-button
            type="primary"
            :loading="testing"
            :disabled="!formData.snmp_enabled"
            @click="handleTest"
          >
            <el-icon><Connection /></el-icon>
            测试连接
          </el-button>
          <el-button
            type="success"
            :loading="saving"
            @click="handleSave"
          >
            <el-icon><Check /></el-icon>
            保存配置
          </el-button>
          <el-button @click="handleCancel">
            <el-icon><Close /></el-icon>
            取消
          </el-button>
        </el-space>
      </el-form-item>
    </el-form>

    <!-- 测试结果对话框 -->
    <el-dialog
      v-model="testResultVisible"
      title="SNMP 连接测试结果"
      width="600px"
    >
      <el-result
        :icon="testResult.success ? 'success' : 'error'"
        :title="testResult.success ? '连接成功' : '连接失败'"
        :sub-title="testResult.message"
      >
        <template #extra>
          <div v-if="testResult.success && testResult.system_description" class="test-details">
            <el-descriptions title="设备信息" :column="1" border>
              <el-descriptions-item label="目标 IP">
                {{ testResult.target_ip }}
              </el-descriptions-item>
              <el-descriptions-item label="SNMP 版本">
                {{ testResult.snmp_version }}
              </el-descriptions-item>
              <el-descriptions-item label="系统描述">
                {{ testResult.system_description }}
              </el-descriptions-item>
            </el-descriptions>
          </div>
          <div v-else-if="!testResult.success" class="test-error">
            <el-alert
              :title="testResult.error_type || '连接错误'"
              type="error"
              :description="testResult.message"
              show-icon
              :closable="false"
            />
          </div>
        </template>
      </el-result>
      <template #footer>
        <el-button type="primary" @click="testResultVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, watch } from 'vue';
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus';
import { InfoFilled, WarningFilled, Connection, Check, Close } from '@element-plus/icons-vue';
import type { SNMPConfig, SNMPTestResponse } from '@/api/snmp';

interface Props {
  switchId?: number;
  switchIp?: string;
  initialConfig?: Partial<SNMPConfig>;
}

const props = defineProps<Props>();
const emit = defineEmits<{
  save: [config: SNMPConfig];
  cancel: [];
}>();

// 表单引用
const formRef = ref<FormInstance>();

// 表单数据
const formData = reactive<SNMPConfig>({
  snmp_enabled: true,
  snmp_version: '3',
  snmp_username: '',
  snmp_auth_protocol: 'SHA',
  snmp_auth_password: '',
  snmp_priv_protocol: 'AES128',
  snmp_priv_password: '',
  snmp_port: 161,
  snmp_community: '',
  ...props.initialConfig
});

// 表单验证规则
const rules = reactive<FormRules>({
  snmp_version: [
    { required: true, message: '请选择 SNMP 版本', trigger: 'change' }
  ],
  snmp_username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 1, max: 100, message: '用户名长度在 1 到 100 个字符', trigger: 'blur' }
  ],
  snmp_auth_password: [
    { required: true, message: '请输入认证密码', trigger: 'blur' },
    { min: 8, message: '认证密码至少 8 位字符', trigger: 'blur' }
  ],
  snmp_priv_password: [
    { required: true, message: '请输入加密密码', trigger: 'blur' },
    { min: 8, message: '加密密码至少 8 位字符', trigger: 'blur' }
  ],
  snmp_community: [
    { required: true, message: '请输入 Community 字符串', trigger: 'blur' }
  ]
});

// 状态
const testing = ref(false);
const saving = ref(false);
const testResultVisible = ref(false);
const testResult = ref<SNMPTestResponse>({
  success: false,
  message: ''
});

// 监听 SNMP 版本变化，清空不相关字段
watch(() => formData.snmp_version, (newVersion) => {
  if (newVersion === '3') {
    formData.snmp_community = '';
  } else if (newVersion === '2c') {
    formData.snmp_username = '';
    formData.snmp_auth_password = '';
    formData.snmp_priv_password = '';
  }
});

// 测试连接
const handleTest = async () => {
  if (!props.switchIp) {
    ElMessage.warning('缺少交换机 IP 地址');
    return;
  }

  // 验证表单
  if (!formRef.value) return;

  try {
    await formRef.value.validate();
  } catch {
    ElMessage.warning('请填写完整的 SNMP 配置');
    return;
  }

  testing.value = true;

  try {
    const { testSNMPConnection } = await import('@/api/snmp');

    const testConfig = {
      target_ip: props.switchIp,
      snmp_version: formData.snmp_version,
      snmp_port: formData.snmp_port || 161,
      ...(formData.snmp_version === '3' ? {
        snmp_username: formData.snmp_username,
        snmp_auth_protocol: formData.snmp_auth_protocol,
        snmp_auth_password: formData.snmp_auth_password,
        snmp_priv_protocol: formData.snmp_priv_protocol,
        snmp_priv_password: formData.snmp_priv_password
      } : {
        snmp_community: formData.snmp_community
      })
    };

    testResult.value = await testSNMPConnection(testConfig);
    testResultVisible.value = true;

    if (testResult.value.success) {
      ElMessage.success('SNMP 连接测试成功！');
    } else {
      ElMessage.error('SNMP 连接测试失败');
    }
  } catch (error: any) {
    ElMessage.error(`测试失败: ${error.message || '未知错误'}`);
    testResult.value = {
      success: false,
      message: error.message || '连接测试失败',
      error_type: 'exception'
    };
    testResultVisible.value = true;
  } finally {
    testing.value = false;
  }
};

// 保存配置
const handleSave = async () => {
  if (!formRef.value) return;

  try {
    await formRef.value.validate();

    saving.value = true;
    emit('save', { ...formData });
  } catch {
    ElMessage.warning('请填写完整的表单信息');
  } finally {
    saving.value = false;
  }
};

// 取消
const handleCancel = () => {
  emit('cancel');
};

// 暴露方法给父组件
defineExpose({
  validate: () => formRef.value?.validate(),
  resetFields: () => formRef.value?.resetFields()
});
</script>

<style scoped >
.snmp-config-form {
  padding: 20px;

  .form-tip {
    margin-top: 8px;
    font-size: 12px;
    color: #909399;
    display: flex;
    align-items: center;
    gap: 4px;

    &.warning {
      color: #e6a23c;
    }
  }

  .test-details {
    margin-top: 20px;
  }

  .test-error {
    margin-top: 20px;
  }

  :deep(.el-divider__text) {
    font-weight: 600;
    color: #409eff;
  }
}
</style>
