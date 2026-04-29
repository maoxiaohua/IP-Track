import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { settingsApi } from '@/api/settings'

export const useSettingsStore = defineStore('settings', () => {
  const loading = ref(false)
  const error = ref<string | null>(null)

  const cacheHours = ref<number>(24)
  const cacheHoursMin = ref<number>(1)
  const cacheHoursMax = ref<number>(168)
  const lastUpdated = ref<Date | null>(null)

  const isDirty = ref(false)
  const isSaving = ref(false)

  // Load settings from backend
  const loadSettings = async () => {
    loading.value = true
    error.value = null

    try {
      const settings = await settingsApi.getIPLookupSettings()
      cacheHours.value = settings.cache_hours
      cacheHoursMin.value = settings.cache_hours_min
      cacheHoursMax.value = settings.cache_hours_max
      lastUpdated.value = new Date()
      isDirty.value = false
    } catch (err: any) {
      error.value = err.message || 'Failed to load settings'
    } finally {
      loading.value = false
    }
  }

  // Update cache hours
  const updateCacheHours = async (hours: number) => {
    if (hours < cacheHoursMin.value || hours > cacheHoursMax.value) {
      error.value = `Cache hours must be between ${cacheHoursMin.value} and ${cacheHoursMax.value}`
      return false
    }

    isSaving.value = true
    error.value = null

    try {
      const result = await settingsApi.updateCacheHours(hours)
      cacheHours.value = parseInt(result.value)
      lastUpdated.value = new Date()
      isDirty.value = false
      return true
    } catch (err: any) {
      error.value = err.message || 'Failed to update cache hours'
      return false
    } finally {
      isSaving.value = false
    }
  }

  // Mark as dirty when user changes value
  const setCacheHours = (hours: number) => {
    cacheHours.value = hours
    isDirty.value = true
  }

  // Reset to last saved value
  const reset = () => {
    loadSettings()
  }

  // Validation computed property
  const isValidCacheHours = computed(() => {
    return cacheHours.value >= cacheHoursMin.value &&
           cacheHours.value <= cacheHoursMax.value
  })

  return {
    // State
    loading,
    error,
    cacheHours,
    cacheHoursMin,
    cacheHoursMax,
    lastUpdated,
    isDirty,
    isSaving,

    // Computed
    isValidCacheHours,

    // Methods
    loadSettings,
    updateCacheHours,
    setCacheHours,
    reset
  }
})
