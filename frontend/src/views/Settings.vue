<template>
  <div class="settings-view">
    <el-card class="settings-card">
      <template #header>
        <div class="card-header">
          <h2>Settings</h2>
          <p>Configure IP-Track system parameters</p>
        </div>
      </template>

      <!-- IP Lookup Settings Section -->
      <el-card class="section-card">
        <template #header>
          <div class="section-header">
            <h3>IP Lookup Configuration</h3>
          </div>
        </template>

        <el-row :gutter="20">
          <el-col :span="12">
            <div class="setting-group">
              <label class="setting-label">
                <span>Cache Query Window (Hours)</span>
                <el-tooltip content="How many hours of historical data to search in IP lookups" placement="top">
                  <el-icon><QuestionFilled /></el-icon>
                </el-tooltip>
              </label>

              <div class="setting-input-wrapper">
                <el-input-number
                  v-model="settingsStore.cacheHours"
                  :min="settingsStore.cacheHoursMin"
                  :max="settingsStore.cacheHoursMax"
                  :step="1"
                  size="large"
                  placeholder="Enter cache hours"
                  @change="settingsStore.setCacheHours"
                />
                <span class="setting-hint">
                  Range: {{ settingsStore.cacheHoursMin }} - {{ settingsStore.cacheHoursMax }} hours
                </span>
              </div>

              <div class="setting-description">
                <p>
                  Controls the time window used when querying cached ARP/MAC tables.
                  A larger window includes older data (slower queries, more comprehensive).
                  A smaller window is faster but may miss devices that haven't been seen recently.
                </p>
                <p v-if="settingsStore.lastUpdated">
                  <strong>Last updated:</strong> {{ formatTime(settingsStore.lastUpdated) }}
                </p>
              </div>
            </div>
          </el-col>

          <el-col :span="12">
            <div class="impact-box">
              <h4>Impact of Changes</h4>
              <ul>
                <li v-if="settingsStore.cacheHours >= 48">
                  <el-icon color="#67c23a"><SuccessFilled /></el-icon>
                  <span>Searching 2+ days of data - comprehensive but slower</span>
                </li>
                <li v-else-if="settingsStore.cacheHours >= 24">
                  <el-icon color="#e6a23c"><WarningFilled /></el-icon>
                  <span>Searching 1+ day of data - balanced approach</span>
                </li>
                <li v-else>
                  <el-icon color="#f56c6c"><CircleCloseFilled /></el-icon>
                  <span>Searching &lt;24 hours - fast but may miss devices</span>
                </li>
              </ul>
              <p class="impact-note">
                Changes take effect immediately without restarting the backend.
              </p>
            </div>
          </el-col>
        </el-row>

        <!-- Error display -->
        <el-alert
          v-if="settingsStore.error"
          type="error"
          :title="settingsStore.error"
          :closable="true"
          @close="settingsStore.error = null"
          style="margin-bottom: 20px; margin-top: 20px"
        />

        <!-- Action buttons -->
        <div class="action-buttons">
          <el-button
            type="primary"
            @click="handleSave"
            :loading="settingsStore.isSaving"
            :disabled="!settingsStore.isDirty || !settingsStore.isValidCacheHours"
          >
            Save Changes
          </el-button>
          <el-button
            @click="settingsStore.reset"
            :disabled="!settingsStore.isDirty"
          >
            Cancel
          </el-button>
        </div>
      </el-card>

      <!-- Hardware Inventory (IPAM SN / model) -->
      <el-card class="section-card" style="margin-top: 20px">
        <template #header>
          <div class="section-header">
            <h3>Hardware Inventory (IPAM)</h3>
          </div>
        </template>

        <el-form label-width="220px" v-loading="hardwareLoading">
          <el-form-item label="自动采集开关">
            <el-switch v-model="hardwareForm.enabled" />
            <span class="hardware-hint">关闭后停止自动采集，已采集的 SN 不会被清空</span>
          </el-form-item>
          <el-form-item label="失败重试间隔（小时）">
            <el-input-number v-model="hardwareForm.retry_hours" :min="1" :max="720" />
          </el-form-item>
          <el-form-item label="默认 SNMP Community">
            <el-input
              v-model="hardwareForm.default_community"
              type="password"
              show-password
              clearable
              style="max-width: 320px"
              :placeholder="hardwareSettings.default_community_configured ? '已配置，留空保持不变' : '未配置'"
            />
          </el-form-item>
          <el-form-item label="WMI / WinRM 域">
            <el-input
              v-model="hardwareForm.wmi_domain"
              clearable
              style="max-width: 320px"
              placeholder="留空表示本机账号"
            />
          </el-form-item>
          <el-form-item label="WMI / WinRM 用户名">
            <el-input v-model="hardwareForm.wmi_username" clearable style="max-width: 320px" />
          </el-form-item>
          <el-form-item label="WMI / WinRM 口令">
            <el-input
              v-model="hardwareForm.wmi_password"
              type="password"
              show-password
              clearable
              style="max-width: 320px"
              :placeholder="hardwareSettings.wmi_password_configured ? '已配置，留空保持不变' : '未配置'"
            />
          </el-form-item>
          <el-form-item label="WMI 并发数">
            <el-input-number v-model="hardwareForm.wmi_concurrency" :min="1" :max="8" />
            <span class="hardware-hint">建议保持 1，避免连续失败导致账号锁定</span>
          </el-form-item>
          <el-form-item label="每轮 WMI 采集上限">
            <el-input-number v-model="hardwareForm.wmi_max_per_sweep" :min="1" :max="1000" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="hardwareSaving" @click="saveHardwareSettings">
              保存硬件盘点设置
            </el-button>
          </el-form-item>
        </el-form>
      </el-card>

      <!-- Additional settings placeholder -->
      <el-empty
        description="More settings coming soon"
        style="margin-top: 40px"
      />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useSettingsStore } from '@/stores/settings'
import { ElMessage } from 'element-plus'
import { SuccessFilled, WarningFilled, CircleCloseFilled, QuestionFilled } from '@element-plus/icons-vue'
import { hardwareApi, type HardwareInventorySettings, type HardwareInventorySettingsUpdate } from '@/api/ipam'

const settingsStore = useSettingsStore()

const hardwareLoading = ref(false)
const hardwareSaving = ref(false)
const hardwareSettings = ref<HardwareInventorySettings>({
  enabled: true,
  retry_hours: 24,
  wmi_concurrency: 1,
  wmi_max_per_sweep: 50,
  default_community_configured: false,
  wmi_domain: '',
  wmi_username: '',
  wmi_password_configured: false
})
// 口令字段只提交用户新填的值，留空不覆盖
const hardwareForm = reactive({
  enabled: true,
  retry_hours: 24,
  wmi_concurrency: 1,
  wmi_max_per_sweep: 50,
  default_community: '',
  wmi_domain: '',
  wmi_username: '',
  wmi_password: ''
})

const loadHardwareSettings = async () => {
  hardwareLoading.value = true
  try {
    const data = await hardwareApi.getSettings()
    hardwareSettings.value = data
    hardwareForm.enabled = data.enabled
    hardwareForm.retry_hours = data.retry_hours
    hardwareForm.wmi_concurrency = data.wmi_concurrency
    hardwareForm.wmi_max_per_sweep = data.wmi_max_per_sweep
    hardwareForm.wmi_domain = data.wmi_domain || ''
    hardwareForm.wmi_username = data.wmi_username || ''
    hardwareForm.default_community = ''
    hardwareForm.wmi_password = ''
  } catch (error: any) {
    const detail = error?.response?.data?.detail
    ElMessage.error(detail || '加载硬件盘点设置失败')
  } finally {
    hardwareLoading.value = false
  }
}

const saveHardwareSettings = async () => {
  if (hardwareSaving.value) return
  hardwareSaving.value = true
  try {
    const payload: HardwareInventorySettingsUpdate = {
      enabled: hardwareForm.enabled,
      retry_hours: hardwareForm.retry_hours,
      wmi_concurrency: hardwareForm.wmi_concurrency,
      wmi_max_per_sweep: hardwareForm.wmi_max_per_sweep
    }
    // 非敏感字段按差异提交，避免误清空；口令仅在填写时覆盖
    if (hardwareForm.wmi_domain !== (hardwareSettings.value.wmi_domain || '')) {
      payload.wmi_domain = hardwareForm.wmi_domain
    }
    if (hardwareForm.wmi_username !== (hardwareSettings.value.wmi_username || '')) {
      payload.wmi_username = hardwareForm.wmi_username
    }
    if (hardwareForm.default_community) {
      payload.default_community = hardwareForm.default_community
    }
    if (hardwareForm.wmi_password) {
      payload.wmi_password = hardwareForm.wmi_password
    }
    await hardwareApi.updateSettings(payload)
    ElMessage.success('硬件盘点设置已保存')
    await loadHardwareSettings()
  } catch (error: any) {
    const detail = error?.response?.data?.detail
    ElMessage.error(detail || '保存硬件盘点设置失败')
  } finally {
    hardwareSaving.value = false
  }
}

onMounted(async () => {
  await settingsStore.loadSettings()
  await loadHardwareSettings()
})

const formatTime = (date: Date): string => {
  return new Date(date).toLocaleString()
}

const handleSave = async () => {
  if (!settingsStore.isValidCacheHours) {
    ElMessage.error('Invalid cache hours value')
    return
  }

  const success = await settingsStore.updateCacheHours(settingsStore.cacheHours)
  if (success) {
    ElMessage.success('Settings updated successfully')
  } else {
    ElMessage.error(settingsStore.error || 'Failed to update settings')
  }
}
</script>

<style scoped>
.settings-view {
  max-width: 1200px;
  margin: 0 auto;
}

.settings-card {
  margin-bottom: 20px;
}

.card-header h2 {
  margin: 0 0 8px 0;
  color: #303133;
  font-size: 24px;
}

.card-header p {
  margin: 0;
  color: #909399;
  font-size: 14px;
}

.section-card {
  margin-bottom: 20px;
}

.section-header h3 {
  margin: 0;
  color: #303133;
  font-size: 18px;
}

.setting-group {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.setting-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  color: #303133;
}

.setting-input-wrapper {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.setting-input-wrapper :deep(.el-input-number) {
  width: 100%;
}

.setting-hint {
  font-size: 12px;
  color: #909399;
}

.setting-description {
  border-left: 3px solid #e4e7eb;
  padding-left: 12px;
  font-size: 13px;
  color: #606266;
  line-height: 1.6;
}

.setting-description p {
  margin: 0 0 8px 0;
}

.setting-description p:last-child {
  margin-bottom: 0;
}

.impact-box {
  background: #f0f9ff;
  border: 1px solid #b3d8ff;
  border-radius: 4px;
  padding: 16px;
  height: 100%;
}

.impact-box h4 {
  margin: 0 0 12px 0;
  color: #0066cc;
  font-weight: 600;
}

.impact-box ul {
  margin: 0;
  padding-left: 0;
  list-style: none;
}

.impact-box li {
  margin-bottom: 8px;
  color: #606266;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.impact-note {
  margin: 12px 0 0 0;
  padding-top: 12px;
  border-top: 1px solid #b3d8ff;
  font-size: 12px;
  color: #0066cc;
  font-style: italic;
}

.action-buttons {
  display: flex;
  gap: 12px;
  margin-top: 24px;
  padding-top: 24px;
  border-top: 1px solid #ebeef5;
}

.hardware-hint {
  margin-left: 12px;
  font-size: 12px;
  color: #909399;
}
</style>
