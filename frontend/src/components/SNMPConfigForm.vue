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
        <!-- 凭据来源：选已保存的模板，或让这台设备用自己的一份凭据 -->
        <el-form-item label="凭据来源" prop="snmp_profile_id">
          <!--
            placeholder 和「本机自带」那个选项文案必须一致：Element Plus 在
            modelValue 为 null 时判定为「没有值」，会渲染 placeholder 而不是选中项，
            两处写法一样，看上去才始终是同一个状态。
          -->
          <el-select
            v-model="formData.snmp_profile_id"
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
          <div class="form-tip">
            <el-icon><InfoFilled /></el-icon>
            选中模板后，下面这些逐台填写的用户名/协议/口令都不再生效，凭据整体以模板为准；
            以后改口令只改模板一处，所有引用它的交换机同时生效。
          </div>
        </el-form-item>

        <el-alert
          v-if="formData.snmp_profile_id"
          type="info"
          :closable="false"
          show-icon
          style="margin-bottom: 18px;"
        >
          <template #title>
            凭据取自模板「{{ snmpProfileStore.byId(formData.snmp_profile_id)?.name }}」。
            选回「本机自带（不引用模板）」保存即可解绑。
          </template>
        </el-alert>

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

        <!--
          引用模板时把逐台凭据整段隐藏：后端在 snmp_profile_id 非空时本来就忽略
          这些字段，摆在这里只会让人以为「这里填的还算数」，改了没反应更难排查。
        -->
        <template v-if="!formData.snmp_profile_id">
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
              <el-option label="MD5" value="MD5" />
              <el-option label="SHA-224" value="SHA-224" />
              <el-option label="SHA-256" value="SHA-256" />
              <el-option label="SHA-384" value="SHA-384" />
              <el-option label="SHA-512" value="SHA-512" />
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
              <el-option label="AES-128 (推荐)" value="AES-128" />
              <el-option label="AES-192" value="AES-192" />
              <el-option label="AES-256" value="AES-256" />
              <el-option label="AES" value="AES" />
              <el-option label="DES" value="DES" />
            </el-select>
            <div class="form-tip">
              <el-icon><InfoFilled /></el-icon>
              不填写加密密码时，将使用仅认证不加密的 SNMPv3 模式
            </div>
          </el-form-item>

          <el-form-item label="加密密码（可选）" prop="snmp_priv_password">
            <el-input
              v-model="formData.snmp_priv_password"
              type="password"
              placeholder="留空则不启用加密"
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
          <div v-if="testResult.success" class="test-details">
            <el-descriptions title="设备信息" :column="1" border>
              <el-descriptions-item label="目标 IP">
                {{ testResult.target_ip }}
              </el-descriptions-item>
              <el-descriptions-item label="SNMP 版本">
                {{ testResult.snmp_version }}
              </el-descriptions-item>
              <!--
                凭据来源必须显示：改了模板口令但测试结果没变时，先看这一行是
                「本机自带」还是「模板 xxx」，就能分清是没挂上模板还是模板本身的问题。
              -->
              <el-descriptions-item label="凭据来源">
                {{ testResult.credential_source || '—' }}
              </el-descriptions-item>
              <el-descriptions-item v-if="testResult.system_description" label="系统描述">
                {{ testResult.system_description }}
              </el-descriptions-item>
            </el-descriptions>
          </div>
          <div v-else class="test-error">
            <el-alert
              :title="testResult.error_type || '连接错误'"
              type="error"
              :description="testResult.message"
              show-icon
              :closable="false"
            />
            <!-- 原始报错单独摆一行：WrongDigest / Unknown USM user 这类字眼
                 是分辨「口令错」还是「协议不匹配」的唯一线索 -->
            <div v-if="testResult.raw_error" class="raw-error">
              {{ testResult.raw_error }}
            </div>
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
import { ref, reactive, watch, onMounted } from 'vue';
import { ElMessage, type FormInstance, type FormRules } from 'element-plus';
import { InfoFilled, WarningFilled, Connection, Check, Close } from '@element-plus/icons-vue';
import {
  testSNMPConnection,
  testSavedSNMPConfig,
  type SNMPConfig,
  type SNMPTestResponse,
} from '@/api/snmp';
// 凭据模板列表：新增/编辑/批量配置共用同一份缓存，避免同一个页面里重复请求。
import { useSNMPProfilesStore } from '@/stores/snmpProfiles';

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

const snmpProfileStore = useSNMPProfilesStore();

// 表单引用
const formRef = ref<FormInstance>();

/**
 * 协议名的历史写法 -> 下拉框统一使用的写法。
 *
 * switches 表存的是 'SHA256' / 'AES128'，snmp_profiles 表存的是 'SHA-256' / 'AES-192'。
 * 下拉框只保留带连字符的那一套选项，回填时先把老写法换算过来；否则值虽然是对的，
 * 却匹配不上任何选项，框里会直接显示原始字符串，看着像没选中。
 */
const PROTOCOL_ALIASES: Record<string, string> = {
  SHA1: 'SHA',
  SHA224: 'SHA-224',
  SHA256: 'SHA-256',
  SHA384: 'SHA-384',
  SHA512: 'SHA-512',
  AES128: 'AES-128',
  AES192: 'AES-192',
  AES256: 'AES-256',
};

/** 把库里取出的协议名换算成下拉框的写法；空值原样返回，交给调用方决定默认值 */
const normalizeProtocolForDisplay = (value?: string | null): string | undefined => {
  if (!value) return undefined;
  return PROTOCOL_ALIASES[value.trim().toUpperCase()] || value;
};

// 表单数据
const formData = reactive<SNMPConfig>({
  snmp_enabled: true,
  snmp_version: '3',
  snmp_username: '',
  snmp_auth_password: '',
  snmp_priv_password: '',
  snmp_port: 161,
  snmp_community: '',
  ...props.initialConfig,
  // 下面三项必须放在展开之后：要用归一化/兜底值覆盖掉 initialConfig 里的原始写法。
  // 也正因为要放在展开之后，这三项在上面就不能再各出现一次 —— 对象字面量里
  // 同名字段写两遍是 TS1117 编译错误，会让整个前端构建挂掉。
  snmp_auth_protocol: normalizeProtocolForDisplay(props.initialConfig?.snmp_auth_protocol) ?? 'SHA',
  snmp_priv_protocol: normalizeProtocolForDisplay(props.initialConfig?.snmp_priv_protocol) ?? 'AES-128',
  // null 表示本机自带凭据。父组件不传时也落到 null，保证提交时该字段一定在。
  snmp_profile_id: props.initialConfig?.snmp_profile_id ?? null,
});

// 表单验证规则
const rules = reactive<FormRules>({
  snmp_version: [
    { required: true, message: '请选择 SNMP 版本', trigger: 'change' }
  ],
  snmp_username: [
    {
      validator: (_rule: any, value: string, callback: (error?: Error) => void) => {
        // 引用了模板就用不着逐台填：这些输入框整段被隐藏，校验必须同步放行，
        // 否则用户看不到的必填项会拦住提交，还找不到是哪儿报的错。
        if (formData.snmp_profile_id) {
          callback()
          return
        }
        if (formData.snmp_enabled && formData.snmp_version === '3' && !value) {
          callback(new Error('请输入用户名'))
          return
        }
        callback()
      },
      trigger: 'blur'
    },
    { min: 1, max: 100, message: '用户名长度在 1 到 100 个字符', trigger: 'blur' }
  ],
  snmp_auth_password: [
    {
      validator: (_rule: any, value: string, callback: (error?: Error) => void) => {
        if (formData.snmp_profile_id) {
          callback()
          return
        }
        if (formData.snmp_enabled && formData.snmp_version === '3' && !value) {
          callback(new Error('请输入认证密码'))
          return
        }
        if (value && value.length < 8) {
          callback(new Error('认证密码至少 8 位字符'))
          return
        }
        callback()
      },
      trigger: 'blur'
    }
  ],
  snmp_priv_password: [
    {
      validator: (_rule: any, value: string, callback: (error?: Error) => void) => {
        if (formData.snmp_profile_id) {
          callback()
          return
        }
        if (value && value.length < 8) {
          callback(new Error('加密密码至少 8 位字符'))
          return
        }
        callback()
      },
      trigger: 'blur'
    }
  ],
  snmp_community: [
    {
      validator: (_rule: any, value: string, callback: (error?: Error) => void) => {
        if (formData.snmp_profile_id) {
          callback()
          return
        }
        if (formData.snmp_enabled && formData.snmp_version === '2c' && !value) {
          callback(new Error('请输入 Community 字符串'))
          return
        }
        callback()
      },
      trigger: 'blur'
    }
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

// 本组件是被对话框挂上去才创建的，onMounted 就相当于「对话框打开了」，
// 正好在这时候把模板列表备好。store 里有缓存，反复开关也只请求一次。
onMounted(() => {
  snmpProfileStore.load();
});

// 测试连接
const handleTest = async () => {
  // 验证表单
  if (!formRef.value) return;

  try {
    await formRef.value.validate();
  } catch {
    ElMessage.warning('请填写完整的 SNMP 配置');
    return;
  }

  // 引用模板时没法在这里测：浏览器手里没有模板的明文口令，而且批量配置下连
  // 目标交换机都还没定。这种只能让服务端拿库里存着的那份凭据去测。
  if (formData.snmp_profile_id) {
    if (!props.switchId) {
      ElMessage.warning('引用模板的凭据无法在批量配置里测试，请到该交换机的详情页单独测试');
      return;
    }

    testing.value = true;
    try {
      // 服务端按 switch_id 取凭据：和后台采集走的是同一条解析路径，
      // 这里测得通，采集就测得通，不会出现「页面能连上、采集连不上」。
      testResult.value = await testSavedSNMPConfig(props.switchId);
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
    return;
  }

  if (!props.switchIp) {
    ElMessage.warning('缺少交换机 IP 地址');
    return;
  }

  testing.value = true;

  try {
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

    .raw-error {
      margin-top: 10px;
      padding: 8px 12px;
      border-radius: 4px;
      background: #f5f7fa;
      font-family: monospace;
      font-size: 12px;
      color: #606266;
      word-break: break-all;
    }
  }

  :deep(.el-divider__text) {
    font-weight: 600;
    color: var(--primary-color);
  }
}
</style>
