<template>
  <div class="column-settings">
    <el-popover
      v-model:visible="popoverVisible"
      placement="bottom-end"
      :width="260"
      trigger="click"
      @after-leave="handleClose"
    >
      <template #reference>
        <el-button size="small" :loading="saving">
          <el-icon style="margin-right: 4px"><Setting /></el-icon>
          列设置
        </el-button>
      </template>

      <div class="column-settings-panel">
        <div class="column-settings-title">显示列</div>
        <div class="column-settings-list">
          <el-checkbox
            v-for="col in columns"
            :key="col.key"
            :model-value="isVisible(col.key)"
            :label="col.label"
            size="small"
            class="column-settings-item"
            @update:model-value="(checked: unknown) => emit('toggle', col.key, Boolean(checked))"
          />
        </div>
        <div class="column-settings-footer">
          <el-button size="small" @click="emit('reset')">恢复默认</el-button>
          <span class="column-settings-hint">按账号自动保存</span>
        </div>
      </div>
    </el-popover>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElButton, ElCheckbox, ElIcon, ElPopover } from 'element-plus'
import { Setting } from '@element-plus/icons-vue'
import type { IPColumnDef } from './ipColumns'

withDefaults(
  defineProps<{
    columns: IPColumnDef[]
    isVisible: (key: string) => boolean
    saving?: boolean
  }>(),
  { saving: false }
)

const emit = defineEmits<{
  (e: 'toggle', key: string, visible: boolean): void
  (e: 'reset'): void
  (e: 'save'): void
}>()

const popoverVisible = ref(false)

// 弹层关闭时才落库，避免每勾一次就发一次请求
// 用 after-leave（ElPopover 声明的 emit），不要用 @hide（那是靠 $attrs 透传给内部 ElTooltip 的）
const handleClose = () => {
  emit('save')
}
</script>

<style scoped>
.column-settings-panel {
  max-height: 60vh;
  display: flex;
  flex-direction: column;
}

.column-settings-title {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 8px;
}

.column-settings-list {
  overflow-y: auto;
  max-height: 45vh;
  padding-right: 4px;
}

.column-settings-item {
  display: flex;
  width: 100%;
  margin-right: 0;
  height: 26px;
}

.column-settings-item :deep(.el-checkbox__label) {
  color: #303133;
  font-size: 13px;
}

.column-settings-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid #ebeef5;
}

.column-settings-hint {
  font-size: 12px;
  color: #909399;
}
</style>
