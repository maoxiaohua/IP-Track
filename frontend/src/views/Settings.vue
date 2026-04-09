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

      <!-- Additional settings placeholder -->
      <el-empty
        description="More settings coming soon"
        style="margin-top: 40px"
      />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useSettingsStore } from '@/stores/settings'
import { ElMessage } from 'element-plus'
import { SuccessFilled, WarningFilled, CircleCloseFilled, QuestionFilled } from '@element-plus/icons-vue'

const settingsStore = useSettingsStore()

onMounted(async () => {
  await settingsStore.loadSettings()
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
</style>
