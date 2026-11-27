/**
 * 列显示偏好：同一账号在多处表格间共享「哪些列可见」的选择。
 *
 * - 已登录：保存到后端 user_ui_preferences（GET/PUT /api/v1/ipam/preferences/{key}），
 *   换浏览器 / 换设备也能恢复；
 * - 只读访客（无 token）：退化为浏览器本地存储。
 *
 * 只保存「被隐藏的列 key」，这样以后在 ipColumns.ts 新增列时，
 * 新列对已有账号默认可见，无需迁移历史偏好。
 */
import { computed, ref } from 'vue'
import apiClient from '@/api/index'
import {
  IP_COLUMNS,
  IP_COLUMN_KEYS,
  IP_COLUMNS_DEFAULT_HIDDEN,
  type IPColumnDef
} from '@/components/ipam/ipColumns'

const STORAGE_PREFIX = 'iptrack.column-prefs.'

const hasToken = (): boolean => {
  try {
    return Boolean(localStorage.getItem('iptrack_token'))
  } catch {
    return false
  }
}

const sanitizeHiddenKeys = (value: unknown, fallback: string[]): string[] | null => {
  const raw =
    value && typeof value === 'object' && !Array.isArray(value) && 'hidden' in value
      ? (value as { hidden?: unknown }).hidden
      : value
  if (!Array.isArray(raw)) return null
  const keys = raw.filter(
    (key): key is string => typeof key === 'string' && IP_COLUMN_KEYS.includes(key)
  )
  // 全部列都被隐藏会让表格变成空白，强制保留至少一列
  if (keys.length >= IP_COLUMN_KEYS.length) return [...fallback]
  return keys
}

const preferenceUrl = (prefKey: string) =>
  `/api/v1/ipam/preferences/${encodeURIComponent(prefKey)}`

/**
 * @param defaultHiddenKeys 本页面的默认隐藏列，默认沿用 ipColumns 的全局默认
 *   （例如下钻页需要默认显示「MAC 地址 / 最近扫描时间」，就传入自己的列表）
 */
export function useColumnPreferences(
  prefKey: string,
  defaultHiddenKeys: string[] = IP_COLUMNS_DEFAULT_HIDDEN
) {
  const defaults = defaultHiddenKeys.filter((key) => IP_COLUMN_KEYS.includes(key))
  const hiddenKeys = ref<string[]>([...defaults])
  const saving = ref(false)
  const loaded = ref(false)

  const visibleColumns = computed<IPColumnDef[]>(() =>
    IP_COLUMNS.filter((column) => !hiddenKeys.value.includes(column.key))
  )

  const visibleKeys = computed(() => visibleColumns.value.map((column) => column.key))

  const isVisible = (key: string) => !hiddenKeys.value.includes(key)

  const load = async () => {
    try {
      if (hasToken()) {
        const res = await apiClient.get(preferenceUrl(prefKey))
        const parsed = sanitizeHiddenKeys(res.data?.value, defaults)
        if (parsed) hiddenKeys.value = parsed
      } else {
        const raw = localStorage.getItem(STORAGE_PREFIX + prefKey)
        if (raw) {
          const parsed = sanitizeHiddenKeys(JSON.parse(raw), defaults)
          if (parsed) hiddenKeys.value = parsed
        }
      }
    } catch (error) {
      // 读取失败时继续用默认列，不影响表格展示
      console.warn('加载列设置失败:', error)
    } finally {
      loaded.value = true
    }
  }

  const save = async () => {
    const value = { hidden: [...hiddenKeys.value] }
    saving.value = true
    try {
      if (hasToken()) {
        await apiClient.put(preferenceUrl(prefKey), { value })
      } else {
        localStorage.setItem(STORAGE_PREFIX + prefKey, JSON.stringify(value))
      }
    } finally {
      saving.value = false
    }
  }

  const toggle = (key: string, visible: boolean) => {
    if (!IP_COLUMN_KEYS.includes(key)) return
    if (visible) {
      hiddenKeys.value = hiddenKeys.value.filter((item) => item !== key)
      return
    }
    // 至少保留一列可见
    if (!hiddenKeys.value.includes(key) && hiddenKeys.value.length < IP_COLUMN_KEYS.length - 1) {
      hiddenKeys.value = [...hiddenKeys.value, key]
    }
  }

  const reset = () => {
    hiddenKeys.value = [...defaults]
  }

  return {
    columns: IP_COLUMNS,
    visibleColumns,
    visibleKeys,
    hiddenKeys,
    saving,
    loaded,
    load,
    save,
    toggle,
    reset,
    isVisible
  }
}
