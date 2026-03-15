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
      '/api': {
        target: 'http://iptrack-backend:8100',
        changeOrigin: true,
        secure: false
      }
    }
  }
})
