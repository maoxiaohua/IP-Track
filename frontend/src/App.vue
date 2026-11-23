<template>
  <div id="app">
    <el-container>
      <el-header>
        <div class="header-content">
          <h1>IP Track System</h1>
          <el-menu
            mode="horizontal"
            :default-active="activeRoute"
            router
          >
            <el-tooltip content="IP Lookup" placement="bottom" :show-after="300" :disabled="!isMobile">
              <el-menu-item index="/">
                <el-icon><Search /></el-icon>
                <span>IP Lookup</span>
              </el-menu-item>
            </el-tooltip>
            <el-tooltip content="Switches" placement="bottom" :show-after="300" :disabled="!isMobile">
              <el-menu-item index="/switches">
                <el-icon><Setting /></el-icon>
                <span>Switches</span>
              </el-menu-item>
            </el-tooltip>
            <el-tooltip content="Network Topology" placement="bottom" :show-after="300" :disabled="!isMobile">
              <el-menu-item index="/topology">
                <el-icon><Share /></el-icon>
                <span>Topology</span>
              </el-menu-item>
            </el-tooltip>
            <el-tooltip content="IPAM" placement="bottom" :show-after="300" :disabled="!isMobile">
              <el-menu-item index="/ipam">
                <el-icon><Grid /></el-icon>
                <span>IPAM</span>
              </el-menu-item>
            </el-tooltip>
            <el-tooltip content="Optical Modules" placement="bottom" :show-after="300" :disabled="!isMobile">
              <el-menu-item index="/optical-modules">
                <el-icon><Connection /></el-icon>
                <span>Optical Modules</span>
              </el-menu-item>
            </el-tooltip>
          </el-menu>

          <!-- More dropdown outside el-menu -->
          <el-dropdown trigger="click" @command="handleMoreNav">
            <div
            class="more-btn"
            tabindex="0"
            role="button"
            aria-label="More navigation options"
            @keydown.enter="() => {}"
          >
              <el-icon :size="20"><MoreFilled /></el-icon>
            </div>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="/snmp-profiles">
                  <el-icon><Key /></el-icon> SNMP Profiles
                </el-dropdown-item>
                <el-dropdown-item command="/discovery">
                  <el-icon><Compass /></el-icon> Batch Discovery
                </el-dropdown-item>
                <el-dropdown-item command="/command-templates">
                  <el-icon><Document /></el-icon> Templates
                </el-dropdown-item>
                <el-dropdown-item command="/alarms">
                  <el-icon><Bell /></el-icon> Alarms
                </el-dropdown-item>
                <el-dropdown-item command="/history">
                  <el-icon><Clock /></el-icon> History
                </el-dropdown-item>
                <el-dropdown-item command="/settings">
                  <el-icon><Tools /></el-icon> Settings
                </el-dropdown-item>
                <el-dropdown-item command="/bmc-reset">
                  <el-icon><Connection /></el-icon> BMC Reset
                </el-dropdown-item>
                <el-dropdown-item command="/subnet-probe">
                  <el-icon><Search /></el-icon> 子网存活探测
                </el-dropdown-item>
                <el-dropdown-item command="/config-backups">
                  <el-icon><Document /></el-icon> 配置备份
                </el-dropdown-item>
                <el-dropdown-item command="/visio">
                  <el-icon><Document /></el-icon> Visio 图纸查看
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>

          <!-- Login state: guests browse read-only, login unlocks write actions -->
          <div v-if="authStore.isLoggedIn" class="auth-area">
            <el-dropdown trigger="click" @command="handleAccountCommand">
              <div class="user-btn" tabindex="0" role="button" aria-label="账户菜单">
                <el-icon :size="18"><UserFilled /></el-icon>
                <span class="user-name">{{ authStore.displayName }}</span>
              </div>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="change-password">修改密码</el-dropdown-item>
                  <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
          <div v-else class="auth-area">
            <el-tooltip content="当前为只读访客模式，新增/修改/删除需登录" placement="bottom">
              <el-tag type="warning" effect="light" class="guest-tag">只读访客</el-tag>
            </el-tooltip>
            <el-button type="primary" size="small" @click="goLogin">
              <el-icon><UserFilled /></el-icon>
              <span class="login-label">登录</span>
            </el-button>
          </div>
        </div>
      </el-header>
      <el-main>
        <router-view :key="route.path" />
      </el-main>
    </el-container>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { MoreFilled, UserFilled } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const activeRoute = computed(() => route.path)

const isMobile = ref(false)
const mq = typeof window !== 'undefined' ? window.matchMedia('(max-width: 768px)') : null
const updateMobile = (e: MediaQueryListEvent | MediaQueryList) => { isMobile.value = e.matches }

const goLogin = () => {
  router.push({ path: '/login', query: { redirect: route.fullPath } })
}

const handleAccountCommand = async (command: string) => {
  if (command === 'change-password') {
    router.push({ path: '/login', query: { change: '1' } })
    return
  }
  if (command === 'logout') {
    await authStore.logout()
    ElMessage.success('已退出登录，当前为只读访客模式')
    router.push('/')
  }
}

// A 401 anywhere means the token is gone/expired: clear it and offer login.
const handleUnauthorized = () => {
  authStore.clear()
  if (route.path !== '/login') {
    router.push({ path: '/login', query: { redirect: route.fullPath } })
  }
}

onMounted(() => {
  if (mq) { updateMobile(mq); mq.addEventListener('change', updateMobile) }
  window.addEventListener('iptrack:unauthorized', handleUnauthorized)
  authStore.refresh().then((user) => {
    if (user?.must_change_password) {
      router.replace({ path: '/login', query: { change: '1' } })
    }
  })
})
onUnmounted(() => {
  if (mq) mq.removeEventListener('change', updateMobile)
  window.removeEventListener('iptrack:unauthorized', handleUnauthorized)
})

const handleMoreNav = (path: string) => {
  router.push(path)
}
</script>

<style scoped>
#app {
  min-height: 100vh;
  background: linear-gradient(135deg, #3B82F6 0%, #60A5FA 100%);
}

.el-header {
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(10px);
  color: #303133;
  padding: 0;
  box-shadow: 0 2px 20px rgba(59, 130, 246, 0.1);
  position: sticky;
  top: 0;
  z-index: 1000;
}

.header-content {
  display: flex;
  align-items: center;
  height: 100%;
  padding: 0 30px;
  max-width: 1800px;
  margin: 0 auto;
}

.header-content h1 {
  margin: 0;
  margin-right: 50px;
  font-size: 28px;
  font-weight: 700;
  background: linear-gradient(135deg, #3B82F6 0%, #60A5FA 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  letter-spacing: -0.5px;
}

.el-menu {
  background-color: transparent;
  border: none;
  flex: 1;
}

.el-menu-item {
  color: #374151 !important;
  font-weight: 600;
  border-radius: 8px;
  margin: 0 4px;
  transition: all 0.3s ease;
}

.el-menu-item:hover {
  background: linear-gradient(135deg, rgba(59, 130, 246, 0.1) 0%, rgba(96, 165, 250, 0.1) 100%) !important;
  color: #3B82F6 !important;
  transform: translateY(-2px);
}

.el-menu-item.is-active {
  background: linear-gradient(135deg, #3B82F6 0%, #60A5FA 100%) !important;
  color: white !important;
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.4);
}

.el-menu-item .el-icon {
  font-size: 18px;
  margin-right: 6px;
}

/* Sub-menu styling */
:deep(.el-sub-menu__title) {
  color: #374151 !important;
  font-weight: 600;
  border-radius: 8px;
  margin: 0 4px;
  transition: all 0.3s ease;
}

:deep(.el-sub-menu__title:hover) {
  background: linear-gradient(135deg, rgba(59, 130, 246, 0.1) 0%, rgba(96, 165, 250, 0.1) 100%) !important;
  color: #3B82F6 !important;
}

:deep(.el-menu--popup) {
  min-width: 200px !important;
  padding: 8px 0 !important;
}

.more-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 8px;
  cursor: pointer;
  color: #374151;
  transition: all 0.3s ease;
  margin-left: 4px;
  flex-shrink: 0;
}

.more-btn:hover {
  background: rgba(59, 130, 246, 0.1);
  color: #3B82F6;
}

.el-main {
  padding: 30px;
  max-width: 1800px;
  margin: 0 auto;
  width: 100%;
}

/* Login state in the header */
.auth-area {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: 12px;
  flex-shrink: 0;
}

.guest-tag {
  font-weight: 600;
}

.user-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  height: 40px;
  padding: 0 12px;
  border-radius: 8px;
  cursor: pointer;
  color: #374151;
  font-weight: 600;
  transition: all 0.3s ease;
}

.user-btn:hover {
  background: rgba(59, 130, 246, 0.1);
  color: #3B82F6;
}

.user-name {
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Responsive */
@media (max-width: 768px) {
  .header-content h1 {
    font-size: 20px;
    margin-right: 20px;
  }

  .el-menu-item span {
    display: none;
  }

  .el-main {
    padding: 15px;
  }

  .guest-tag,
  .user-name,
  .login-label {
    display: none;
  }

  .auth-area {
    margin-left: 4px;
  }

  .user-btn {
    padding: 0 8px;
  }
}
</style>
