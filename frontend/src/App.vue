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
  background-color: #f5f7fa;
}

.el-header {
  background-color: #409eff;
  color: white;
  padding: 0;
}

.header-content {
  display: flex;
  align-items: center;
  height: 100%;
  padding: 0 20px;
}

.header-content h1 {
  margin: 0;
  margin-right: 40px;
  font-size: 24px;
  color: white;
}

.el-menu {
  background-color: transparent;
  border: none;
}

.el-menu-item {
  color: white !important;
}

.el-menu-item:hover {
  background-color: rgba(255, 255, 255, 0.1) !important;
}

.el-menu-item.is-active {
  background-color: rgba(255, 255, 255, 0.2) !important;
  border-bottom: 2px solid white !important;
}

.el-main {
  padding: 20px;
}
</style>
