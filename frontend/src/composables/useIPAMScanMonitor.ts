import { onBeforeUnmount, ref } from 'vue'
import { ipamApi, type IPAMScanStatus } from '@/api/ipam'

interface UseIPAMScanMonitorOptions {
  onStatus?: (status: IPAMScanStatus, previous: IPAMScanStatus | null) => void
}

export const useIPAMScanMonitor = (options: UseIPAMScanMonitorOptions = {}) => {
  const scanStatus = ref<IPAMScanStatus | null>(null)
  const monitorSupported = ref(true)

  let eventSource: EventSource | null = null
  let reconnectTimer: number | null = null

  const applyStatus = (status: IPAMScanStatus) => {
    const previous = scanStatus.value
    scanStatus.value = status
    options.onStatus?.(status, previous)
  }

  const loadInitialStatus = async () => {
    try {
      const status = await ipamApi.getScanStatus()
      monitorSupported.value = true
      applyStatus(status)
      return true
    } catch (error: any) {
      if (error?.response?.status === 404) {
        monitorSupported.value = false
        return false
      }
      console.error('Failed to load IPAM scan status:', error)
      return false
    }
  }

  const disconnect = () => {
    if (reconnectTimer !== null) {
      window.clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (eventSource) {
      eventSource.close()
      eventSource = null
    }
  }

  const connect = () => {
    if (eventSource || !monitorSupported.value) {
      return
    }

    eventSource = new EventSource(ipamApi.getScanEventsUrl())

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as IPAMScanStatus
        applyStatus(data)
      } catch (error) {
        console.error('Failed to parse IPAM scan event:', error)
      }
    }

    eventSource.onerror = () => {
      disconnect()
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
    scanStatus,
    monitorSupported,
    connect,
    disconnect,
    loadInitialStatus
  }
}
