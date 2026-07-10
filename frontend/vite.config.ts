import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const backendCore = env.VITE_PROXY_CORE || 'http://iptrack-backend-core:8100'
  const backendIpam = env.VITE_PROXY_IPAM || 'http://iptrack-backend-ipam:8100'
  const backendCollector = env.VITE_PROXY_COLLECTOR || 'http://iptrack-backend-collector:8100'

  return {
    plugins: [vue()],
    build: {
      rollupOptions: {
        output: {
          manualChunks(id) {
            if (!id.includes('node_modules')) {
              return
            }

            if (id.includes('xlsx')) {
              return 'vendor-xlsx'
            }

            if (id.includes('echarts') || id.includes('zrender')) {
              return 'vendor-echarts'
            }

            if (id.includes('element-plus') || id.includes('@element-plus')) {
              return 'vendor-element-plus'
            }

            if (
              id.includes('/vue/') ||
              id.includes('@vue') ||
              id.includes('vue-router') ||
              id.includes('pinia')
            ) {
              return 'vendor-vue'
            }
          }
        }
      }
    },
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
        '/api/v1/ipam': {
          target: backendIpam,
          changeOrigin: true,
          secure: false
        },
        '/api/v1/network': {
          target: backendCollector,
          changeOrigin: true,
          secure: false
        },
        '/api/v1/discovery': {
          target: backendCollector,
          changeOrigin: true,
          secure: false
        },
        '/api/v1/command-templates': {
          target: backendCollector,
          changeOrigin: true,
          secure: false
        },
        '/api': {
          target: backendCore,
          changeOrigin: true,
          secure: false
        }
      }
    }
  }
})
