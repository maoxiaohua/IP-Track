import { defineStore } from 'pinia'
import { ref } from 'vue'
import { bmcApi, type BMCServer, type BMCServerCreate, type BMCServerUpdate, type BMCResetHistory, type BMCGlobalCredentials, type BMCCredentialProfile, type BMCCredentialProfileCreate, type BMCCredentialProfileUpdate } from '@/api/bmc'

export const useBMCStore = defineStore('bmc', () => {
  const servers = ref<BMCServer[]>([])
  const serversTotal = ref(0)
  const serversLoading = ref(false)

  const history = ref<BMCResetHistory[]>([])
  const historyTotal = ref(0)
  const historyLoading = ref(false)

  const globalCredentials = ref<BMCGlobalCredentials>({ username: '', password_set: false })
  const credsLoading = ref(false)

  const credentialProfiles = ref<BMCCredentialProfile[]>([])
  const profilesLoading = ref(false)

  const error = ref<string | null>(null)

  async function loadServers(params?: { skip?: number; limit?: number; enabled_only?: boolean; verified?: boolean | null; search?: string }) {
    serversLoading.value = true
    error.value = null
    try {
      const res = await bmcApi.getServers(params)
      servers.value = res.items
      serversTotal.value = res.total
    } catch (e: any) {
      error.value = e.message || 'Failed to load BMC servers'
    } finally {
      serversLoading.value = false
    }
  }

  async function createServer(data: BMCServerCreate) {
    const server = await bmcApi.createServer(data)
    await loadServers()
    return server
  }

  async function updateServer(id: number, data: BMCServerUpdate) {
    const server = await bmcApi.updateServer(id, data)
    await loadServers()
    return server
  }

  async function deleteServer(id: number) {
    await bmcApi.deleteServer(id)
    await loadServers()
  }

  async function loadHistory(params?: { server_id?: number; status?: string; skip?: number; limit?: number }) {
    historyLoading.value = true
    try {
      const res = await bmcApi.getResetHistory(params)
      history.value = res.items
      historyTotal.value = res.total
    } finally {
      historyLoading.value = false
    }
  }

  async function loadGlobalCredentials() {
    credsLoading.value = true
    try {
      globalCredentials.value = await bmcApi.getGlobalCredentials()
    } finally {
      credsLoading.value = false
    }
  }

  async function updateGlobalCredentials(username: string, password?: string) {
    await bmcApi.updateGlobalCredentials({ username, password })
    await loadGlobalCredentials()
  }

  // Credential Profiles
  async function loadCredentialProfiles() {
    profilesLoading.value = true
    try {
      credentialProfiles.value = await bmcApi.getCredentialProfiles()
    } finally {
      profilesLoading.value = false
    }
  }

  async function createCredentialProfile(data: BMCCredentialProfileCreate) {
    const profile = await bmcApi.createCredentialProfile(data)
    await loadCredentialProfiles()
    return profile
  }

  async function updateCredentialProfile(id: number, data: BMCCredentialProfileUpdate) {
    const profile = await bmcApi.updateCredentialProfile(id, data)
    await loadCredentialProfiles()
    return profile
  }

  async function deleteCredentialProfile(id: number) {
    await bmcApi.deleteCredentialProfile(id)
    await loadCredentialProfiles()
  }

  return {
    servers, serversTotal, serversLoading,
    history, historyTotal, historyLoading,
    globalCredentials, credsLoading,
    credentialProfiles, profilesLoading,
    error,
    loadServers, createServer, updateServer, deleteServer,
    loadHistory,
    loadGlobalCredentials, updateGlobalCredentials,
    loadCredentialProfiles, createCredentialProfile, updateCredentialProfile, deleteCredentialProfile,
  }
})
