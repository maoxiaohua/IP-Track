import { defineStore } from 'pinia'
import { ref } from 'vue'
import { lookupApi, type IPLookupResult } from '@/api/lookup'

export const useLookupStore = defineStore('lookup', () => {
  const loading = ref(false)
  const currentResult = ref<IPLookupResult | null>(null)
  const error = ref<string | null>(null)

  const lookupIP = async (ipAddress: string) => {
    loading.value = true
    error.value = null
    currentResult.value = null

    try {
      const response = await lookupApi.lookupIP(ipAddress)

      if (response.success && response.result) {
        currentResult.value = response.result
      } else {
        error.value = response.error || 'Lookup failed'
      }
    } catch (err: any) {
      error.value = err.message || 'An error occurred during lookup'
    } finally {
      loading.value = false
    }
  }

  const clearResult = () => {
    currentResult.value = null
    error.value = null
  }

  return {
    loading,
    currentResult,
    error,
    lookupIP,
    clearResult
  }
})
