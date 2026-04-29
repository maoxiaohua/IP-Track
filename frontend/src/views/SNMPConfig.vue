<template>
  <div class="snmp-config-page">
    <el-card class="header-card">
      <template #header>
        <div class="card-header">
          <span>
            <el-icon><Setting /></el-icon>
            SNMP 配置管理
          </span>
          <el-space>
            <el-button type="primary" @click="handleBatchConfig">
              <el-icon><Operation /></el-icon>
              批量配置
            </el-button>
            <el-button @click="loadSwitches">
              <el-icon><Refresh /></el-icon>
              刷新
            </el-button>
          </el-space>
        </div>
      </template>

      <el-alert
        title="SNMP 配置说明"
        type="info"
        :closable="false"
        show-icon
      >
        <p>在此页面配置交换机的 SNMP 凭据，系统会使用这些凭据做设备识别和轻量补充采集，例如硬件型号、系统信息以及部分 SNMP 可读属性。</p>
        <p>ARP/MAC 表已统一走交换机 CLI 采集（SSH/Telnet）；推荐使用 <strong>SNMPv3</strong>，同时兼容仅认证不加密的老设备场景。</p>
      </el-alert>
    </el-card>

    <!-- 交换机列表 -->
    <el-card class="table-card">
      <el-table
        v-loading="loading"
        :data="switches"
        stripe
        border
        style="width: 100%"
      >
        <el-table-column type="selection" width="55" />

        <el-table-column prop="name" label="交换机名称" min-width="150">
          <template #default="{ row }">
            <div class="switch-name">
              <el-tag :type="row.enabled ? 'success' : 'info'" size="small">
                {{ row.enabled ? '启用' : '禁用' }}
              </el-tag>
              <span>{{ row.name }}</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column prop="ip_address" label="IP 地址" width="140" />

        <el-table-column prop="vendor" label="厂商" width="100">
          <template #default="{ row }">
            <el-tag size="small">{{ row.vendor }}</el-tag>
          </template>
        </el-table-column>

        <el-table-column prop="role" label="角色" width="100">
          <template #default="{ row }">
            <el-tag
              :type="row.role === 'core' ? 'danger' : row.role === 'aggregation' ? 'warning' : ''"
              size="small"
            >
              {{ roleMap[row.role] || row.role }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="SNMP 状态" width="120">
          <template #default="{ row }">
            <el-tag
              :type="row.snmp_enabled ? 'success' : 'info'"
              size="small"
            >
              {{ row.snmp_enabled ? '已启用' : '未启用' }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="SNMP 版本" width="100">
          <template #default="{ row }">
            <span v-if="row.snmp_enabled">
              {{ row.snmp_version === '3' ? 'SNMPv3' : 'SNMPv2c' }}
            </span>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>

        <el-table-column label="凭据状态" width="100">
          <template #default="{ row }">
            <el-icon v-if="row.has_credentials" color="#67c23a" :size="18">
              <CircleCheckFilled />
            </el-icon>
            <el-icon v-else color="#909399" :size="18">
              <CircleCloseFilled />
            </el-icon>
          </template>
        </el-table-column>

        <el-table-column label="用户名" min-width="120">
          <template #default="{ row }">
            <span v-if="row.snmp_username">{{ row.snmp_username }}</span>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-space>
              <el-button
                type="primary"
                size="small"
                @click="handleEdit(row)"
              >
                配置
              </el-button>
              <el-button
                v-if="row.snmp_enabled"
                type="danger"
                size="small"
                @click="handleDelete(row)"
              >
                删除
              </el-button>
            </el-space>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[10, 20, 50, 100]"
          layout="total, sizes, prev, pager, next, jumper"
          @size-change="loadSwitches"
          @current-change="loadSwitches"
        />
      </div>
    </el-card>

    <!-- 配置对话框 -->
    <el-dialog
      v-model="configDialogVisible"
      :title="`配置 SNMP - ${currentSwitch?.name}`"
      width="700px"
      :close-on-click-modal="false"
    >
      <SNMPConfigForm
        v-if="currentSwitch"
        :switch-id="currentSwitch.id"
        :switch-ip="currentSwitch.ip_address"
        :initial-config="currentConfig"
        @save="handleSaveConfig"
        @cancel="configDialogVisible = false"
      />
    </el-dialog>

    <!-- 批量配置对话框 -->
    <el-dialog
      v-model="batchDialogVisible"
      title="批量配置 SNMP"
      width="700px"
      :close-on-click-modal="false"
    >
      <el-alert
        title="批量配置说明"
        type="warning"
        :closable="false"
        show-icon
        style="margin-bottom: 20px"
      >
        <p>批量配置将为所有选中的交换机应用相同的 SNMP 凭据。</p>
        <p>请确保这些交换机使用相同的 SNMP 配置。</p>
      </el-alert>

      <SNMPConfigForm
        :initial-config="batchConfig"
        @save="handleBatchSave"
        @cancel="batchDialogVisible = false"
      />
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import {
  Setting,
  Operation,
  Refresh,
  CircleCheckFilled,
  CircleCloseFilled
} from '@element-plus/icons-vue';
import SNMPConfigForm from '@/components/SNMPConfigForm.vue';
import {
  listSNMPConfiguredSwitches,
  getSNMPConfig,
  updateSNMPConfig,
  batchUpdateSNMPConfig,
  deleteSNMPConfig,
  type SwitchSNMPStatus,
  type SNMPConfig
} from '@/api/snmp';

// 角色映射
const roleMap: Record<string, string> = {
  core: '核心',
  aggregation: '汇聚',
  access: '接入'
};

// 数据
const switches = ref<SwitchSNMPStatus[]>([]);
const loading = ref(false);
const currentPage = ref(1);
const pageSize = ref(20);
const total = ref(0);

// 对话框
const configDialogVisible = ref(false);
const batchDialogVisible = ref(false);
const currentSwitch = ref<SwitchSNMPStatus | null>(null);
const currentConfig = ref<Partial<SNMPConfig>>({});
const batchConfig = ref<Partial<SNMPConfig>>({
  snmp_enabled: true,
  snmp_version: '3',
  snmp_auth_protocol: 'SHA',
  snmp_priv_protocol: 'AES128',
  snmp_port: 161
});

// 选中的交换机
const selectedSwitches = ref<SwitchSNMPStatus[]>([]);

// 加载交换机列表
const loadSwitches = async () => {
  loading.value = true;
  try {
    const response = await listSNMPConfiguredSwitches();
    switches.value = response.switches;
    total.value = response.total;
  } catch (error: any) {
    ElMessage.error(`加载失败: ${error.message || '未知错误'}`);
  } finally {
    loading.value = false;
  }
};

// 编辑配置
const handleEdit = async (switchItem: SwitchSNMPStatus) => {
  currentSwitch.value = switchItem;

  // 如果已有配置，加载现有配置
  if (switchItem.snmp_enabled) {
    try {
      const config = await getSNMPConfig(switchItem.id);
      currentConfig.value = {
        snmp_enabled: config.snmp_enabled,
        snmp_version: config.snmp_version as '2c' | '3',
        snmp_username: config.snmp_username,
        snmp_auth_protocol: config.snmp_auth_protocol as any,
        snmp_priv_protocol: config.snmp_priv_protocol as any,
        snmp_port: config.snmp_port
      };
    } catch (error: any) {
      ElMessage.error(`加载配置失败: ${error.message}`);
      return;
    }
  } else {
    // 新配置，使用默认值
    currentConfig.value = {
      snmp_enabled: true,
      snmp_version: '3',
      snmp_auth_protocol: 'SHA',
      snmp_priv_protocol: 'AES128',
      snmp_port: 161
    };
  }

  configDialogVisible.value = true;
};

// 保存配置
const handleSaveConfig = async (config: SNMPConfig) => {
  if (!currentSwitch.value) return;

  try {
    await updateSNMPConfig(currentSwitch.value.id, config);
    ElMessage.success('SNMP 配置保存成功');
    configDialogVisible.value = false;
    await loadSwitches();
  } catch (error: any) {
    ElMessage.error(`保存失败: ${error.response?.data?.detail || error.message || '未知错误'}`);
  }
};

// 删除配置
const handleDelete = async (switchItem: SwitchSNMPStatus) => {
  try {
    await ElMessageBox.confirm(
      `确定要删除交换机 "${switchItem.name}" 的 SNMP 配置吗？`,
      '确认删除',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }
    );

    await deleteSNMPConfig(switchItem.id);
    ElMessage.success('SNMP 配置已删除');
    await loadSwitches();
  } catch (error: any) {
    if (error !== 'cancel') {
      ElMessage.error(`删除失败: ${error.message || '未知错误'}`);
    }
  }
};

// 批量配置
const handleBatchConfig = () => {
  if (selectedSwitches.value.length === 0) {
    ElMessage.warning('请先选择要配置的交换机');
    return;
  }

  batchDialogVisible.value = true;
};

// 批量保存
const handleBatchSave = async (config: SNMPConfig) => {
  if (selectedSwitches.value.length === 0) {
    ElMessage.warning('请先选择要配置的交换机');
    return;
  }

  try {
    const switchIds = selectedSwitches.value.map(s => s.id);
    await batchUpdateSNMPConfig(switchIds, config);
    ElMessage.success(`成功为 ${switchIds.length} 台交换机配置 SNMP`);
    batchDialogVisible.value = false;
    await loadSwitches();
  } catch (error: any) {
    ElMessage.error(`批量配置失败: ${error.response?.data?.detail || error.message || '未知错误'}`);
  }
};

// 初始化
onMounted(() => {
  loadSwitches();
});
</script>

<style scoped>
.snmp-config-page {
  padding: 20px;

  .header-card {
    margin-bottom: 20px;

    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;

      span {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 16px;
        font-weight: 600;
      }
    }

    :deep(.el-alert) {
      p {
        margin: 4px 0;
        line-height: 1.6;
      }
    }
  }

  .table-card {
    .switch-name {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .text-muted {
      color: #909399;
    }

    .pagination {
      margin-top: 20px;
      display: flex;
      justify-content: flex-end;
    }
  }
}
</style>
