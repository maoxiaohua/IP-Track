import { onBeforeUnmount, ref } from 'vue'
import { bmcApi, type BMCResetStatus } from '@/api/bmc'

interface UseBMCResetMonitorOptions {
  onStatus?: (status: BMCResetStatus, previous: BMCResetStatus | null) => void
  onUnavailable?: () => void
}

export const useBMCResetMonitor = (options: UseBMCResetMonitorOptions = {}) => {
  const resetStatus = ref<BMCResetStatus | null>(null)
  const monitorSupported = ref(true)

  let eventSource: EventSource | null = null
  let reconnectTimer: number | null = null
  let rafId: number | null = null
  let pendingStatus: BMCResetStatus | null = null
  // 连续连接失败次数，避免 SSE 一直连不上时页面永远等不到状态
  let connectFailures = 0
  const MAX_CONNECT_FAILURES = 3

  const applyStatus = (status: BMCResetStatus) => {
    const previous = resetStatus.value
    resetStatus.value = status
    options.onStatus?.(status, previous)
  }

  const loadInitialStatus = async () => {
    try {
      const status = await bmcApi.getResetStatus()
      monitorSupported.value = true
      applyStatus(status)
      return true
    } catch (error: any) {
      if (error?.response?.status === 404) {
        monitorSupported.value = false
        return false
      }
      console.error('Failed to load BMC reset status:', error)
      return false
    }
  }

  const disconnect = () => {
    if (reconnectTimer !== null) {
      window.clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (rafId !== null) {
      cancelAnimationFrame(rafId)
      rafId = null
    }
    pendingStatus = null
    if (eventSource) {
      eventSource.close()
      eventSource = null
    }
  }

  const connect = () => {
    if (eventSource || !monitorSupported.value) {
      return
    }

    eventSource = new EventSource(bmcApi.getResetEventsUrl())

    eventSource.onmessage = (event) => {
      connectFailures = 0
      try {
        pendingStatus = JSON.parse(event.data) as BMCResetStatus
        if (rafId === null) {
          rafId = requestAnimationFrame(() => {
            rafId = null
            if (pendingStatus) {
              applyStatus(pendingStatus)
              pendingStatus = null
            }
          })
        }
      } catch (error) {
        console.error('Failed to parse BMC reset event:', error)
      }
    }

    eventSource.onerror = () => {
      disconnect()
      connectFailures += 1
      if (connectFailures >= MAX_CONNECT_FAILURES) {
        // 无法建立实时连接时通知页面，避免按钮一直卡在 loading
        monitorSupported.value = false
        options.onUnavailable?.()
        return
      }
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = null
        connect()
      }, 3000)
    }
  }

  onBeforeUnmount(() => {
    disconnect()
  })

  return {
    resetStatus,
    monitorSupported,
    connect,
    disconnect,
    loadInitialStatus,
  }
}
