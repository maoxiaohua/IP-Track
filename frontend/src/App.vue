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
            <el-menu-item index="/">
              <el-icon><Search /></el-icon>
              <span>IP Lookup</span>
            </el-menu-item>
            <el-menu-item index="/switches">
              <el-icon><Setting /></el-icon>
              <span>Switches</span>
            </el-menu-item>
            <el-menu-item index="/ipam">
              <el-icon><Grid /></el-icon>
              <span>IPAM</span>
            </el-menu-item>
            <el-menu-item index="/discovery">
              <el-icon><Compass /></el-icon>
              <span>Batch Discovery</span>
            </el-menu-item>
            <el-menu-item index="/history">
              <el-icon><Clock /></el-icon>
              <span>History</span>
            </el-menu-item>
          </el-menu>
        </div>
      </el-header>
      <el-main>
        <router-view />
      </el-main>
    </el-container>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const activeRoute = computed(() => route.path)
</script>

<style scoped>
#app {
  min-height: 100vh;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}

.el-header {
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(10px);
  color: #303133;
  padding: 0;
  box-shadow: 0 2px 20px rgba(0, 0, 0, 0.1);
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
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
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
  color: #606266 !important;
  font-weight: 500;
  border-radius: 8px;
  margin: 0 4px;
  transition: all 0.3s ease;
}

.el-menu-item:hover {
  background: linear-gradient(135deg, rgba(102, 126, 234, 0.1) 0%, rgba(118, 75, 162, 0.1) 100%) !important;
  color: #667eea !important;
  transform: translateY(-2px);
}

.el-menu-item.is-active {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
  color: white !important;
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
}

.el-menu-item .el-icon {
  font-size: 18px;
  margin-right: 6px;
}

.el-main {
  padding: 30px;
  max-width: 1800px;
  margin: 0 auto;
  width: 100%;
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
}
</style>
