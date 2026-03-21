import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    watch: {
      usePolling: true
    },
    hmr: {
      overlay: false  // Disable HMR overlay to prevent URI malformed errors
    },
    proxy: {
      // Route IPAM API calls to IPAM service
      '/api/v1/ipam': {
        target: 'http://iptrack-backend-ipam:8100',
        changeOrigin: true,
        secure: false
      },
      // Route Network API calls to Collector service (includes optical modules)
      '/api/v1/network': {
        target: 'http://iptrack-backend-collector:8100',
        changeOrigin: true,
        secure: false
      },
      // Route Discovery API calls to Collector service
      '/api/v1/discovery': {
        target: 'http://iptrack-backend-collector:8100',
        changeOrigin: true,
        secure: false
      },
      '/api/v1/command-templates': {
        target: 'http://iptrack-backend-collector:8100',
        changeOrigin: true,
        secure: false
      },
      // All other API calls go to Core service (switches, lookup, history, alarms, snmp-profiles)
      '/api': {
        target: 'http://iptrack-backend-core:8100',
        changeOrigin: true,
        secure: false
      }
    }
  }
})
