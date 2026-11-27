<template>
  <div class="switch-detail">
    <el-page-header @back="goBack">
      <template #title>
        <span style="font-size: 18px; font-weight: 600;">{{ switchInfo?.name || '交换机详情' }}</span>
      </template>
      <template #content>
        <div class="header-content" v-if="switchInfo">
          <el-tag :type="switchInfo.is_reachable ? 'success' : 'danger'">
            {{ switchInfo.is_reachable ? '在线' : '离线' }}
          </el-tag>
          <span class="switch-ip">{{ switchInfo.ip_address }}</span>
        </div>
      </template>
    </el-page-header>

    <!-- Loading State -->
    <el-card v-if="loading" class="info-card" v-loading="true" element-loading-text="加载中...">
      <div style="height: 200px;"></div>
    </el-card>

    <!-- Error State -->
    <el-card v-else-if="!switchInfo && !loading" class="info-card">
      <el-empty description="加载交换机信息失败">
        <el-button type="primary" @click="loadSwitchInfo">重新加载</el-button>
      </el-empty>
    </el-card>

    <!-- Switch Info Card -->
    <el-card v-else-if="switchInfo" class="info-card" shadow="hover">
      <template #header>
        <div class="card-header">
          <span class="section-title">交换机信息</span>
          <el-space wrap>
            <el-button
              type="primary"
              size="small"
              class="detail-action-button"
              @click="openEditDialog"
            >
              <template #icon><el-icon><Edit /></el-icon></template>
              编辑交换机
            </el-button>
            <el-button
              type="success"
              size="small"
              class="detail-action-button"
              @click="refreshDeviceInfo"
              :loading="deviceInfoLoading"
            >
              <template #icon><el-icon><Refresh /></el-icon></template>
              刷新设备信息
            </el-button>
            <el-button
              type="danger"
              size="small"
              class="detail-action-button"
              @click="handleDelete"
              :loading="deletingSwitch"
            >
              <template #icon><el-icon><Delete /></el-icon></template>
              删除交换机
            </el-button>
          </el-space>
        </div>
      </template>
      <el-descriptions :column="3" border size="default">
        <el-descriptions-item label="名称" label-class-name="desc-label">
          {{ switchInfo.name }}
        </el-descriptions-item>
        <el-descriptions-item label="IP地址" label-class-name="desc-label">
          {{ switchInfo.ip_address }}
        </el-descriptions-item>
        <el-descriptions-item label="厂商" label-class-name="desc-label">
          <el-tag type="info" size="small">{{ switchInfo.vendor?.toUpperCase() || 'Unknown' }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="型号" label-class-name="desc-label">
          {{ switchInfo.model || 'Unknown' }}
        </el-descriptions-item>
        <el-descriptions-item label="序列号" label-class-name="desc-label">
          {{ switchInfo.serial_number || '-' }}
        </el-descriptions-item>
        <el-descriptions-item label="角色" label-class-name="desc-label">
          <el-tag size="small" :type="getRoleType(switchInfo.role)">
            {{ getRoleLabel(switchInfo.role) }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="优先级" label-class-name="desc-label">
          <el-tag size="small" :type="getPriorityType(switchInfo.priority)">
            {{ switchInfo.priority }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="响应时间" label-class-name="desc-label">
          <span v-if="switchInfo.response_time_ms" style="color: #67c23a; font-weight: 500;">
            {{ switchInfo.response_time_ms.toFixed(2) }} ms
          </span>
          <span v-else style="color: #909399;">-</span>
        </el-descriptions-item>
        <el-descriptions-item label="最后检查" label-class-name="desc-label">
          {{ switchInfo.last_check_at ? formatDateTime(switchInfo.last_check_at) : '-' }}
        </el-descriptions-item>
        <el-descriptions-item label="SNMP" label-class-name="desc-label">
          <el-tag :type="switchInfo.snmp_enabled ? 'success' : 'info'" size="small">
            {{ switchInfo.snmp_enabled ? '已启用' : '未启用' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="SNMP 凭据来源" label-class-name="desc-label">
          <!--
            引用模板时把模板名摆出来。这一步很要紧：模板口令改了以后设备却毫无变化，
            先看这里是不是「本机自带」——没挂上模板的话，改模板当然不起作用。
          -->
          <el-tag v-if="switchInfo.snmp_profile_id" type="warning" size="small">
            模板：{{ switchInfo.snmp_profile_name || `#${switchInfo.snmp_profile_id}` }}
          </el-tag>
          <span v-else style="color: #909399;">本机自带</span>
        </el-descriptions-item>
        <el-descriptions-item label="最近采集状态" label-class-name="desc-label">
          <el-tag
            v-if="switchInfo.last_collection_status"
            :type="getCollectionStatusTag(switchInfo.last_collection_status)"
            size="small"
          >
            {{ switchInfo.last_collection_status }}
          </el-tag>
          <span v-else style="color: #909399;">-</span>
        </el-descriptions-item>
        <el-descriptions-item label="最近采集时间" label-class-name="desc-label">
          {{ getLatestCollectionTime(switchInfo) }}
        </el-descriptions-item>
        <el-descriptions-item label="上次成功采集" label-class-name="desc-label">
          <span v-if="switchInfo.last_successful_collection_at" style="color: #409eff; font-weight: 500;">
            {{ formatDateTime(switchInfo.last_successful_collection_at) }}
          </span>
          <span v-else style="color: #909399;">从未成功</span>
        </el-descriptions-item>
        <el-descriptions-item label="Trunk 人工识别" label-class-name="desc-label">
          <div class="trunk-review-status">
            <el-tag :type="switchInfo.trunk_review_completed ? 'success' : 'warning'" size="small">
              {{ switchInfo.trunk_review_completed ? '已完成' : '待处理' }}
            </el-tag>
            <span v-if="switchInfo.trunk_review_completed_at" class="trunk-review-time">
              {{ formatDateTime(switchInfo.trunk_review_completed_at) }}
            </span>
          </div>
        </el-descriptions-item>
      </el-descriptions>

      <el-alert
        v-if="switchInfo.last_collection_status"
        :title="`最近采集状态：${switchInfo.last_collection_status}`"
        :description="switchInfo.last_collection_message || '暂无详细说明'"
        :type="switchInfo.last_collection_status === 'success' ? 'success' : switchInfo.last_collection_status === 'failed' ? 'error' : 'warning'"
        :closable="false"
        show-icon
        style="margin-top: 16px;"
      />
    </el-card>

    <el-dialog
      v-model="showEditDialog"
      title="编辑交换机"
      width="680px"
      destroy-on-close
      @closed="resetSwitchForm"
    >
      <el-form
        ref="switchFormRef"
        :model="switchForm"
        :rules="switchRules"
        label-width="160px"
      >
        <el-form-item label="名称" prop="name">
          <el-input v-model="switchForm.name" placeholder="例如：Core-Switch-01" />
        </el-form-item>

        <el-form-item label="IP 地址" prop="ip_address">
          <el-input v-model="switchForm.ip_address" placeholder="例如：192.168.1.1" />
        </el-form-item>

        <el-form-item label="厂商" prop="vendor">
          <el-select v-model="switchForm.vendor" placeholder="选择厂商">
            <el-option label="Cisco" value="cisco" />
            <el-option label="Dell" value="dell" />
            <el-option label="Alcatel-Lucent" value="alcatel" />
            <el-option label="Juniper" value="juniper" />
            <el-option label="Arista" value="arista" />
            <el-option label="HPE" value="hpe" />
            <el-option label="Huawei" value="huawei" />
            <el-option label="H3C" value="h3c" />
            <el-option label="Fortinet" value="fortinet" />
            <el-option label="Extreme" value="extreme" />
            <el-option label="Aruba" value="aruba" />
            <el-option label="MikroTik" value="mikrotik" />
            <el-option label="Palo Alto" value="paloalto" />
            <el-option label="其他" value="other" />
          </el-select>
        </el-form-item>

        <el-form-item label="型号" prop="model">
          <el-input v-model="switchForm.model" placeholder="例如：WS-C4506" />
        </el-form-item>

        <el-divider content-position="left">CLI 配置</el-divider>

        <el-form-item label="启用 CLI" prop="cli_enabled">
          <el-switch v-model="switchForm.cli_enabled" />
          <span class="edit-form-tip">启用后可通过 SSH 或 Telnet 执行命令</span>
        </el-form-item>

        <template v-if="switchForm.cli_enabled">
          <el-form-item label="CLI 协议" prop="cli_transport">
            <el-select v-model="switchForm.cli_transport" style="width: 180px">
              <el-option label="SSH" value="ssh" />
              <el-option label="Telnet" value="telnet" />
            </el-select>
          </el-form-item>

          <el-form-item label="CLI 端口" prop="ssh_port">
            <el-input-number v-model="switchForm.ssh_port" :min="1" :max="65535" />
          </el-form-item>

          <el-form-item label="CLI 用户名" prop="username">
            <el-input v-model="switchForm.username" placeholder="请输入 CLI 用户名" />
          </el-form-item>

          <el-form-item label="CLI 密码" prop="password">
            <el-input
              v-model="switchForm.password"
              type="password"
              placeholder="留空则保持当前密码不变"
              show-password
            />
            <div class="edit-form-tip">
              当前已配置密码时可留空，不会覆盖现有 CLI 密码。
            </div>
          </el-form-item>

          <el-form-item label="Enable 密码" prop="enable_password">
            <el-input
              v-model="switchForm.enable_password"
              type="password"
              placeholder="可选，留空则不修改"
              show-password
            />
          </el-form-item>

          <el-form-item label="连接超时" prop="connection_timeout">
            <el-input-number v-model="switchForm.connection_timeout" :min="5" :max="300" />
          </el-form-item>
        </template>

        <el-divider content-position="left">数据收集设置</el-divider>

        <el-form-item label="自动收集 ARP" prop="auto_collect_arp">
          <el-switch v-model="switchForm.auto_collect_arp" />
        </el-form-item>

        <el-form-item label="自动收集 MAC" prop="auto_collect_mac">
          <el-switch v-model="switchForm.auto_collect_mac" />
        </el-form-item>

        <el-form-item label="启用设备" prop="enabled">
          <el-switch v-model="switchForm.enabled" />
        </el-form-item>

        <el-divider content-position="left">SNMP 配置</el-divider>

        <el-form-item label="启用 SNMP" prop="snmp_enabled">
          <el-switch v-model="switchForm.snmp_enabled" />
        </el-form-item>

        <template v-if="switchForm.snmp_enabled">
          <el-form-item label="凭据来源" prop="snmp_profile_id">
            <el-select
              v-model="switchForm.snmp_profile_id"
              placeholder="本机自带（不引用模板）"
              style="width: 100%"
            >
              <el-option label="本机自带（不引用模板）" :value="null" />
              <el-option
                v-for="p in snmpProfileStore.enabledProfiles()"
                :key="p.id"
                :label="`模板：${p.name}（${p.version} · ${p.auth_protocol || '—'} / ${p.priv_protocol || '—'}）`"
                :value="p.id"
              />
            </el-select>
            <div class="edit-form-tip">
              选中模板后，本机的用户名、协议、口令都不再使用，凭据整体以模板为准；
              以后改口令只改模板一处，所有引用它的交换机同时生效。
            </div>
          </el-form-item>

          <el-alert
            v-if="switchForm.snmp_profile_id"
            type="info"
            :closable="false"
            show-icon
            style="margin-bottom: 18px;"
          >
            <template #title>
              凭据取自模板「{{ snmpProfileStore.byId(switchForm.snmp_profile_id)?.name }}」，
              用户名、协议、口令都在模板上维护。改回「本机自带」并保存即可解绑。
            </template>
          </el-alert>

          <el-form-item label="SNMP 版本" prop="snmp_version">
            <el-radio-group v-model="switchForm.snmp_version">
              <el-radio label="3">SNMPv3</el-radio>
              <el-radio label="2c">SNMPv2c</el-radio>
            </el-radio-group>
          </el-form-item>

          <!--
            引用模板时整段隐藏：这些字段后端本来就不读，留在界面上只会让人以为
            「这里填的还算数」，改了没效果反而更难排查。
          -->
          <template v-if="!switchForm.snmp_profile_id">
          <template v-if="switchForm.snmp_version === '3'">
            <el-form-item label="SNMP 用户名" prop="snmp_username">
              <el-input v-model="switchForm.snmp_username" placeholder="请输入 SNMP 用户名" />
            </el-form-item>

            <el-form-item label="认证协议" prop="snmp_auth_protocol">
              <el-select v-model="switchForm.snmp_auth_protocol">
                <el-option label="MD5" value="MD5" />
                <el-option label="SHA" value="SHA" />
                <el-option label="SHA-224" value="SHA-224" />
                <el-option label="SHA-256" value="SHA-256" />
                <el-option label="SHA-384" value="SHA-384" />
                <el-option label="SHA-512" value="SHA-512" />
              </el-select>
            </el-form-item>

            <el-form-item label="认证密码" prop="snmp_auth_password">
              <el-input
                v-model="switchForm.snmp_auth_password"
                type="password"
                placeholder="新设备必填；编辑时留空则保持不变"
                show-password
              />
              <div class="edit-form-tip">
                已配置 SNMPv3 认证密码时可留空，不会覆盖现有配置。
              </div>
            </el-form-item>

            <el-form-item label="加密协议" prop="snmp_priv_protocol">
              <el-select v-model="switchForm.snmp_priv_protocol">
                <el-option label="DES" value="DES" />
                <el-option label="AES-128" value="AES-128" />
                <el-option label="AES-192" value="AES-192" />
                <el-option label="AES-256" value="AES-256" />
              </el-select>
            </el-form-item>

            <el-form-item label="加密密码（可选）" prop="snmp_priv_password">
              <el-input
                v-model="switchForm.snmp_priv_password"
                type="password"
                placeholder="留空则保持现有配置，或继续使用仅认证模式"
                show-password
              />
              <div class="edit-form-tip">
                当前支持仅认证不加密的 SNMPv3；若设备原来已配加密，留空不会覆盖现有加密密码。
              </div>
            </el-form-item>
          </template>

          <template v-else>
            <el-form-item label="Community" prop="snmp_community">
              <el-input
                v-model="switchForm.snmp_community"
                placeholder="新设备必填；编辑现有 v2c 设备时留空则保持不变"
              />
              <div class="edit-form-tip">
                SNMPv2c 不加密，建议仅在可信网络环境中使用。
              </div>
            </el-form-item>
          </template>
          </template>

          <el-form-item label="SNMP 端口" prop="snmp_port">
            <el-input-number v-model="switchForm.snmp_port" :min="1" :max="65535" />
          </el-form-item>
        </template>
      </el-form>

      <template #footer>
        <el-button @click="closeEditDialog">取消</el-button>
        <el-button type="primary" :loading="savingSwitch" @click="saveSwitch">
          保存修改
        </el-button>
      </template>
    </el-dialog>

    <!-- Data Tabs -->
    <el-tabs v-model="activeTab" class="data-tabs">
      <el-tab-pane label="ARP 表" name="arp">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span class="section-title">ARP 表 ({{ arpData.length }} 条记录)</span>
              <div class="card-header-actions">
                <el-button type="success" size="small" @click="exportArpData('excel')" :loading="arpExportLoading">
                  导出Excel
                </el-button>
                <el-button type="info" size="small" @click="exportArpData('csv')" :loading="arpExportLoading">
                  导出CSV
                </el-button>
                <el-button type="primary" size="small" class="detail-action-button" @click="collectArpData" :loading="arpLoading">
                  <template #icon><el-icon><Refresh /></el-icon></template>
                  立即收集
                </el-button>
              </div>
            </div>
          </template>

          <el-alert
            v-if="arpData.length === 0 && !arpLoading"
            title="暂无数据"
            type="info"
            description="系统每10分钟自动采集一次ARP数据，请稍后刷新查看。"
            :closable="false"
            show-icon
            style="margin-bottom: 20px;"
          />

          <el-table 
            v-if="arpData.length > 0" 
            :data="filteredArpData" 
            stripe 
            style="width: 100%" 
            :default-sort="{ prop: 'last_seen', order: 'descending' }"
            border
          >
            <el-table-column prop="ip_address" label="IP 地址" width="150" sortable>
              <template #default="{ row }">
                <el-link type="primary" @click="searchIP(row.ip_address)" underline="never">
                  {{ row.ip_address }}
                </el-link>
              </template>
            </el-table-column>
            <el-table-column prop="mac_address" label="MAC 地址" width="180" sortable />
            <el-table-column prop="vlan_id" label="VLAN" width="100" sortable align="center" />
            <el-table-column prop="interface" label="接口" width="150" sortable />
            <el-table-column prop="age_seconds" label="Age (秒)" width="120" sortable align="center" />
            <el-table-column prop="last_seen" label="最后发现时间" sortable min-width="180">
              <template #default="{ row }">
                {{ formatDateTime(row.last_seen) }}
              </template>
            </el-table-column>
          </el-table>

          <el-pagination
            v-if="arpData.length > pageSize"
            v-model:current-page="arpCurrentPage"
            :page-size="pageSize"
            layout="total, prev, pager, next"
            :total="arpData.length"
            style="margin-top: 20px; justify-content: center"
          />
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="MAC 地址表" name="mac">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span class="section-title">MAC 地址表 ({{ macData.length }} 条记录)</span>
              <div class="card-header-actions">
                <el-button type="success" size="small" @click="exportMacData('excel')" :loading="macExportLoading">
                  导出Excel
                </el-button>
                <el-button type="info" size="small" @click="exportMacData('csv')" :loading="macExportLoading">
                  导出CSV
                </el-button>
                <el-button type="primary" size="small" class="detail-action-button" @click="collectMacData" :loading="macLoading">
                  <template #icon><el-icon><Refresh /></el-icon></template>
                  立即收集
                </el-button>
              </div>
            </div>
          </template>

          <el-alert
            v-if="macData.length === 0 && !macLoading"
            title="暂无数据"
            type="info"
            description="系统每10分钟自动采集一次MAC地址表数据，请稍后刷新查看。"
            :closable="false"
            show-icon
            style="margin-bottom: 20px;"
          />

          <el-table 
            v-if="macData.length > 0" 
            :data="filteredMacData" 
            stripe 
            style="width: 100%" 
            :default-sort="{ prop: 'last_seen', order: 'descending' }"
            border
          >
            <el-table-column prop="mac_address" label="MAC 地址" width="180" sortable />
            <el-table-column prop="port_name" label="端口" width="150" sortable />
            <el-table-column prop="vlan_id" label="VLAN" width="100" sortable align="center" />
            <el-table-column prop="is_dynamic" label="类型" width="100" align="center">
              <template #default="{ row }">
                <el-tag :type="row.is_dynamic ? 'success' : 'warning'" size="small">
                  {{ row.is_dynamic ? '动态' : '静态' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="last_seen" label="最后发现时间" sortable min-width="180">
              <template #default="{ row }">
                {{ formatDateTime(row.last_seen) }}
              </template>
            </el-table-column>
          </el-table>

          <el-pagination
            v-if="macData.length > pageSize"
            v-model:current-page="macCurrentPage"
            :page-size="pageSize"
            layout="total, prev, pager, next"
            :total="macData.length"
            style="margin-top: 20px; justify-content: center"
          />
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="端口策略" name="port-policy">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <div class="port-policy-header">
                <span class="section-title">端口定位策略</span>
                <el-tag v-if="portAnalysisSummary" type="success" size="small">
                  可参与定位 {{ portAnalysisSummary.lookup_included_ports }}/{{ portAnalysisSummary.total_ports }}
                </el-tag>
                <el-tag
                  v-if="switchInfo"
                  :type="switchInfo.trunk_review_completed ? 'success' : 'warning'"
                  effect="dark"
                >
                  {{ switchInfo.trunk_review_completed ? '人工识别已完成' : '人工识别待处理' }}
                </el-tag>
                <el-button
                  v-if="switchInfo && !switchInfo.trunk_review_completed"
                  type="success"
                  size="small"
                  class="detail-action-button"
                  :loading="trunkReviewUpdating"
                  @click="setTrunkReview(true)"
                >
                  标记已完成
                </el-button>
                <el-button
                  v-else-if="switchInfo"
                  type="info"
                  size="small"
                  class="detail-action-button"
                  :loading="trunkReviewUpdating"
                  @click="setTrunkReview(false)"
                >
                  取消完成标记
                </el-button>
              </div>
              <el-space>
                <el-button
                  type="primary"
                  size="small"
                  class="detail-action-button"
                  @click="loadPortAnalysis"
                  :loading="portPolicyLoading"
                >
                  <template #icon><el-icon><Refresh /></el-icon></template>
                  刷新策略
                </el-button>
                <el-button
                  type="warning"
                  size="small"
                  class="detail-action-button"
                  @click="analyzePorts"
                  :loading="portAnalyzing"
                >
                  重新分析端口
                </el-button>
              </el-space>
            </div>
          </template>

          <el-alert
            v-if="portAnalysisFreshness?.warning"
            :title="portAnalysisFreshness.status === 'stale' ? '当前显示的是历史端口分析' : '端口分析状态提示'"
            :description="portAnalysisAlertDescription"
            :type="portAnalysisFreshness.status === 'stale' ? 'warning' : 'info'"
            :closable="false"
            show-icon
            style="margin-bottom: 20px;"
          />

          <el-alert
            v-if="portAnalysisData.length === 0 && !portPolicyLoading"
            title="暂无端口分析数据"
            type="info"
            description="请先执行一次端口分析。系统会基于 MAC 表生成端口分析，然后你可以人工设置某些端口强制参与或排除定位。"
            :closable="false"
            show-icon
            style="margin-bottom: 20px;"
          />

          <div v-if="portAnalysisSummary" class="policy-summary">
            <el-tag type="info">Access {{ portAnalysisSummary.access_ports }}</el-tag>
            <el-tag type="warning">Trunk {{ portAnalysisSummary.trunk_ports }}</el-tag>
            <el-tag type="danger">Uplink {{ portAnalysisSummary.uplink_ports }}</el-tag>
            <el-tag type="info">Unknown {{ portAnalysisSummary.unknown_ports }}</el-tag>
            <el-tag type="success">Lookup Included {{ portAnalysisSummary.lookup_included_ports }}</el-tag>
            <el-tag type="danger">Lookup Excluded {{ portAnalysisSummary.lookup_excluded_ports }}</el-tag>
          </div>

          <el-table
            v-if="portAnalysisData.length > 0"
            :data="portAnalysisData"
            stripe
            border
            style="width: 100%"
            :default-sort="{ prop: 'port_name', order: 'ascending' }"
          >
            <el-table-column prop="port_name" label="端口" min-width="160" sortable />
            <el-table-column prop="mac_count" label="MAC 数" width="90" sortable align="center" />
            <el-table-column prop="unique_vlans" label="VLAN 数" width="100" sortable align="center" />
            <el-table-column prop="port_type" label="自动判定" width="120" sortable align="center">
              <template #default="{ row }">
                <el-tag :type="getPortTypeTag(row.port_type)" size="small">
                  {{ getPortTypeLabel(row.port_type) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="lookup_policy_override" label="人工覆盖" width="120" align="center">
              <template #default="{ row }">
                <el-tag v-if="row.lookup_policy_override" :type="row.lookup_policy_override === 'include' ? 'success' : 'danger'" size="small">
                  {{ row.lookup_policy_override === 'include' ? '强制包含' : '强制排除' }}
                </el-tag>
                <span v-else style="color: #909399;">自动</span>
              </template>
            </el-table-column>
            <el-table-column prop="effective_lookup_status" label="生效结果" width="120" align="center">
              <template #default="{ row }">
                <el-tag :type="getLookupStatusTag(row.effective_lookup_status)" size="small">
                  {{ row.effective_lookup_status === 'included' ? '参与定位' : '排除定位' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="effective_lookup_reason" label="生效原因" min-width="160" show-overflow-tooltip />
            <el-table-column prop="analyzed_at" label="分析时间" min-width="180" sortable>
              <template #default="{ row }">
                {{ formatDateTime(row.analyzed_at) }}
              </template>
            </el-table-column>
            <el-table-column label="操作" min-width="240" fixed="right">
              <template #default="{ row }">
                <el-space wrap>
                  <el-button
                    size="small"
                    type="success"
                    class="detail-table-button"
                    :disabled="row.lookup_policy_override === 'include'"
                    :loading="portPolicyUpdatingPort === row.port_name"
                    @click="setPortLookupPolicy(row, 'include')"
                  >
                    强制包含
                  </el-button>
                  <el-button
                    size="small"
                    type="danger"
                    class="detail-table-button"
                    :disabled="row.lookup_policy_override === 'exclude'"
                    :loading="portPolicyUpdatingPort === row.port_name"
                    @click="setPortLookupPolicy(row, 'exclude')"
                  >
                    强制排除
                  </el-button>
                  <el-button
                    size="small"
                    type="info"
                    class="detail-table-button"
                    :disabled="!row.lookup_policy_override"
                    :loading="portPolicyUpdatingPort === row.port_name"
                    @click="setPortLookupPolicy(row, null)"
                  >
                    清除覆盖
                  </el-button>
                </el-space>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="光模块" name="optical">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span class="section-title">
                光模块信息
                (当前 {{ opticalPresentCount }} / 历史 {{ opticalHistoricalCount }} / 总计 {{ opticalData.length }})
              </span>
              <el-button type="primary" size="small" class="detail-action-button" @click="collectOpticalData" :loading="opticalLoading">
                <template #icon><el-icon><Refresh /></el-icon></template>
                立即收集
              </el-button>
            </div>
          </template>

          <el-alert
            v-if="opticalFreshness?.warning"
            :title="opticalFreshness.status === 'stale' ? '光模块库存为历史视图' : '光模块库存提示'"
            :type="opticalFreshness.status === 'stale' ? 'warning' : 'info'"
            :description="opticalFreshnessAlertDescription"
            :closable="false"
            show-icon
            style="margin-bottom: 20px;"
          />

          <el-alert
            v-if="opticalData.length === 0 && !opticalLoading"
            title="暂无数据"
            type="info"
            :description="opticalEmptyDescription"
            :closable="false"
            show-icon
            style="margin-bottom: 20px;"
          />

          <el-table
            v-if="opticalData.length > 0"
            :data="filteredOpticalData"
            stripe
            style="width: 100%"
            :default-sort="{ prop: 'port_name', order: 'ascending' }"
            border
          >
            <el-table-column prop="port_name" label="端口" width="150" sortable />
            <el-table-column prop="presence_status" label="状态" width="110" sortable>
              <template #default="{ row }">
                <el-tag :type="row.is_present ? 'success' : 'warning'" size="small">
                  {{ row.is_present ? '当前存在' : '历史缓存' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="module_type" label="模块类型" width="120" sortable>
              <template #default="{ row }">
                <el-tag
                  :type="getModuleTagType(row.module_type)"
                  size="small"
                >
                  {{ row.module_type || 'Unknown' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="vendor" label="厂商" width="150" sortable show-overflow-tooltip />
            <el-table-column prop="model" label="型号" width="180" sortable show-overflow-tooltip />
            <el-table-column prop="serial_number" label="序列号" width="180" sortable show-overflow-tooltip />
            <el-table-column prop="speed_gbps" label="速率" width="100" sortable align="center">
              <template #default="{ row }">
                <span v-if="row.speed_gbps">{{ row.speed_gbps }} Gbps</span>
                <span v-else style="color: #999;">-</span>
              </template>
            </el-table-column>
            <el-table-column prop="last_seen" label="最近确认时间" sortable min-width="180">
              <template #default="{ row }">
                {{ formatDateTime(row.last_seen) }}
              </template>
            </el-table-column>
            <el-table-column prop="first_seen" label="首次发现" sortable min-width="180">
              <template #default="{ row }">
                {{ formatDateTime(row.first_seen) }}
              </template>
            </el-table-column>
          </el-table>

          <el-pagination
            v-if="opticalData.length > pageSize"
            v-model:current-page="opticalCurrentPage"
            :page-size="pageSize"
            layout="total, prev, pager, next"
            :total="opticalData.length"
            style="margin-top: 20px; justify-content: center"
          />
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="端口清单" name="interfaces">
        <el-card>
          <template #header>
            <div class="card-header">
              <span class="section-title">端口清单 ({{ topologyInterfaces.length }} 个端口)</span>
              <el-text type="info" size="small">闲置时长仅对「链路非 up」的端口计算（当前时间 - ifLastChange，含 admin 禁用的端口）；up 端口为使用中，不计闲置</el-text>
            </div>
          </template>
          <el-empty
            v-if="!topologyInterfaces.length && !topologyLoading"
            description="该交换机暂无接口采集数据，请先到「邻居 / 拓扑」页执行采集"
            :image-size="60"
          />
          <el-table v-else :data="topologyInterfaces" stripe border size="small" v-loading="topologyLoading">
            <el-table-column label="接口" min-width="150">
              <template #default="{ row }">
                {{ row.if_name || row.if_descr || row.if_index }}
              </template>
            </el-table-column>
            <el-table-column prop="if_alias" label="描述" min-width="140" />
            <el-table-column label="状态" width="120">
              <template #default="{ row }">
                {{ row.admin_status || '-' }} / {{ row.oper_status || '-' }}
              </template>
            </el-table-column>
            <el-table-column label="对端设备" min-width="150">
              <template #default="{ row }">
                <el-tooltip
                  v-if="portDeviceOf(row) && portDeviceOf(row)!.port_device"
                  :content="portDeviceTooltip(portDeviceOf(row)!)"
                  placement="top"
                >
                  <el-tag :type="portDeviceTagType(portDeviceOf(row)!)" effect="dark" size="small">
                    {{ portDeviceLabel(portDeviceOf(row)!) }}
                  </el-tag>
                </el-tooltip>
                <span v-else class="port-device-empty">-</span>
              </template>
            </el-table-column>
            <el-table-column prop="speed_mbps" label="速率(Mbps)" width="110" />
            <el-table-column prop="last_change_at" label="最后变更" min-width="170" sortable>
              <template #default="{ row }">
                {{ formatDateTime(row.last_change_at) }}
              </template>
            </el-table-column>
            <el-table-column prop="last_change_at" label="闲置时长" width="110">
              <template #default="{ row }">
                {{ formatIdleDuration(row) }}
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="邻居 / 拓扑" name="topology">
        <el-card>
          <template #header>
            <div class="card-header">
              <div class="card-header-actions">
                <span>LLDP / CDP 邻居与接口</span>
                <el-tag
                  v-if="switchInfo?.last_topology_collection_status"
                  :type="topologyStatusTagType"
                  size="small"
                >
                  {{ switchInfo.last_topology_collection_status }}
                  <template v-if="switchInfo.last_topology_neighbors_count != null">
                    （{{ switchInfo.last_topology_neighbors_count }} 条邻居）
                  </template>
                </el-tag>
              </div>
              <el-tooltip :content="authStore.isLoggedIn ? '采集该交换机的接口与邻居' : '访客只读，请登录后采集'" placement="top">
                <span>
                  <el-button
                    type="primary"
                    size="small"
                    class="detail-action-button"
                    :loading="topologyCollecting"
                    :disabled="!authStore.isLoggedIn"
                    @click="collectTopologyData"
                  >
                    <template #icon><el-icon><Refresh /></el-icon></template>
                    采集拓扑
                  </el-button>
                </span>
              </el-tooltip>
            </div>
          </template>

          <el-alert
            v-if="switchInfo?.last_topology_collection_message && switchInfo.last_topology_collection_status !== 'success'"
            :title="switchInfo.last_topology_collection_message"
            type="warning"
            :closable="false"
            show-icon
            style="margin-bottom: 20px;"
          />

          <el-tabs v-model="topologyTab">
            <el-tab-pane label="链路" name="links">
              <el-empty v-if="!topologyLinks.length && !topologyLoading" description="暂无链路，请先采集拓扑" :image-size="60" />
              <el-table v-else :data="topologyLinks" stripe border size="small" v-loading="topologyLoading">
                <el-table-column label="状态" width="150">
                  <template #default="{ row }">
                    <el-tag :type="linkStatusTagType(row.status)" size="small">{{ row.status }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="confidence" label="置信度" width="90" />
                <el-table-column label="本端端口" min-width="160">
                  <template #default="{ row }">{{ localPortName(row) || '-' }}</template>
                </el-table-column>
                <el-table-column label="对端" min-width="220">
                  <template #default="{ row }">
                    {{ remoteLabel(row) }}
                    <el-text type="info" size="small">{{ remotePortName(row) || '-' }}</el-text>
                  </template>
                </el-table-column>
                <el-table-column prop="evidence" label="证据" width="110" />
              </el-table>
            </el-tab-pane>

            <el-tab-pane label="邻居" name="neighbors">
              <el-empty v-if="!topologyNeighbors.length && !topologyLoading" description="该交换机暂无已采集的邻居" :image-size="60" />
              <el-table v-else :data="topologyNeighbors" stripe border size="small" v-loading="topologyLoading">
                <el-table-column prop="protocol" label="协议" width="80" />
                <el-table-column label="本端" min-width="150">
                  <template #default="{ row }">
                    {{ row.local_port_id || row.local_port_desc || row.local_if_index }}
                  </template>
                </el-table-column>
                <el-table-column label="远端" min-width="200">
                  <template #default="{ row }">
                    {{ row.remote_sys_name || row.remote_chassis_id || '-' }}
                    <el-text type="info" size="small">{{ row.remote_port_id || row.remote_port_desc || '-' }}</el-text>
                  </template>
                </el-table-column>
                <el-table-column prop="remote_mgmt_addr" label="远端管理 IP" width="150" />
              </el-table>
            </el-tab-pane>

          </el-tabs>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="配置备份" name="backup">
        <el-card shadow="never">
          <template #header>
            <div class="backup-header">
              <span>配置备份（只读抓取 running-config）</span>
              <el-button size="small" :loading="backupLoading" @click="loadBackupData">
                <template #icon><el-icon><Refresh /></el-icon></template>
                刷新
              </el-button>
            </div>
          </template>

          <template v-if="backupOverview">
            <el-alert
              v-if="!backupOverview.supported"
              type="warning"
              :closable="false"
              show-icon
              :title="backupOverview.unsupported_reason || '暂不支持该厂商的配置备份，可在配置备份模块中手动指定驱动和命令'"
              style="margin-bottom: 12px;"
            />
            <el-descriptions :column="3" border size="small" style="margin-bottom: 12px;">
              <el-descriptions-item label="备份状态">
                <el-tag :type="backupStatusType(backupOverview.status)" size="small">{{ backupStatusText(backupOverview.status) }}</el-tag>
                <div v-if="backupOverview.message" class="backup-msg">{{ backupOverview.message }}</div>
              </el-descriptions-item>
              <el-descriptions-item label="上次备份">{{ formatBackupTime(backupOverview.last_backup_at) }}</el-descriptions-item>
              <el-descriptions-item label="上次成功">{{ formatBackupTime(backupOverview.last_success_at) }}</el-descriptions-item>
              <el-descriptions-item label="版本数">{{ backupOverview.version_count }}</el-descriptions-item>
              <el-descriptions-item label="配置大小">{{ formatBackupBytes(backupOverview.last_success_size) }}</el-descriptions-item>
              <el-descriptions-item label="备份间隔">
                {{ backupOverview.interval_minutes }} 分钟（{{ backupOverview.backup_interval_minutes ? '单台设置' : '全局默认' }}）
              </el-descriptions-item>
            </el-descriptions>

            <div class="backup-actions">
              <el-tooltip :content="backupRunTooltip" placement="top">
                <span>
                  <el-button
                    type="primary"
                    size="small"
                    :loading="backupRunning"
                    :disabled="!canBackupNow"
                    @click="handleBackupNow"
                  >
                    立即备份
                  </el-button>
                </span>
              </el-tooltip>
              <el-button size="small" :disabled="!backupOverview.last_success_id" @click="openBackupContent(backupOverview.last_success_id)">
                查看最新配置
              </el-button>
              <el-button size="small" :disabled="!backupOverview.last_success_id" @click="downloadBackupLatest">
                下载最新
              </el-button>
              <router-link to="/config-backups" class="backup-link">在「配置备份」模块中管理 →</router-link>
            </div>

            <el-table :data="backupHistory" size="small" stripe v-loading="backupLoading" empty-text="暂无备份记录">
              <el-table-column label="开始时间" min-width="160">
                <template #default="{ row }">{{ formatBackupTime(row.started_at) }}</template>
              </el-table-column>
              <el-table-column label="状态" width="90">
                <template #default="{ row }">
                  <el-tag :type="backupStatusType(row.status)" size="small">{{ backupStatusText(row.status) }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="触发" width="80">
                <template #default="{ row }">{{ row.trigger_source === 'manual' ? '手动' : '定时' }}</template>
              </el-table-column>
              <el-table-column label="大小" width="90">
                <template #default="{ row }">{{ formatBackupBytes(row.size_bytes) }}</template>
              </el-table-column>
              <el-table-column label="耗时" width="90">
                <template #default="{ row }">{{ row.duration_ms != null ? `${(row.duration_ms / 1000).toFixed(1)} s` : '—' }}</template>
              </el-table-column>
              <el-table-column label="说明" min-width="200" show-overflow-tooltip>
                <template #default="{ row }">{{ row.message || '—' }}</template>
              </el-table-column>
              <el-table-column label="操作" width="190" fixed="right">
                <template #default="{ row }">
                  <el-button link size="small" :disabled="!row.sha256" @click="openBackupContent(row.id)">查看</el-button>
                  <el-button link size="small" :disabled="!row.sha256" @click="downloadBackupRecord(row.id)">下载</el-button>
                  <el-button link size="small" :disabled="!previousSuccessId(row)" @click="openBackupDiff(row)">对比</el-button>
                </template>
              </el-table-column>
            </el-table>
          </template>
          <el-empty v-else-if="!backupLoading" description="暂无备份信息" :image-size="60" />
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="backupContentVisible" :title="backupContentTitle" width="1000px" destroy-on-close>
      <div v-loading="backupContentLoading">
        <div v-if="backupContentMeta" class="backup-content-meta">
          <el-tag size="small" effect="plain">#{{ backupContentMeta.id }}</el-tag>
          <span>{{ formatBackupTime(backupContentMeta.started_at) }}</span>
          <span>{{ formatBackupBytes(backupContentMeta.size_bytes) }}</span>
          <el-button link type="primary" size="small" @click="downloadBackupRecord(backupContentMeta.id)">下载</el-button>
        </div>
        <pre class="backup-config-content">{{ backupContent || '（空）' }}</pre>
      </div>
    </el-dialog>

    <el-dialog v-model="backupDiffVisible" title="配置版本对比" width="1100px" destroy-on-close>
      <el-alert
        v-if="backupDiffResult?.truncated"
        type="warning"
        :closable="false"
        show-icon
        title="差异过大已截断显示"
        style="margin-bottom: 8px;"
      />
      <div v-loading="backupDiffLoading" class="backup-diff-box">
        <div v-if="!backupDiffResult" class="backup-diff-empty">加载中…</div>
        <div v-else-if="!backupDiffLines.length" class="backup-diff-empty">两个版本内容完全一致</div>
        <pre v-else class="backup-diff-content"><div v-for="line in backupDiffLines" :key="line.key" :class="line.cls">{{ line.text || ' ' }}</div></pre>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed, reactive, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { Delete, Edit, Refresh } from '@element-plus/icons-vue'
import apiClient from '@/api'
import {
  switchesApi,
  type OpticalInventoryFreshness,
  type OpticalModuleEntry,
  type PortAnalysisEntry,
  type PortAnalysisResponse,
  type SwitchCreate,
  type Switch,
} from '@/api/switches'
// 凭据模板列表：编辑对话框的「凭据来源」下拉要用。与新增/批量配置共用同一份缓存。
import { useSNMPProfilesStore } from '@/stores/snmpProfiles'
import { useAuthStore } from '@/stores/auth'
import {
  collectTopology,
  getSwitchPortDevices,
  getTopologyGraph,
  getTopologyInterfaces,
  getTopologyNeighbors,
  type SwitchPortDevice,
  type TopologyInterface,
  type TopologyLink,
  type TopologyNeighbor,
} from '@/api/topology'
import {
  downloadBackup,
  fetchBackupContent,
  fetchBackupDiff,
  fetchBackupHistory,
  fetchBackupOverview,
  runBackupNow,
} from '@/api/configBackups'
import type {
  BackupDiffResponse,
  BackupOverviewItem,
  BackupRecord,
  BackupStatus,
  BackupVersionContent,
} from '@/api/configBackups'

const route = useRoute()
const router = useRouter()

const snmpProfileStore = useSNMPProfilesStore()
const authStore = useAuthStore()

const switchId = ref(Number(route.params.id))
const switchInfo = ref<Switch | null>(null)
const activeTab = ref('arp')
const loading = ref(true)
const deviceInfoLoading = ref(false)
const showEditDialog = ref(false)
const savingSwitch = ref(false)
const deletingSwitch = ref(false)
const switchFormRef = ref<FormInstance>()

const arpData = ref<any[]>([])
const macData = ref<any[]>([])
const opticalData = ref<OpticalModuleEntry[]>([])
const opticalFreshness = ref<OpticalInventoryFreshness | null>(null)
const opticalPresentCount = ref(0)
const opticalHistoricalCount = ref(0)
const portAnalysisData = ref<PortAnalysisEntry[]>([])
const portAnalysisSummary = ref<PortAnalysisResponse['summary'] | null>(null)
const portAnalysisFreshness = ref<PortAnalysisResponse['freshness'] | null>(null)
const arpLoading = ref(false)
const macLoading = ref(false)
const arpExportLoading = ref(false)
const macExportLoading = ref(false)
const opticalLoading = ref(false)
const portPolicyLoading = ref(false)
const portAnalyzing = ref(false)
const portPolicyUpdatingPort = ref<string | null>(null)
const trunkReviewUpdating = ref(false)

// 邻居 / 拓扑页签：按需加载，避免详情页一进来就打三份拓扑请求。
const topologyTab = ref('links')
const topologyLoading = ref(false)
const topologyCollecting = ref(false)
const topologyNeighbors = ref<TopologyNeighbor[]>([])
const topologyInterfaces = ref<TopologyInterface[]>([])
const topologyLinks = ref<TopologyLink[]>([])
// 端口 ↔ 对端设备（后端统一判定，避免前端重复实现分类规则）
const topologyPortDevices = ref<SwitchPortDevice[]>([])

const arpCurrentPage = ref(1)
const macCurrentPage = ref(1)
const opticalCurrentPage = ref(1)
const pageSize = ref(50)

const defaultCliPort = (transport?: 'ssh' | 'telnet') => transport === 'telnet' ? 23 : 22

const switchForm = reactive<SwitchCreate>({
  name: '',
  ip_address: '',
  vendor: 'cisco',
  model: '',
  enabled: true,
  cli_enabled: false,
  cli_transport: 'ssh',
  ssh_port: 22,
  username: '',
  password: '',
  enable_password: '',
  connection_timeout: 30,
  auto_collect_arp: true,
  auto_collect_mac: true,
  auto_collect_topology: true,
  snmp_enabled: true,
  snmp_version: '3',
  snmp_port: 161,
  // null = 本机自带凭据，不引用模板。
  snmp_profile_id: null,
  snmp_username: '',
  snmp_auth_protocol: 'SHA',
  snmp_auth_password: '',
  snmp_priv_protocol: 'AES128',
  snmp_priv_password: '',
  snmp_community: ''
})

const switchRules: FormRules = {
  name: [{ required: true, message: '请输入交换机名称', trigger: 'blur' }],
  ip_address: [{ required: true, message: '请输入 IP 地址', trigger: 'blur' }],
  vendor: [{ required: true, message: '请选择厂商', trigger: 'change' }],
  username: [
    {
      validator: (_rule, value, callback) => {
        if (switchForm.cli_enabled && !value) {
          callback(new Error('启用 CLI 时必须填写用户名'))
          return
        }
        callback()
      },
      trigger: 'blur'
    }
  ],
  password: [
    {
      validator: (_rule, value, callback) => {
        if (switchForm.cli_enabled && !value && !switchInfo.value?.cli_enabled) {
          callback(new Error('新启用 CLI 时必须填写密码'))
          return
        }
        callback()
      },
      trigger: 'blur'
    }
  ],
  snmp_username: [
    {
      validator: (_rule, value, callback) => {
        // 引用模板时用户名在模板上，这里不校验；否则隐藏的必填项会拦住提交。
        if (switchForm.snmp_profile_id) {
          callback()
          return
        }
        if (switchForm.snmp_enabled && switchForm.snmp_version === '3' && !value) {
          callback(new Error('SNMPv3 必须填写用户名'))
          return
        }
        callback()
      },
      trigger: 'blur'
    }
  ],
  snmp_auth_password: [
    {
      validator: (_rule, value, callback) => {
        if (switchForm.snmp_profile_id) {
          callback()
          return
        }
        if (
          switchForm.snmp_enabled &&
          switchForm.snmp_version === '3' &&
          !value &&
          switchInfo.value?.snmp_version !== '3'
        ) {
          callback(new Error('新启用 SNMPv3 时必须填写认证密码'))
          return
        }
        if (value && value.length < 8) {
          callback(new Error('SNMPv3 认证密码至少 8 位字符'))
          return
        }
        callback()
      },
      trigger: 'blur'
    }
  ],
  snmp_priv_password: [
    {
      validator: (_rule, value, callback) => {
        if (value && value.length < 8) {
          callback(new Error('SNMPv3 加密密码至少 8 位字符'))
          return
        }
        callback()
      },
      trigger: 'blur'
    }
  ],
  snmp_community: [
    {
      validator: (_rule, value, callback) => {
        if (switchForm.snmp_profile_id) {
          callback()
          return
        }
        if (
          switchForm.snmp_enabled &&
          switchForm.snmp_version === '2c' &&
          !value &&
          switchInfo.value?.snmp_version !== '2c'
        ) {
          callback(new Error('新启用 SNMPv2c 时必须填写 Community'))
          return
        }
        callback()
      },
      trigger: 'blur'
    }
  ]
}

watch(
  () => switchForm.cli_transport,
  (newTransport, oldTransport) => {
    const previousDefaultPort = defaultCliPort(oldTransport)
    if (
      switchForm.ssh_port === undefined ||
      switchForm.ssh_port === null ||
      switchForm.ssh_port === previousDefaultPort
    ) {
      switchForm.ssh_port = defaultCliPort(newTransport)
    }
  }
)

watch(
  () => switchForm.snmp_version,
  (newVersion) => {
    if (newVersion === '3') {
      switchForm.snmp_community = ''
      return
    }

    switchForm.snmp_username = ''
    switchForm.snmp_auth_password = ''
    switchForm.snmp_priv_password = ''
  }
)

const filteredArpData = computed(() => {
  const start = (arpCurrentPage.value - 1) * pageSize.value
  const end = start + pageSize.value
  return arpData.value.slice(start, end)
})

const filteredMacData = computed(() => {
  const start = (macCurrentPage.value - 1) * pageSize.value
  const end = start + pageSize.value
  return macData.value.slice(start, end)
})

const filteredOpticalData = computed(() => {
  const start = (opticalCurrentPage.value - 1) * pageSize.value
  const end = start + pageSize.value
  return opticalData.value.slice(start, end)
})

const goBack = () => {
  router.push('/switches')
}

const formatDateTime = (dateStr?: string | null) => {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
}

// 端口闲置时长：除「链路 up」外的端口都算闲置（admin down 同样是闲置，只是被人为关闭）。
// 闲置时长 = 现在 - ifLastChange；up 端口正在使用，不显示时长。
const formatIdleDuration = (row: TopologyInterface) => {
  const oper = (row.oper_status || '').toLowerCase()
  if (oper === 'up') return '使用中'
  if (!row.last_change_at) return '-'
  const ms = Date.now() - new Date(row.last_change_at).getTime()
  if (!Number.isFinite(ms) || ms < 0) return '-'
  const days = Math.floor(ms / 86400000)
  if (days >= 1) return `${days} 天`
  const hours = Math.floor(ms / 3600000)
  if (hours >= 1) return `${hours} 小时`
  return `${Math.floor(ms / 60000)} 分钟`
}

const getRoleType = (role?: string) => {
  const types: Record<string, any> = {
    core: 'danger',
    aggregation: 'warning',
    access: 'info'
  }
  return role ? types[role] || 'info' : 'info'
}

const getRoleLabel = (role?: string) => {
  const labels: Record<string, string> = {
    core: 'Core',
    aggregation: 'Aggregation',
    access: 'Access'
  }
  return role ? labels[role] || role : 'Unknown'
}

const getModuleTagType = (moduleType: string) => {
  if (!moduleType) return 'info'
  if (moduleType === 'QSFP28') return 'danger'
  if (moduleType === 'QSFP+' || moduleType === 'QSFP') return 'warning'
  return 'success'
}

const getPriorityType = (priority?: number) => {
  if (priority === undefined || priority === null) return 'info'
  if (priority <= 10) return 'danger'
  if (priority <= 50) return 'warning'
  return 'info'
}

const getPortTypeTag = (portType: PortAnalysisEntry['port_type']) => {
  const types: Record<PortAnalysisEntry['port_type'], string> = {
    access: 'success',
    trunk: 'warning',
    uplink: 'danger',
    unknown: 'info'
  }
  return types[portType] || 'info'
}

const getPortTypeLabel = (portType: PortAnalysisEntry['port_type']) => {
  const labels: Record<PortAnalysisEntry['port_type'], string> = {
    access: 'Access',
    trunk: 'Trunk',
    uplink: 'Uplink',
    unknown: 'Unknown'
  }
  return labels[portType] || portType
}

const getLookupStatusTag = (status: PortAnalysisEntry['effective_lookup_status']) => {
  return status === 'included' ? 'success' : 'danger'
}

const getCollectionStatusTag = (status?: string | null) => {
  if (status === 'success') return 'success'
  if (status === 'failed') return 'danger'
  return 'warning'
}

const getLatestCollectionTime = (switchData?: Switch | null) => {
  if (!switchData) return '-'

  const timestamps = [
    switchData.last_arp_collection_at,
    switchData.last_mac_collection_at,
    switchData.last_optical_collection_at
  ]
    .filter((value): value is string => Boolean(value))
    .map(value => new Date(value).getTime())
    .filter(value => !Number.isNaN(value))

  if (timestamps.length === 0) return '-'
  return formatDateTime(new Date(Math.max(...timestamps)).toISOString())
}

const portAnalysisAlertDescription = computed(() => {
  if (!portAnalysisFreshness.value?.warning) return ''

  const parts = [portAnalysisFreshness.value.warning]

  if (portAnalysisFreshness.value.last_analyzed_at) {
    parts.push(`最近成功分析时间：${formatDateTime(portAnalysisFreshness.value.last_analyzed_at)}`)
  }

  if (portAnalysisFreshness.value.last_collection_attempt_at) {
    parts.push(`最近采集尝试：${formatDateTime(portAnalysisFreshness.value.last_collection_attempt_at)}`)
  }

  if (portAnalysisFreshness.value.last_collection_message) {
    parts.push(`最近采集说明：${portAnalysisFreshness.value.last_collection_message}`)
  }

  return parts.join(' ')
})

const opticalFreshnessAlertDescription = computed(() => {
  if (!opticalFreshness.value?.warning) return ''

  const parts = [opticalFreshness.value.warning]

  if (opticalFreshness.value.last_optical_success_at) {
    parts.push(`最近成功时间：${formatDateTime(opticalFreshness.value.last_optical_success_at)}`)
  }

  if (opticalFreshness.value.last_optical_collection_at) {
    parts.push(`最近尝试时间：${formatDateTime(opticalFreshness.value.last_optical_collection_at)}`)
  }

  if (opticalFreshness.value.last_optical_collection_message) {
    parts.push(`最近说明：${opticalFreshness.value.last_optical_collection_message}`)
  }

  return parts.join(' ')
})

const opticalEmptyDescription = computed(() => {
  if (opticalFreshness.value?.last_optical_collection_status === 'empty') {
    return '最近一次光模块采集已确认该交换机当前没有检测到光模块，系统会保留历史缓存用于追踪。'
  }

  if (opticalFreshness.value?.last_optical_collection_status === 'failed') {
    return '最近一次光模块采集失败，当前没有可展示的成功快照。请检查交换机连通性或采集方式。'
  }

  return '点击【立即收集】按钮采集光模块信息。系统现在会保留历史缓存，并明确标记历史/当前状态。'
})

const searchIP = (ip: string) => {
  router.push(`/?ip=${ip}`)
}

const resetSwitchForm = () => {
  Object.assign(switchForm, {
    name: '',
    ip_address: '',
    vendor: 'cisco',
    model: '',
    enabled: true,
    cli_enabled: false,
    cli_transport: 'ssh',
    ssh_port: 22,
    username: '',
    password: '',
    enable_password: '',
    connection_timeout: 30,
    auto_collect_arp: true,
    auto_collect_mac: true,
    auto_collect_topology: true,
    snmp_enabled: true,
    snmp_version: '3',
    snmp_port: 161,
    snmp_profile_id: null,
    snmp_username: '',
    snmp_auth_protocol: 'SHA',
    snmp_auth_password: '',
    snmp_priv_protocol: 'AES128',
    snmp_priv_password: '',
    snmp_community: ''
  })
  switchFormRef.value?.clearValidate()
}

const openEditDialog = async () => {
  if (!switchInfo.value) return

  // 先备好模板列表再开框：下拉框否则会先空一下再冒出来。
  // store 有缓存，来回开关对话框也只请求一次。
  await snmpProfileStore.load()

  Object.assign(switchForm, {
    name: switchInfo.value.name,
    ip_address: switchInfo.value.ip_address,
    vendor: switchInfo.value.vendor,
    model: switchInfo.value.model || '',
    enabled: switchInfo.value.enabled,
    cli_enabled: switchInfo.value.cli_enabled || false,
    cli_transport: switchInfo.value.cli_transport || 'ssh',
    ssh_port: switchInfo.value.ssh_port ?? defaultCliPort(switchInfo.value.cli_transport || 'ssh'),
    username: switchInfo.value.username || '',
    password: '',
    enable_password: '',
    connection_timeout: switchInfo.value.connection_timeout || 30,
    auto_collect_arp: switchInfo.value.auto_collect_arp ?? true,
    auto_collect_mac: switchInfo.value.auto_collect_mac ?? true,
    auto_collect_topology: switchInfo.value.auto_collect_topology ?? true,
    snmp_enabled: switchInfo.value.snmp_enabled || false,
    snmp_version: switchInfo.value.snmp_version || '3',
    snmp_port: switchInfo.value.snmp_port || 161,
    snmp_profile_id: switchInfo.value.snmp_profile_id ?? null,
    snmp_username: switchInfo.value.snmp_username || '',
    snmp_auth_protocol: switchInfo.value.snmp_auth_protocol || 'SHA',
    snmp_auth_password: '',
    snmp_priv_protocol: switchInfo.value.snmp_priv_protocol || 'AES128',
    snmp_priv_password: '',
    snmp_community: ''
  })

  showEditDialog.value = true
  switchFormRef.value?.clearValidate()
}

const closeEditDialog = () => {
  showEditDialog.value = false
  resetSwitchForm()
}

const saveSwitch = async () => {
  if (!switchInfo.value || !switchFormRef.value) return

  try {
    await switchFormRef.value.validate()
  } catch {
    return
  }

  savingSwitch.value = true
  try {
    const updateData: Record<string, unknown> = {}

    Object.entries(switchForm).forEach(([key, value]) => {
      if (typeof value === 'boolean') {
        updateData[key] = value
        return
      }

      if (value !== '' && value !== null && value !== undefined) {
        updateData[key] = value
      }
    })

    // snmp_profile_id 必须显式带上，null 也要带：上面的循环把 null 当「空值」
    // 丢掉了，而后端把「字段不在请求里」解释成「不改动现有绑定」，两者语义相反。
    // 少了这一行，界面上就永远解不了绑（选回「本机自带」保存后还是挂着模板）。
    updateData.snmp_profile_id = switchForm.snmp_profile_id ?? null

    const updatedSwitch = await switchesApi.update(switchInfo.value.id, updateData)
    switchInfo.value = updatedSwitch
    ElMessage.success('交换机信息已更新')
    closeEditDialog()
  } catch (error: any) {
    console.error('Failed to save switch:', error)
    ElMessage.error(error.response?.data?.detail || '保存交换机信息失败')
  } finally {
    savingSwitch.value = false
  }
}

const handleDelete = async () => {
  if (!switchInfo.value) return

  try {
    await ElMessageBox.confirm(
      `确定要删除交换机「${switchInfo.value.name}」吗？此操作不可撤销。`,
      '删除交换机',
      {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning',
        confirmButtonClass: 'el-button--danger'
      }
    )
  } catch {
    return // 用户取消
  }

  deletingSwitch.value = true
  try {
    await switchesApi.delete(switchInfo.value.id)
    ElMessage.success('交换机已删除')
    router.push('/switches')
  } catch (error: any) {
    console.error('Failed to delete switch:', error)
    ElMessage.error(error.response?.data?.detail || '删除交换机失败')
  } finally {
    deletingSwitch.value = false
  }
}

const loadSwitchInfo = async () => {
  loading.value = true
  try {
    const response = await apiClient.get(`/api/v1/switches/${switchId.value}`)
    switchInfo.value = response.data
    console.log('Switch info loaded:', response.data)
  } catch (error: any) {
    console.error('Failed to load switch info:', error)
    ElMessage.error(error.response?.data?.detail || '加载交换机信息失败')
  } finally {
    loading.value = false
  }
}

const loadArpData = async () => {
  arpLoading.value = true
  try {
    console.log(`正在加载交换机 ${switchId.value} 的ARP表...`)
    const response = await apiClient.get(`/api/v1/switches/${switchId.value}/arp`)
    console.log('ARP表响应:', response.data)
    arpData.value = response.data.entries || []
    if (arpData.value.length > 0) {
      ElMessage.success(`刷新成功：加载了 ${arpData.value.length} 条 ARP 记录`)
    } else {
      ElMessage.info('刷新成功：当前暂无 ARP 记录，系统每10分钟自动采集一次数据')
    }
  } catch (error: any) {
    console.error('Failed to load ARP data:', error)
    ElMessage.error(error.response?.data?.detail || '加载ARP表失败')
  } finally {
    arpLoading.value = false
  }
}

const loadMacData = async () => {
  macLoading.value = true
  try {
    console.log(`正在加载交换机 ${switchId.value} 的MAC表...`)
    const response = await apiClient.get(`/api/v1/switches/${switchId.value}/mac`)
    console.log('MAC表响应:', response.data)
    macData.value = response.data.entries || []
    if (macData.value.length > 0) {
      ElMessage.success(`刷新成功：加载了 ${macData.value.length} 条 MAC 记录`)
    } else {
      ElMessage.info('刷新成功：当前暂无 MAC 记录，系统每10分钟自动采集一次数据')
    }
  } catch (error: any) {
    console.error('Failed to load MAC data:', error)
    ElMessage.error(error.response?.data?.detail || '加载MAC表失败')
  } finally {
    macLoading.value = false
  }
}

// Manual collection functions
const collectArpData = async () => {
  arpLoading.value = true
  try {
    ElMessage.info('正在实时收集 ARP 表数据，请稍候...')
    const response = await switchesApi.collectArp(switchId.value)
    console.log('ARP collection response:', response)

    if (response.total_entries > 0) {
      ElMessage.success(`✅ ${response.message}`)
      // Reload data from database
      await loadArpData()
    } else {
      ElMessage.warning(response.message || '未能收集到 ARP 数据')
    }
  } catch (error: any) {
    console.error('Failed to collect ARP data:', error)
    ElMessage.error(error.response?.data?.detail || '收集 ARP 表失败')
  } finally {
    arpLoading.value = false
  }
}

const collectMacData = async () => {
  macLoading.value = true
  try {
    ElMessage.info('正在实时收集 MAC 地址表数据，请稍候...')
    const response = await switchesApi.collectMac(switchId.value)
    console.log('MAC collection response:', response)

    if (response.total_entries > 0) {
      ElMessage.success(`✅ ${response.message}`)
      // Reload data from database
      await loadMacData()
    } else {
      ElMessage.warning(response.message || '未能收集到 MAC 数据')
    }
  } catch (error: any) {
    console.error('Failed to collect MAC data:', error)
    ElMessage.error(error.response?.data?.detail || '收集 MAC 地址表失败')
  } finally {
    macLoading.value = false
  }
}

// Export functions
const exportArpData = async (format: 'excel' | 'csv') => {
  if (arpExportLoading.value) return
  arpExportLoading.value = true
  try {
    ElMessage.info('正在导出 ARP 表...')
    const { exportToExcel, exportToCSV } = await import('@/utils/export')
    const data = await switchesApi.exportArp()
    if (!data || data.length === 0) {
      ElMessage.warning('没有 ARP 数据可导出')
      return
    }
    const filename = `ARP表_所有交换机_${new Date().toISOString().slice(0, 10)}`
    if (format === 'excel') {
      await exportToExcel(data, filename, 'ARP表')
    } else {
      exportToCSV(data, filename)
    }
    ElMessage.success(`成功导出 ${data.length} 条 ARP 记录`)
  } catch (error: any) {
    console.error('Failed to export ARP data:', error)
    ElMessage.error(error.response?.data?.detail || '导出 ARP 表失败')
  } finally {
    arpExportLoading.value = false
  }
}

const exportMacData = async (format: 'excel' | 'csv') => {
  if (macExportLoading.value) return
  macExportLoading.value = true
  try {
    ElMessage.info('正在导出 MAC 表...')
    const { exportToExcel, exportToCSV } = await import('@/utils/export')
    const data = await switchesApi.exportMac()
    if (!data || data.length === 0) {
      ElMessage.warning('没有 MAC 数据可导出')
      return
    }
    const filename = `MAC表_所有交换机_${new Date().toISOString().slice(0, 10)}`
    if (format === 'excel') {
      await exportToExcel(data, filename, 'MAC表')
    } else {
      exportToCSV(data, filename)
    }
    ElMessage.success(`成功导出 ${data.length} 条 MAC 记录`)
  } catch (error: any) {
    console.error('Failed to export MAC data:', error)
    ElMessage.error(error.response?.data?.detail || '导出 MAC 表失败')
  } finally {
    macExportLoading.value = false
  }
}

const loadOpticalData = async () => {
  opticalLoading.value = true
  try {
    const response = await switchesApi.getOpticalModules(switchId.value)
    opticalData.value = response.entries || []
    opticalFreshness.value = response.freshness || null
    opticalPresentCount.value = response.present_modules || 0
    opticalHistoricalCount.value = response.historical_modules || 0
    console.log('Loaded optical modules:', opticalData.value.length)
  } catch (error: any) {
    console.error('Failed to load optical modules:', error)
    if (error.response?.status !== 404) {
      ElMessage.error('加载光模块信息失败')
    }
  } finally {
    opticalLoading.value = false
  }
}

const loadPortAnalysis = async () => {
  portPolicyLoading.value = true
  try {
    const response = await switchesApi.getPortAnalysis(switchId.value)
    portAnalysisData.value = response.ports || []
    portAnalysisSummary.value = response.summary || null
    portAnalysisFreshness.value = response.freshness || null
  } catch (error: any) {
    portAnalysisData.value = []
    portAnalysisSummary.value = null
    portAnalysisFreshness.value = null

    if (error.response?.status !== 404) {
      console.error('Failed to load port analysis:', error)
      ElMessage.error(error.response?.data?.detail || '加载端口策略失败')
    }
  } finally {
    portPolicyLoading.value = false
  }
}

const analyzePorts = async () => {
  portAnalyzing.value = true
  try {
    ElMessage.info('正在采集最新 MAC 表并分析端口，请稍候...')
    const response = await switchesApi.analyzePorts(switchId.value)
    if (response.success) {
      ElMessage.success(response.message || '端口分析完成')
      await loadPortAnalysis()
    } else {
      ElMessage.warning(response.message || '端口分析未产生结果')
    }
  } catch (error: any) {
    console.error('Failed to analyze ports:', error)
    ElMessage.error(error.response?.data?.detail || '端口分析失败')
  } finally {
    portAnalyzing.value = false
  }
}

const setPortLookupPolicy = async (
  row: PortAnalysisEntry,
  lookupPolicyOverride: 'include' | 'exclude' | null
) => {
  portPolicyUpdatingPort.value = row.port_name
  try {
    await switchesApi.updatePortLookupPolicy(switchId.value, {
      port_name: row.port_name,
      lookup_policy_override: lookupPolicyOverride
    })

    const actionText = lookupPolicyOverride === 'include'
      ? '已强制包含'
      : lookupPolicyOverride === 'exclude'
        ? '已强制排除'
        : '已清除覆盖'

    ElMessage.success(`${row.port_name} ${actionText}`)
    await loadPortAnalysis()
    await loadMacData()
  } catch (error: any) {
    console.error('Failed to update port lookup policy:', error)
    ElMessage.error(error.response?.data?.detail || '更新端口策略失败')
  } finally {
    portPolicyUpdatingPort.value = null
  }
}

const collectOpticalData = async () => {
  opticalLoading.value = true
  try {
    ElMessage.info('正在按当前策略采集光模块信息，请稍候...')
    const response = await switchesApi.collectOpticalModules(switchId.value)
    console.log('Optical module collection response:', response)

    if (response.collection_status === 'success') {
      ElMessage.success(`✅ ${response.message}`)
    } else if (response.collection_status === 'empty') {
      ElMessage.info(response.message || '本次采集确认当前无光模块，历史缓存已保留')
    } else {
      ElMessage.warning(response.message || '未能收集到光模块信息')
    }

    await loadOpticalData()
    await loadSwitchInfo()
  } catch (error: any) {
    console.error('Failed to collect optical modules:', error)
    ElMessage.error(error.response?.data?.detail || '收集光模块信息失败')
  } finally {
    opticalLoading.value = false
  }
}

// 采集是异步队列任务，入队后延迟刷新一次，省得用户手动点刷新。
const TOPOLOGY_REFRESH_DELAY_MS = 6000

const topologyStatusTagType = computed(() => {
  switch (switchInfo.value?.last_topology_collection_status) {
    case 'success':
      return 'success'
    case 'partial':
      return 'warning'
    case 'unsupported':
      return 'info'
    case 'failed':
      return 'danger'
    default:
      return 'info'
  }
})

const linkStatusTagType = (status: string) => {
  switch (status) {
    case 'confirmed':
      return 'success'
    case 'one_sided':
      return 'warning'
    case 'unresolved':
      return 'danger'
    default:
      return 'info'
  }
}

// 对端设备（后端统一判定）：if_index 在同一交换机内唯一，直接按索引关联。
const portDeviceOf = (row: TopologyInterface) =>
  topologyPortDevices.value.find((item) => item.if_index === row.if_index)

const PORT_DEVICE_LABEL: Record<string, string> = {
  switch: '交换机',
  router: '路由器',
  'wlan-ap': '无线 AP',
  hub: '集线器',
  phone: 'IP 话机',
  host: 'PC / 服务器',
  unknown: '未识别'
}

const portDeviceLabel = (device: SwitchPortDevice) =>
  PORT_DEVICE_LABEL[device.port_device_class || ''] || '未识别'

const portDeviceTagType = (device: SwitchPortDevice) => {
  const cls = device.port_device_class
  if (cls === 'switch' || cls === 'router') return 'success'
  if (cls === 'hub' || cls === 'wlan-ap') return 'warning'
  return 'info'
}

const portDeviceTooltip = (device: SwitchPortDevice) => {
  const info = device.port_device
  if (!info) return '无邻居信息'
  const parts = [`置信度 ${info.confidence}%`]
  if (info.sys_name) parts.push(`名称 ${info.sys_name}`)
  if (info.reasons?.length) parts.push(info.reasons.join('；'))
  if (device.status === 'multiple') parts.push(`该端口有 ${device.candidates} 个邻居`)
  return parts.join(' · ')
}

const isLocalA = (link: TopologyLink) => link.a_switch_id === switchId.value
const localPortName = (link: TopologyLink) => (isLocalA(link) ? link.a_port_name : link.b_port_name)
const remotePortName = (link: TopologyLink) => (isLocalA(link) ? link.b_port_name : link.a_port_name)
const remoteLabel = (link: TopologyLink) => {
  const label = isLocalA(link) ? link.b_sys_name || link.b_mgmt_ip : link.a_sys_name || link.a_mgmt_ip
  return label || '未知节点'
}

const loadTopologyData = async () => {
  topologyLoading.value = true
  try {
    const [neighborRes, interfaceRes, graphRes, portDeviceRes] = await Promise.all([
      getTopologyNeighbors({ switch_id: switchId.value, limit: 1000 }),
      getTopologyInterfaces({ switch_id: switchId.value, limit: 2000 }),
      getTopologyGraph({ focus_switch_id: switchId.value, depth: 1 }),
      // 端口设备联动失败不应拖垮整页拓扑，单独兜底为空。
      getSwitchPortDevices(switchId.value).catch(() => ({ data: [] as SwitchPortDevice[] }))
    ])
    topologyNeighbors.value = neighborRes.data || []
    topologyInterfaces.value = interfaceRes.data || []
    topologyPortDevices.value = portDeviceRes.data || []
    topologyLinks.value = (graphRes.data.links || []).filter(
      (link) => link.a_switch_id === switchId.value || link.b_switch_id === switchId.value
    )
  } catch (error: any) {
    console.error('Failed to load topology data:', error)
    ElMessage.error(error.response?.data?.detail || '加载拓扑数据失败')
  } finally {
    topologyLoading.value = false
  }
}

const collectTopologyData = async () => {
  if (!authStore.isLoggedIn) {
    ElMessage.warning('访客只读，请先登录再采集拓扑')
    return
  }
  topologyCollecting.value = true
  try {
    const { data } = await collectTopology([switchId.value])
    if (data.queued > 0) {
      ElMessage.success('已入队采集，稍后自动刷新')
      window.setTimeout(async () => {
        await loadTopologyData()
        await loadSwitchInfo()
      }, TOPOLOGY_REFRESH_DELAY_MS)
    } else {
      ElMessage.info(data.message || '该交换机未启用或未开启自动拓扑')
    }
  } catch (error: any) {
    console.error('Failed to collect topology:', error)
    ElMessage.error(error.response?.data?.detail || '采集拓扑失败')
  } finally {
    topologyCollecting.value = false
  }
}

// ---------- 配置备份 ----------
const BACKUP_STATUS_META: Record<BackupStatus, { text: string; type: 'info' | 'primary' | 'success' | 'danger' | 'warning' }> = {
  never: { text: '未备份', type: 'info' },
  running: { text: '备份中', type: 'primary' },
  success: { text: '成功', type: 'success' },
  failed: { text: '失败', type: 'danger' },
  unsupported: { text: '不支持', type: 'info' },
  skipped: { text: '已跳过', type: 'warning' },
}

const backupLoading = ref(false)
const backupRunning = ref(false)
const backupOverview = ref<BackupOverviewItem | null>(null)
const backupHistory = ref<BackupRecord[]>([])
const backupSuccessVersions = ref<BackupRecord[]>([])
const backupContentVisible = ref(false)
const backupContentLoading = ref(false)
const backupContent = ref('')
const backupContentMeta = ref<BackupVersionContent | null>(null)
const backupDiffVisible = ref(false)
const backupDiffLoading = ref(false)
const backupDiffResult = ref<BackupDiffResponse | null>(null)

const backupStatusText = (status: string) => BACKUP_STATUS_META[status as BackupStatus]?.text || status
const backupStatusType = (status: string) => BACKUP_STATUS_META[status as BackupStatus]?.type || 'info'

const formatBackupTime = (value: string | null | undefined) => {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

const formatBackupBytes = (value: number | null | undefined) => {
  if (value == null) return '—'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(2)} MB`
}

const canBackupNow = computed(() =>
  !!backupOverview.value &&
  authStore.isLoggedIn &&
  backupOverview.value.enabled &&
  backupOverview.value.backup_enabled &&
  backupOverview.value.supported
)

const backupRunTooltip = computed(() => {
  if (!authStore.isLoggedIn) return '访客只读，请登录后备份'
  if (!backupOverview.value) return '暂无备份信息'
  if (!backupOverview.value.enabled) return '交换机已停用'
  if (!backupOverview.value.backup_enabled) return '该交换机已关闭自动备份'
  if (!backupOverview.value.supported) return backupOverview.value.unsupported_reason || '缺少可用驱动或命令'
  return '立即执行一次只读备份'
})

const loadBackupData = async () => {
  backupLoading.value = true
  try {
    const [overviewData, historyData, successData] = await Promise.all([
      fetchBackupOverview(),
      fetchBackupHistory(switchId.value, { page: 1, page_size: 20 }),
      fetchBackupHistory(switchId.value, { page: 1, page_size: 100, status: 'success' }),
    ])
    backupOverview.value = overviewData.items.find(item => item.switch_id === switchId.value) || null
    backupHistory.value = historyData.items
    backupSuccessVersions.value = successData.items
  } catch {
    // apiClient 已统一提示错误
  } finally {
    backupLoading.value = false
  }
}

const handleBackupNow = async () => {
  backupRunning.value = true
  try {
    const result = await runBackupNow(switchId.value)
    if (result.status === 'success') {
      ElMessage.success(result.message || '备份成功')
    } else {
      ElMessage.warning(result.message || `备份未成功（${result.status}）`)
    }
    await loadBackupData()
  } catch {
    // apiClient 已统一提示错误
  } finally {
    backupRunning.value = false
  }
}

const backupContentTitle = computed(() =>
  backupContentMeta.value ? `配置内容 #${backupContentMeta.value.id}` : '配置内容'
)

const openBackupContent = async (backupId: number | null) => {
  if (!backupId) return
  backupContentVisible.value = true
  backupContentLoading.value = true
  backupContent.value = ''
  backupContentMeta.value = null
  try {
    const data = await fetchBackupContent(backupId)
    backupContentMeta.value = data
    backupContent.value = data.content
  } catch {
    backupContentVisible.value = false
  } finally {
    backupContentLoading.value = false
  }
}

const downloadBackupRecord = async (backupId: number) => {
  try {
    await downloadBackup(backupId, `${switchInfo.value?.name || 'switch'}.cfg`)
  } catch {
    ElMessage.error('下载失败，请稍后重试')
  }
}

const downloadBackupLatest = () => {
  const id = backupOverview.value?.last_success_id
  if (id) void downloadBackupRecord(id)
}

// 同一交换机的成功版本按时间倒序，取当前行之后的下一条即为更早的成功版本
const previousSuccessId = (row: BackupRecord) => {
  const index = backupSuccessVersions.value.findIndex(item => item.id === row.id)
  if (index < 0) return null
  const previous = backupSuccessVersions.value[index + 1]
  return previous ? previous.id : null
}

const openBackupDiff = async (row: BackupRecord) => {
  const fromId = previousSuccessId(row)
  if (!fromId) return
  backupDiffVisible.value = true
  backupDiffLoading.value = true
  backupDiffResult.value = null
  try {
    backupDiffResult.value = await fetchBackupDiff(fromId, row.id)
  } catch {
    // apiClient 已统一提示错误
  } finally {
    backupDiffLoading.value = false
  }
}

const backupDiffLines = computed(() => {
  if (!backupDiffResult.value) return []
  return backupDiffResult.value.diff.split('\n').map((text, index) => {
    let cls = 'backup-diff-line'
    if (text.startsWith('+++') || text.startsWith('---')) {
      cls += ' diff-meta'
    } else if (text.startsWith('@@')) {
      cls += ' diff-hunk'
    } else if (text.startsWith('+')) {
      cls += ' diff-add'
    } else if (text.startsWith('-')) {
      cls += ' diff-del'
    }
    return { text, cls, key: index }
  })
})

// 页签首次切到「端口清单 / 邻居 / 拓扑 / 配置备份」时才真正发请求。
watch(activeTab, (tab) => {
  if (tab === 'topology' || tab === 'interfaces') loadTopologyData()
  if (tab === 'backup' && !backupOverview.value) loadBackupData()
})

const refreshDeviceInfo = async () => {
  deviceInfoLoading.value = true
  try {
    ElMessage.info('正在实时获取设备信息，请稍候...')
    const response = await switchesApi.collectDeviceInfo(switchId.value)
    console.log('Device info collection response:', response)

    if (response.success) {
      if (response.updated_fields.length > 0) {
        ElMessage.success(`✅ ${response.message}`)
        // Reload switch info
        await loadSwitchInfo()
      } else {
        ElMessage.info(response.message || '设备信息无变化')
      }
    } else {
      ElMessage.warning(response.message || '未能获取设备信息')
    }
  } catch (error: any) {
    console.error('Failed to collect device info:', error)
    ElMessage.error(error.response?.data?.detail || '获取设备信息失败')
  } finally {
    deviceInfoLoading.value = false
  }
}

const setTrunkReview = async (value: boolean) => {
  if (!switchInfo.value) return

  trunkReviewUpdating.value = true
  try {
    const response = await switchesApi.update(switchId.value, {
      trunk_review_completed: value
    })
    switchInfo.value = response
    ElMessage.success(value ? '已标记为人工识别完成' : '已取消完成标记')
  } catch (error: any) {
    console.error('Failed to update trunk review status:', error)
    ElMessage.error(error.response?.data?.detail || '更新 trunk 识别状态失败')
  } finally {
    trunkReviewUpdating.value = false
  }
}

onMounted(async () => {
  await loadSwitchInfo()
  // 与详情一起预取模板列表，供编辑对话框的「凭据来源」下拉使用。
  snmpProfileStore.load()
  await loadArpData()
  await loadMacData()
  await loadPortAnalysis()
  await loadOpticalData()
})
</script>

<style scoped>
.switch-detail {
  padding: 20px;
  background-color: #f5f7fa;
  min-height: 100vh;
}

.header-content {
  display: flex;
  align-items: center;
  gap: 10px;
}

.switch-ip {
  font-size: 14px;
  color: #606266;
  font-weight: 500;
}

.info-card {
  margin: 20px 0;
  border-radius: 8px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.card-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.port-policy-header {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.section-title {
  font-weight: 700;
  font-size: 15px;
  color: #1f2937 !important;
}

.detail-action-button {
  font-weight: 600;
}

.detail-table-button {
  font-weight: 600;
}

.edit-form-tip {
  margin-left: 8px;
  color: #909399;
  font-size: 12px;
}

.trunk-review-status {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.trunk-review-time {
  color: #909399;
  font-size: 12px;
}

.policy-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 16px;
}

.data-tabs {
  margin-top: 20px;
}

:deep(.desc-label) {
  font-weight: 600;
  background-color: #fafafa;
}

:deep(.el-descriptions__body .el-descriptions__table) {
  table-layout: fixed;
}

:deep(.el-card__header) {
  background: #fafafa;
  border-bottom: 1px solid #ebeef5;
  color: #1f2937 !important;
}

:deep(.el-card__header *:not(.el-button):not(.el-button *)) {
  color: #1f2937 !important;
}


:deep(.el-card__header .el-button--primary) {
  color: #fff !important;
}

:deep(.el-card__header .el-button--success) {
  color: #fff !important;
}

:deep(.el-card__header .el-button--warning) {
  color: #fff !important;
}

:deep(.el-card__header .el-button--info) {
  color: #fff !important;
}

/* ---------- 配置备份页签 ---------- */
.backup-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.backup-msg {
  margin-top: 4px;
  color: #909399;
  font-size: 12px;
  word-break: break-all;
}

.backup-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.backup-link {
  color: #409eff;
  font-size: 12px;
  text-decoration: none;
}

.backup-content-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 8px;
  color: #606266;
  font-size: 12px;
}

.backup-config-content {
  margin: 0;
  padding: 12px;
  max-height: 60vh;
  overflow: auto;
  background: #f5f7fa;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre;
  color: #303133;
}

.backup-diff-box {
  min-height: 200px;
}

.backup-diff-empty {
  padding: 40px 0;
  text-align: center;
  color: #909399;
  font-size: 13px;
}

.backup-diff-content {
  margin: 0;
  padding: 12px;
  max-height: 56vh;
  overflow: auto;
  background: #ffffff;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 1.5;
  color: #303133;
}

.backup-diff-line {
  white-space: pre;
  padding: 0 4px;
}

.backup-diff-line.diff-add {
  background: #e7f7e7;
  color: #1a7f37;
}

.backup-diff-line.diff-del {
  background: #fdecea;
  color: #b42318;
}

.backup-diff-line.diff-hunk {
  background: #eef4ff;
  color: #2f54eb;
}

.backup-diff-line.diff-meta {
  color: #909399;
}

.port-device-empty {
  color: #909399;
}
</style>
