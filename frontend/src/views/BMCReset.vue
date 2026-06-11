<template>
  <div class="bmc-reset">
    <h2 class="page-title">BMC Reset</h2>

    <el-tabs v-model="activeTab" type="border-card">
      <!-- Tab 1: Server Inventory -->
      <el-tab-pane name="servers">
        <template #label>
          <span><el-icon><Monitor /></el-icon> Server Inventory</span>
        </template>

        <div class="toolbar">
          <el-button type="primary" @click="showServerDialog = true" :icon="Plus">Add Server</el-button>
          <el-button type="success" @click="showBatchDialog = true" :icon="Upload">Batch Import</el-button>
          <el-button @click="refreshServers" :icon="Refresh" :loading="store.serversLoading">Refresh</el-button>
          <el-select v-model="verifiedFilter" placeholder="Verified" clearable style="width:120px" @change="refreshServers">
            <el-option label="All" :value="null" />
            <el-option label="OK" :value="true" />
            <el-option label="Fail" :value="false" />
          </el-select>
          <el-input
            v-model="inventorySearch"
            placeholder="Search by name or IP..."
            clearable
            @input="serverPage = 1; refreshServers()"
            style="width:240px"
          >
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
          <el-button v-if="tableSelection.length > 0" type="success" @click="batchToggleEnabled(true)" :loading="batchToggling">
            Enable ({{ tableSelection.length }})
          </el-button>
          <el-button v-if="tableSelection.length > 0" type="info" @click="batchToggleEnabled(false)" :loading="batchToggling">
            Disable ({{ tableSelection.length }})
          </el-button>
          <el-button v-if="tableSelection.length > 0" type="warning" @click="bulkQueryInfo" :loading="bulkQuerying">
            Info ({{ tableSelection.length }})
          </el-button>
          <el-button v-if="tableSelection.length > 0" type="danger" @click="bulkDelete" :loading="bulkDeleting">
            Delete ({{ tableSelection.length }})
          </el-button>
          <el-button type="success" plain @click="exportCSV(true)" :icon="Download">Export OK</el-button>
          <el-button type="danger" plain @click="exportCSV(false)" :icon="Download">Export Fail</el-button>
        </div>

        <el-table :data="store.servers" v-loading="store.serversLoading" stripe @selection-change="handleSelectionChange">
          <el-table-column type="selection" width="45" />
          <el-table-column prop="name" label="Name" min-width="120" />
          <el-table-column label="Credential Source" min-width="150">
            <template #default="{ row }">
              <template v-if="row.credential_profile_name">
                <el-tag type="primary" size="small">Profile: {{ row.credential_profile_name }}</el-tag>
              </template>
              <template v-else-if="row.use_global_credentials">
                <el-tag type="warning" size="small">Global</el-tag>
              </template>
              <template v-else>
                <span>{{ row.username }}</span>
              </template>
            </template>
          </el-table-column>
          <el-table-column prop="serial_number" label="Serial Number" min-width="140">
            <template #default="{ row }">
              <span v-if="row.serial_number">{{ row.serial_number }}</span>
              <span v-else class="text-muted">—</span>
            </template>
          </el-table-column>
          <el-table-column prop="bmc_firmware_version" label="BMC Version" min-width="110">
            <template #default="{ row }">
              <span v-if="row.bmc_firmware_version">{{ row.bmc_firmware_version }}</span>
              <span v-else class="text-muted">—</span>
            </template>
          </el-table-column>
          <el-table-column label="Last Reset" min-width="140">
            <template #default="{ row }">
              <template v-if="row.last_reset_at">
                <div style="font-size:12px">{{ formatDate(row.last_reset_at) }}</div>
                <el-tag :type="row.last_reset_result === 'success' ? 'success' : 'danger'" size="small">
                  {{ row.last_reset_result }}
                </el-tag>
              </template>
              <span v-else class="text-muted">Never</span>
            </template>
          </el-table-column>
          <el-table-column label="Verified" width="90">
            <template #default="{ row }">
              <template v-if="row.verified">
                <el-tag type="success" size="small">OK</el-tag>
              </template>
              <template v-else>
                <el-tooltip :content="row.verify_error || 'Not verified'" placement="top">
                  <el-tag type="danger" size="small" style="cursor:help">Fail</el-tag>
                </el-tooltip>
              </template>
            </template>
          </el-table-column>
          <el-table-column label="Enabled" width="75">
            <template #default="{ row }">
              <el-tag :type="row.enabled ? 'success' : 'info'" size="small">{{ row.enabled ? 'Yes' : 'No' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="Actions" width="210" fixed="right">
            <template #default="{ row }">
              <el-button size="small" @click="queryInfo(row.id)" :loading="queryingId === row.id">Info</el-button>
              <el-button size="small" @click="editServer(row)">Edit</el-button>
              <el-button size="small" type="danger" @click="confirmDelete(row)">Del</el-button>
            </template>
          </el-table-column>
        </el-table>

        <el-pagination
          class="pagination"
          v-model:current-page="serverPage"
          :page-size="serverPageSize"
          :total="store.serversTotal"
          layout="total, prev, pager, next"
          @current-change="refreshServers"
        />
      </el-tab-pane>

      <!-- Tab 2: Global Settings -->
      <el-tab-pane name="settings">
        <template #label>
          <span><el-icon><Setting /></el-icon> Global Settings</span>
        </template>

        <el-card header="Credential Profiles" class="setting-card">
          <el-table :data="store.credentialProfiles" v-loading="store.profilesLoading" size="small" stripe>
            <el-table-column prop="name" label="Profile Name" min-width="140" />
            <el-table-column prop="username" label="Username" min-width="100" />
            <el-table-column prop="server_count" label="# Servers" width="80" />
            <el-table-column label="Actions" width="170" fixed="right">
              <template #default="{ row }">
                <el-button size="small" @click="editProfile(row)">Edit</el-button>
                <el-button size="small" type="danger" @click="confirmDeleteProfile(row)">Del</el-button>
              </template>
            </el-table-column>
          </el-table>
          <div style="margin-top:12px">
            <el-button type="primary" size="small" @click="showProfileDialog = true">Add Profile</el-button>
          </div>
        </el-card>

        <el-card header="Global IPMI Credentials (Fallback)" class="setting-card">
          <el-form :model="credsForm" label-width="180px" @submit.prevent="saveGlobalCreds">
            <el-form-item label="IPMI Username">
              <el-input v-model="credsForm.username" placeholder="e.g. admin" />
            </el-form-item>
            <el-form-item label="IPMI Password">
              <el-input v-model="credsForm.password" type="password" show-password placeholder="Leave blank to keep current" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="saveGlobalCreds" :loading="savingCreds">Save Credentials</el-button>
            </el-form-item>
          </el-form>
        </el-card>

        <el-card header="Monthly Schedule" class="setting-card">
          <el-form label-width="180px">
            <el-form-item label="Enable Monthly Reset">
              <el-switch v-model="schedEnabled" @change="saveSchedule" />
            </el-form-item>
            <el-form-item label="Day of Month">
              <el-input-number v-model="schedDay" :min="1" :max="28" @change="saveSchedule" />
            </el-form-item>
            <el-form-item label="Hour (0-23)">
              <el-input-number v-model="schedHour" :min="0" :max="23" @change="saveSchedule" />
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>

      <!-- Tab 3: Reset Execution -->
      <el-tab-pane name="execute">
        <template #label>
          <span><el-icon><VideoPlay /></el-icon> Reset Execution</span>
        </template>

        <el-card header="Select Servers to Reset">
          <div style="margin-bottom:12px">
            <el-input
              v-model="resetSearch"
              placeholder="Search by name or IP..."
              clearable
              @input="loadResetServers"
              style="max-width:320px"
            >
              <template #prefix><el-icon><Search /></el-icon></template>
            </el-input>
          </div>
          <el-table
            :data="resetServers"
            v-loading="resetServersLoading"
            @selection-change="(v: BMCServer[]) => selectedServers = v.map(s => s.id)"
            stripe
          >
            <el-table-column type="selection" width="55" :selectable="(r: BMCServer) => r.enabled && r.verified" />
            <el-table-column prop="name" label="Name" />
            <el-table-column prop="host" label="Host / IP" />
            <el-table-column prop="serial_number" label="Serial Number" min-width="130">
              <template #default="{ row }">
                <span v-if="row.serial_number">{{ row.serial_number }}</span>
                <span v-else class="text-muted">—</span>
              </template>
            </el-table-column>
            <el-table-column label="Last Result" width="100">
              <template #default="{ row }">
                <el-tag v-if="row.last_reset_result" :type="row.last_reset_result === 'success' ? 'success' : 'danger'" size="small">
                  {{ row.last_reset_result }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>

          <div style="margin-top:16px">
            <el-button
              type="danger"
              @click="startReset"
              :disabled="!selectedServers.length || resetRunning"
              :loading="resetRunning"
            >
              Reset Selected ({{ selectedServers.length }})
            </el-button>
          </div>
        </el-card>

        <!-- Live Progress -->
        <el-card v-if="resetStatus && (resetStatus.running || resetStatus.current_phase !== 'idle')" header="Progress" class="progress-card">
          <div v-if="resetStatus.running" class="progress-body">
            <el-progress
              :percentage="resetStatus.total_servers ? Math.round(resetStatus.completed_servers / resetStatus.total_servers * 100) : 0"
              :status="resetStatus.failure_count > 0 ? 'warning' : undefined"
              :stroke-width="20"
            />
            <div class="progress-stats">
              <span>Completed: {{ resetStatus.completed_servers }} / {{ resetStatus.total_servers }}</span>
              <span class="success-text">Success: {{ resetStatus.success_count }}</span>
              <span class="failure-text">Failed: {{ resetStatus.failure_count }}</span>
            </div>
            <div v-if="resetStatus.current_server_name" class="current-server">
              Current: {{ resetStatus.current_server_name }} ({{ resetStatus.current_server_host }})
              — Attempt {{ resetStatus.current_attempt }}, {{ resetStatus.current_interface }}
            </div>
          </div>

          <!-- Completion Summary -->
          <div v-if="!resetStatus.running && resetStatus.results.length > 0" class="results-summary">
            <h4>Result Summary</h4>
            <el-table :data="resetStatus.results" stripe size="small">
              <el-table-column prop="server_name" label="Server" />
              <el-table-column prop="server_host" label="Host" />
              <el-table-column label="Status" width="100">
                <template #default="{ row }">
                  <el-tag :type="row.status === 'success' ? 'success' : 'danger'" size="small">{{ row.status }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="Error" min-width="200">
                <template #default="{ row }">
                  <template v-if="row.error_category">
                    <el-tag size="small" style="margin-right:6px">{{ row.error_category }}</el-tag>
                    {{ row.error_message?.slice(0, 120) }}
                  </template>
                  <span v-else class="success-text">—</span>
                </template>
              </el-table-column>
              <el-table-column prop="attempts_made" label="Attempts" width="80" />
              <el-table-column label="Duration" width="100">
                <template #default="{ row }">{{ row.duration_ms }}ms</template>
              </el-table-column>
            </el-table>
          </div>

          <!-- Error Log -->
          <div v-if="!resetStatus.running && errorLog.length > 0" class="error-log">
            <el-button size="small" @click="showErrorLog = !showErrorLog" :type="showErrorLog ? 'danger' : 'default'">
              {{ showErrorLog ? 'Hide' : 'Show' }} Error Log ({{ errorLog.length }})
            </el-button>
            <el-tag v-if="resetStatus.error" type="danger" size="small" style="margin-left:8px">{{ resetStatus.error }}</el-tag>
            <div v-if="showErrorLog" class="error-log-list">
              <div v-for="(entry, i) in errorLog" :key="i" class="error-entry">
                <span class="error-time">{{ entry.time }}</span>
                <strong>{{ entry.server }}</strong> ({{ entry.host }})
                <el-tag size="small" type="danger" style="margin-left:6px">{{ entry.category }}</el-tag>
                <div class="error-msg">{{ entry.message }}</div>
              </div>
            </div>
          </div>
        </el-card>
      </el-tab-pane>

      <!-- Tab 4: Reset History -->
      <el-tab-pane name="history">
        <template #label>
          <span><el-icon><Clock /></el-icon> Reset History</span>
        </template>

        <div class="toolbar">
          <el-select v-model="historyFilterStatus" placeholder="Filter by status" clearable @change="loadHistory" style="width:140px">
            <el-option label="Success" value="success" />
            <el-option label="Failure" value="failure" />
          </el-select>
          <el-select v-model="historyFilterServer" placeholder="Filter by server" clearable @change="loadHistory" style="width:200px;margin-left:8px">
            <el-option v-for="s in store.servers" :key="s.id" :label="s.name" :value="s.id" />
          </el-select>
          <el-button @click="loadHistory" :icon="Refresh" :loading="store.historyLoading" style="margin-left:8px">Refresh</el-button>
        </div>

        <el-table :data="store.history" v-loading="store.historyLoading" stripe>
          <el-table-column label="Time" width="170">
            <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
          </el-table-column>
          <el-table-column prop="server_name" label="Server" width="140" />
          <el-table-column prop="server_host" label="Host" width="140" />
          <el-table-column label="Status" width="90">
            <template #default="{ row }">
              <el-tag :type="row.status === 'success' ? 'success' : 'danger'" size="small">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="Error" min-width="160">
            <template #default="{ row }">
              <template v-if="row.error_category">
                <el-tag size="small" type="warning" style="margin-right:6px">{{ row.error_category }}</el-tag>
              </template>
              <el-tooltip v-if="row.error_message" :content="row.error_message" placement="top">
                <span class="error-preview">{{ row.error_message?.slice(0, 80) }}{{ row.error_message.length > 80 ? '...' : '' }}</span>
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column prop="attempts_made" label="Attempts" width="80" />
          <el-table-column label="Duration" width="90">
            <template #default="{ row }">{{ row.duration_ms }}ms</template>
          </el-table-column>
          <el-table-column prop="triggered_by" label="Trigger" width="100" />
        </el-table>

        <el-pagination
          v-if="store.historyTotal > 0"
          class="pagination"
          :total="store.historyTotal"
          v-model:current-page="historyPage"
          :page-size="50"
          layout="total, prev, pager, next"
          @current-change="loadHistory"
        />
      </el-tab-pane>
    </el-tabs>

    <!-- Server Add/Edit Dialog -->
    <el-dialog v-model="showServerDialog" :title="editingServer ? 'Edit Server' : 'Add Server'" width="560px">
      <el-form :model="serverForm" label-width="180px">
        <el-form-item label="Name" required>
          <el-input v-model="serverForm.name" placeholder="e.g. Server-01" />
        </el-form-item>
        <el-form-item label="Host / IP" required>
          <el-input v-model="serverForm.host" placeholder="e.g. 10.57.135.202" />
        </el-form-item>
        <el-form-item label="Credential Source" required>
          <el-select v-model="serverForm.credential_source" placeholder="Select credential source" style="width:100%">
            <el-option label="Use Global Credentials" value="global" />
            <el-option
              v-for="p in store.credentialProfiles"
              :key="'p'+p.id"
              :label="'Profile: ' + p.name"
              :value="'profile:'+p.id"
            />
            <el-option label="Custom (per-server)" value="custom" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="serverForm.credential_source === 'custom'" label="IPMI Username">
          <el-input v-model="serverForm.username" placeholder="e.g. admin" />
        </el-form-item>
        <el-form-item v-if="serverForm.credential_source === 'custom'" label="IPMI Password">
          <el-input v-model="serverForm.password" type="password" show-password placeholder="Per-server password" />
        </el-form-item>
        <el-form-item label="Enabled">
          <el-switch v-model="serverForm.enabled" />
        </el-form-item>
        <el-form-item label="Notes">
          <el-input v-model="serverForm.notes" type="textarea" :rows="2" placeholder="Optional notes" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showServerDialog = false">Cancel</el-button>
        <el-button type="primary" @click="saveServer" :loading="savingServer">
          {{ editingServer ? 'Update' : 'Create' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- Batch Import Dialog -->
    <el-dialog v-model="showBatchDialog" title="Batch Import by IP Range" width="560px">
      <el-form :model="batchForm" label-width="180px">
        <el-form-item label="IP List">
          <el-input v-model="batchForm.ips" type="textarea" :rows="4" placeholder="One IP per line, or comma-separated. Takes priority over range below." />
        </el-form-item>
        <el-form-item label="Or IP Range Start">
          <el-input v-model="batchForm.ip_start" placeholder="e.g. 10.57.135.1" />
        </el-form-item>
        <el-form-item label="IP Range End">
          <el-input v-model="batchForm.ip_end" placeholder="e.g. 10.57.135.100" />
        </el-form-item>
        <el-form-item label="Credential Source">
          <el-select v-model="batchForm.credential_source" placeholder="Select credential source" style="width:100%">
            <el-option label="Use Global Credentials" value="global" />
            <el-option
              v-for="p in store.credentialProfiles"
              :key="'bp'+p.id"
              :label="'Profile: ' + p.name"
              :value="'profile:'+p.id"
            />
            <el-option label="Custom (inline)" value="custom" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="batchForm.credential_source === 'custom'" label="IPMI Username">
          <el-input v-model="batchForm.username" placeholder="IPMI username" />
        </el-form-item>
        <el-form-item v-if="batchForm.credential_source === 'custom'" label="IPMI Password">
          <el-input v-model="batchForm.password" type="password" show-password placeholder="Leave empty if using global" />
        </el-form-item>
        <el-form-item label="Enabled">
          <el-switch v-model="batchForm.enabled" />
        </el-form-item>
      </el-form>

      <div v-if="batchResult" class="batch-result">
        <el-alert
          :type="batchResult.errors.length > 0 ? 'warning' : 'success'"
          :title="`Created ${batchResult.created}, skipped ${batchResult.skipped} (total ${batchResult.total})`"
          :closable="false"
          show-icon
        />
        <div v-if="batchResult.errors.length > 0" style="margin-top:8px;max-height:120px;overflow-y:auto">
          <div v-for="(err, i) in batchResult.errors" :key="i" class="error-preview">{{ err }}</div>
        </div>
      </div>

      <template #footer>
        <el-button @click="showBatchDialog = false">Close</el-button>
        <el-button type="primary" @click="doBatchImport" :loading="batchImporting">
          Import
        </el-button>
      </template>
    </el-dialog>

    <!-- Credential Profile Dialog -->
    <el-dialog v-model="showProfileDialog" :title="editingProfile ? 'Edit Profile' : 'Add Profile'" width="500px">
      <el-form :model="profileForm" label-width="140px">
        <el-form-item label="Profile Name" required>
          <el-input v-model="profileForm.name" placeholder="e.g. Production, Lab" />
        </el-form-item>
        <el-form-item label="IPMI Username" required>
          <el-input v-model="profileForm.username" placeholder="e.g. admin" />
        </el-form-item>
        <el-form-item label="IPMI Password">
          <el-input v-model="profileForm.password" type="password" show-password placeholder="Leave empty to keep current" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showProfileDialog = false">Cancel</el-button>
        <el-button type="primary" @click="saveProfile" :loading="savingProfile">
          {{ editingProfile ? 'Update' : 'Create' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Plus, Refresh, Upload, Monitor, Setting, VideoPlay, Clock, Download } from '@element-plus/icons-vue'
import { useBMCStore } from '@/stores/bmc'
import { bmcApi, type BMCServer, type BMCResetStatus, type BMCCredentialProfile } from '@/api/bmc'
import { API_BASE_URL } from '@/api/index'
import { useBMCResetMonitor } from '@/composables/useBMCResetMonitor'

const store = useBMCStore()
const activeTab = ref('servers')
const serverPage = ref(1)
const serverPageSize = 100
const verifiedFilter = ref<boolean | null>(null)
const inventorySearch = ref('')
const tableSelection = ref<BMCServer[]>([])
const bulkQuerying = ref(false)
const batchToggling = ref(false)

// Reset Execution tab — load ALL verified servers (not paginated)
const resetServers = ref<BMCServer[]>([])
const resetServersLoading = ref(false)
const resetSearch = ref('')

async function loadResetServers() {
  resetServersLoading.value = true
  try {
    const search = resetSearch.value || undefined
    let allServers: BMCServer[] = []
    let skip = 0
    const pageSize = 500
    while (true) {
      const res = await bmcApi.getServers({ skip, limit: pageSize, verified: true, search })
      allServers = allServers.concat(res.items)
      if (skip + pageSize >= res.total) break
      skip += pageSize
    }
    resetServers.value = allServers.filter(s => s.verified)
  } finally {
    resetServersLoading.value = false
  }
}
const bulkDeleting = ref(false)

// ── Server CRUD ─────────────────────────────────────────────

const showServerDialog = ref(false)
const editingServer = ref<BMCServer | null>(null)
const savingServer = ref(false)

// Batch import state
const showBatchDialog = ref(false)
const batchImporting = ref(false)
const batchResult = ref<import('@/api/bmc').BMCBatchImportResult | null>(null)

// Profile management
const showProfileDialog = ref(false)
const editingProfile = ref<BMCCredentialProfile | null>(null)
const savingProfile = ref(false)
const profileForm = reactive({ name: '', username: '', password: '' })

function editProfile(profile: BMCCredentialProfile) {
  editingProfile.value = profile
  profileForm.name = profile.name
  profileForm.username = profile.username
  profileForm.password = ''
  showProfileDialog.value = true
}

async function saveProfile() {
  savingProfile.value = true
  try {
    if (editingProfile.value) {
      await store.updateCredentialProfile(editingProfile.value.id, {
        name: profileForm.name,
        username: profileForm.username,
        password: profileForm.password || undefined,
      })
      ElMessage.success('Profile updated')
    } else {
      await store.createCredentialProfile({
        name: profileForm.name,
        username: profileForm.username,
        password: profileForm.password || undefined,
      })
      ElMessage.success('Profile created')
    }
    showProfileDialog.value = false
    editingProfile.value = null
    profileForm.name = ''
    profileForm.username = ''
    profileForm.password = ''
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || e.message || 'Failed')
  } finally {
    savingProfile.value = false
  }
}

async function confirmDeleteProfile(profile: BMCCredentialProfile) {
  try {
    await ElMessageBox.confirm(
      `Delete profile "${profile.name}"? This will unlink ${profile.server_count} server(s).`,
      'Confirm Delete',
      { confirmButtonText: 'Delete', cancelButtonText: 'Cancel', type: 'warning' }
    )
    await handleDeleteProfile(profile.id)
  } catch { /* cancelled */ }
}

async function handleDeleteProfile(id: number) {
  try {
    await store.deleteCredentialProfile(id)
    ElMessage.success('Profile deleted')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || e.message || 'Failed')
  }
}
const batchForm = reactive({
  ip_start: '',
  ip_end: '',
  ips: '',
  username: 'admin',
  password: '',
  credential_source: 'global',
  enabled: true,
})

// BMC Info query
const queryingId = ref<number | null>(null)

const blankForm = () => ({
  name: '',
  host: '',
  username: 'admin',
  password: '',
  credential_source: 'global',
  enabled: true,
  notes: '',
})

const serverForm = reactive(blankForm())

function editServer(server: BMCServer) {
  editingServer.value = server
  serverForm.name = server.name
  serverForm.host = server.host
  serverForm.username = server.username
  serverForm.password = ''
  if (server.credential_profile_id) {
    serverForm.credential_source = 'profile:' + server.credential_profile_id
  } else if (server.use_global_credentials) {
    serverForm.credential_source = 'global'
  } else {
    serverForm.credential_source = 'custom'
  }
  serverForm.enabled = server.enabled
  serverForm.notes = server.notes || ''
  showServerDialog.value = true
}

async function saveServer() {
  savingServer.value = true
  try {
    const payload: any = { ...serverForm }
    // Convert credential_source to backend fields
    const src = payload.credential_source
    if (src === 'global') {
      payload.use_global_credentials = true
      payload.credential_profile_id = null
    } else if (src && src.startsWith('profile:')) {
      payload.use_global_credentials = false
      payload.credential_profile_id = parseInt(src.split(':')[1])
    } else {
      payload.use_global_credentials = false
      payload.credential_profile_id = null
    }
    delete payload.credential_source

    if (editingServer.value) {
      await store.updateServer(editingServer.value.id, payload)
      ElMessage.success('Server updated')
    } else {
      await store.createServer(payload)
      ElMessage.success('Server created')
    }
    showServerDialog.value = false
    resetForm()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || e.message || 'Failed')
  } finally {
    savingServer.value = false
  }
}

async function confirmDelete(server: BMCServer) {
  try {
    await ElMessageBox.confirm(
      `Delete server "${server.name}" (${server.host})?`,
      'Confirm Delete',
      { confirmButtonText: 'Delete', cancelButtonText: 'Cancel', type: 'warning' }
    )
    await handleDelete(server.id)
  } catch { /* cancelled */ }
}

async function handleDelete(id: number) {
  try {
    await store.deleteServer(id)
    ElMessage.success('Server deleted')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || e.message || 'Failed')
  }
}

async function queryInfo(serverId: number) {
  queryingId.value = serverId
  try {
    const info = await bmcApi.queryBMCInfo(serverId)
    ElMessage.success(
      `SN: ${info.serial_number || 'N/A'}, BMC: ${info.bmc_firmware_version || 'N/A'}` +
      (info.product_name ? `, Product: ${info.product_name}` : '')
    )
    await refreshServers()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || e.message || 'Query failed')
  } finally {
    queryingId.value = null
  }
}

function handleSelectionChange(rows: BMCServer[]) {
  tableSelection.value = rows
}

async function bulkQueryInfo() {
  if (!tableSelection.value.length) return
  bulkQuerying.value = true
  const count = tableSelection.value.length
  // Fire all in parallel — the API returns immediately (background collection)
  const results = await Promise.allSettled(
    tableSelection.value.map(s => bmcApi.queryBMCInfo(s.id))
  )
  const ok = results.filter(r => r.status === 'fulfilled').length
  const fail = results.filter(r => r.status === 'rejected').length
  ElMessage.success(`BMC Info collection started: ${ok} OK, ${fail} failed (results appear within ~60s)`)
  tableSelection.value = []
  bulkQuerying.value = false
}

async function bulkDelete() {
  const count = tableSelection.value.length
  try {
    await ElMessageBox.confirm(
      `This will permanently delete ${count} server(s) from the database. All BMC reset history for these servers will also be removed. This action cannot be undone. Continue?`,
      'Bulk Delete — Irreversible',
      { confirmButtonText: `Delete ${count} Server(s)`, cancelButtonText: 'Cancel', type: 'error', confirmButtonClass: 'el-button--danger' }
    )
  } catch { return }

  bulkDeleting.value = true
  let ok = 0
  let fail = 0
  for (const server of tableSelection.value) {
    try {
      await store.deleteServer(server.id)
      ok++
    } catch {
      fail++
    }
  }
  ElMessage.success(`Deleted: ${ok} OK, ${fail} failed`)
  tableSelection.value = []
  await refreshServers()
  bulkDeleting.value = false
}

async function batchToggleEnabled(enabled: boolean) {
  const count = tableSelection.value.length
  const label = enabled ? 'Enable' : 'Disable'
  try {
    await ElMessageBox.confirm(
      `Set ${count} server(s) to Enabled = ${label}?`,
      `Batch ${label}`,
      { confirmButtonText: label, cancelButtonText: 'Cancel', type: 'info' }
    )
  } catch { return }

  batchToggling.value = true
  try {
    const ids = tableSelection.value.map(s => s.id)
    const result = await bmcApi.batchToggleEnabled(ids, enabled)
    ElMessage.success(result.message)
    tableSelection.value = []
    await refreshServers()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || e.message || 'Failed')
  } finally {
    batchToggling.value = false
  }
}

function exportCSV(verified: boolean) {
  const url = `${API_BASE_URL}/api/v1/bmc/export/${verified ? 'success' : 'failure'}`
  window.open(url, '_blank')
}

async function doBatchImport() {
  if (!batchForm.ips && (!batchForm.ip_start || !batchForm.ip_end)) {
    ElMessage.warning('Please enter an IP list or a start/end IP range')
    return
  }
  batchImporting.value = true
  batchResult.value = null
  try {
    const src = batchForm.credential_source
    const payload: any = {
      ips: batchForm.ips || undefined,
      ip_start: batchForm.ip_start || undefined,
      ip_end: batchForm.ip_end || undefined,
      username: batchForm.username,
      password: batchForm.password || undefined,
      use_global_credentials: src === 'global',
      credential_profile_id: (src && src.startsWith('profile:')) ? parseInt(src.split(':')[1]) : null,
      enabled: batchForm.enabled,
    }
    const result = await bmcApi.batchImportServers(payload)
    batchResult.value = result
    ElMessage.success(`Imported: ${result.created} created, ${result.skipped} skipped`)
    await refreshServers()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || e.message || 'Import failed')
  } finally {
    batchImporting.value = false
  }
}

function resetForm() {
  editingServer.value = null
  Object.assign(serverForm, blankForm())
}

async function refreshServers() {
  await store.loadServers({ skip: (serverPage.value - 1) * serverPageSize, limit: serverPageSize, verified: verifiedFilter.value, search: inventorySearch.value || undefined })
}

// ── Global Settings ─────────────────────────────────────────

const credsForm = reactive({ username: '', password: '' })
const savingCreds = ref(false)
const schedEnabled = ref(false)
const schedDay = ref(1)
const schedHour = ref(2)

async function loadSettings() {
  await store.loadGlobalCredentials()
  credsForm.username = store.globalCredentials.username
  credsForm.password = ''
}

async function saveGlobalCreds() {
  savingCreds.value = true
  try {
    await store.updateGlobalCredentials(credsForm.username, credsForm.password || undefined)
    credsForm.password = ''
    ElMessage.success('Credentials saved')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || e.message || 'Failed')
  } finally {
    savingCreds.value = false
  }
}

async function saveSchedule() {
  try {
    await Promise.all([
      bmcApi.updateScheduleSetting('bmc_monthly_reset_enabled', schedEnabled.value),
      bmcApi.updateScheduleSetting('bmc_monthly_reset_day', schedDay.value),
      bmcApi.updateScheduleSetting('bmc_monthly_reset_hour', schedHour.value),
    ])
    ElMessage.success('Schedule saved')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || e.message || 'Failed to save schedule')
  }
}

async function loadSchedule() {
  try {
    const sched = await bmcApi.getScheduleSettings()
    schedEnabled.value = sched.enabled
    schedDay.value = sched.day
    schedHour.value = sched.hour
  } catch {
    // keep defaults
  }
}

// ── Reset Execution ─────────────────────────────────────────

const selectedServers = ref<number[]>([])
const resetRunning = ref(false)
const errorLog = ref<{ time: string; server: string; host: string; category: string; message: string }[]>([])
const showErrorLog = ref(false)

const {
  resetStatus,
  connect: connectSSE,
  disconnect: disconnectSSE,
  loadInitialStatus,
} = useBMCResetMonitor({
  onStatus(status: BMCResetStatus) {
    if (!status.running && (status.current_phase === 'completed' || status.current_phase === 'error')) {
      resetRunning.value = false
      disconnectSSE()
      refreshServers()
      loadHistory()
      const failures = (status.results || []).filter(r => r.status === 'failure')
      if (failures.length > 0) {
        const ts = new Date().toLocaleString()
        errorLog.value = failures.map(r => ({
          time: ts, server: r.server_name, host: r.server_host,
          category: r.error_category || 'unknown', message: r.error_message || '',
        }))
        showErrorLog.value = true
      } else {
        errorLog.value = []
        showErrorLog.value = false
      }
    }
  },
})

async function startReset() {
  if (!selectedServers.value.length) return
  try {
    await ElMessageBox.confirm(
      `This will cold-reset the BMC on ${selectedServers.value.length} server(s). Continue?`,
      'Confirm BMC Cold Reset',
      { confirmButtonText: 'Reset', cancelButtonText: 'Cancel', type: 'warning' }
    )
  } catch {
    return
  }

  resetRunning.value = true
  try {
    const res = await bmcApi.startReset(selectedServers.value)
    ElMessage.success(res.message)
    await loadInitialStatus()
    connectSSE()
  } catch (e: any) {
    resetRunning.value = false
    ElMessage.error(e.response?.data?.detail || e.message || 'Failed')
  }
}

// ── History ─────────────────────────────────────────────────

const historyPage = ref(1)
const historyFilterStatus = ref<string>('')
const historyFilterServer = ref<number | ''>('')

async function loadHistory() {
  await store.loadHistory({
    status: historyFilterStatus.value || undefined,
    server_id: typeof historyFilterServer.value === 'number' ? historyFilterServer.value : undefined,
    skip: (historyPage.value - 1) * 50,
    limit: 50,
  })
}

// ── Utilities ───────────────────────────────────────────────

function formatDate(iso: string) {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleString()
}

// ── Init ────────────────────────────────────────────────────

onMounted(async () => {
  await Promise.all([refreshServers(), loadResetServers(), store.loadCredentialProfiles(), loadInitialStatus(), loadSettings(), loadSchedule()])
  if (resetStatus.value?.running) {
    resetRunning.value = true
    connectSSE()
  }
})
</script>

<style scoped>
.bmc-reset {
  max-width: 1600px;
}

.page-title {
  margin: 0 0 20px 0;
  font-size: 24px;
}

.toolbar {
  margin-bottom: 16px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.setting-card {
  margin-bottom: 20px;
  max-width: 700px;
}

.progress-card {
  margin-top: 20px;
}

.progress-body {
  padding: 10px 0;
}

.progress-stats {
  display: flex;
  gap: 24px;
  margin-top: 12px;
  font-size: 14px;
}

.current-server {
  margin-top: 8px;
  color: #606266;
  font-size: 13px;
}

.success-text { color: #67c23a; }
.failure-text { color: #f56c6c; }

.results-summary {
  margin-top: 10px;
}

.results-summary h4 {
  margin: 0 0 10px 0;
}

.error-preview {
  cursor: pointer;
  color: #909399;
  font-size: 13px;
}

.text-muted {
  color: #6b7280;
}

.pagination {
  margin-top: 16px;
  justify-content: flex-end;
}
</style>
