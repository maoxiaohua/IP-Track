<template>
  <div class="visio-viewer">
    <el-card v-loading="loading">
      <template #header>
        <div class="card-header">
          <div>
            <h2 class="title">Visio 图纸查看</h2>
            <div class="sub-title">只读预览 .vsdx 文件，不会修改、也不会保存原文件。</div>
          </div>
        </div>
      </template>

      <el-upload
        ref="uploadRef"
        drag
        :auto-upload="false"
        :show-file-list="false"
        :limit="1"
        accept=".vsdx"
        :disabled="loading"
        :on-change="handleFileChange"
        class="upload-area"
      >
        <div class="upload-text">把 .vsdx 文件拖到这里，或<em>点击选择文件</em></div>
        <template #tip>
          <div class="upload-tip">
            支持多页图纸。弧线与样条曲线按近似曲线显示；EMF 矢量图会转换为 SVG 显示（个别含文字或位图层的部分可能缺失），WMF/TIFF 等仍无法显示的图片以虚线框标出，其余图形、文本、图片、组合与旋转按原样渲染。
          </div>
        </template>
      </el-upload>

      <el-alert
        v-if="errorMessage"
        class="msg"
        type="error"
        :closable="false"
        show-icon
        :title="errorMessage"
      />
      <el-alert
        v-if="warnings.length"
        class="msg"
        type="warning"
        :closable="false"
        show-icon
        :title="`解析提示（${warnings.length} 条）`"
      >
        <div v-for="(w, i) in warnings" :key="i" class="warning-item">{{ w }}</div>
      </el-alert>

      <el-empty v-if="!result && !loading" description="尚未打开任何 .vsdx 文件" />
    </el-card>

    <el-card v-if="result" class="result-card">
      <template #header>
        <div class="card-header">
          <h3 class="file-name">{{ result.file_name }}</h3>
          <div class="actions">
            <el-button size="small" :disabled="zoom <= ZOOM_MIN" @click="zoomOut">缩小</el-button>
            <span class="zoom-label">{{ zoom }}%</span>
            <el-button size="small" :disabled="zoom >= ZOOM_MAX" @click="zoomIn">放大</el-button>
            <el-button size="small" @click="fitWidth">适应宽度</el-button>
            <el-button size="small" @click="resetZoom">原始尺寸</el-button>
            <el-button size="small" type="danger" plain @click="closeDocument">关闭</el-button>
          </div>
        </div>
      </template>

      <el-tabs
        v-if="result.pages.length > 1"
        v-model="activeIndex"
        class="page-tabs"
        @tab-change="handleTabChange"
      >
        <el-tab-pane
          v-for="p in result.pages"
          :key="p.index"
          :label="p.name || `第 ${p.index + 1} 页`"
          :name="p.index"
        />
      </el-tabs>

      <div v-if="currentPage" class="page-meta">
        第 {{ currentPage.index + 1 }} / {{ result.pages.length }} 页 · 图形
        {{ currentPage.shape_count }} 个 · {{ Math.round(currentPage.width) }} ×
        {{ Math.round(currentPage.height) }} px
      </div>

      <div ref="scrollRef" class="svg-scroll">
        <img
          v-if="currentPage"
          :src="currentPageUri"
          :style="imgStyle"
          :alt="`${result.file_name} 第 ${currentPage.index + 1} 页`"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import type { UploadFile } from 'element-plus'
import { parseVsdx, type VsdxParseResponse } from '@/api/visio'

const ZOOM_MIN = 50
const ZOOM_MAX = 300
const ZOOM_STEP = 10
// Keep the opened document in sessionStorage so a dev-server full reload
// (HMR) does not discard it. Cleared when the document is closed.
const STORAGE_KEY = 'iptrack_visio_doc'

const uploadRef = ref<any>(null)
const scrollRef = ref<HTMLElement | null>(null)

const loading = ref(false)
const errorMessage = ref('')
const warnings = ref<string[]>([])
const result = ref<VsdxParseResponse | null>(null)
const activeIndex = ref(0)
const zoom = ref(100)

const currentPage = computed(() => {
  const pages = result.value?.pages
  if (!pages || !pages.length) return null
  return pages[activeIndex.value] ?? pages[0]
})

const currentPageUri = computed(() => {
  const page = currentPage.value
  return page ? svgToDataUri(page.svg) : ''
})

const imgStyle = computed(() => {
  const page = currentPage.value
  if (!page) return {}
  return { width: `${Math.round((page.width * zoom.value) / 100)}px` }
})

function clampZoom(value: number): number {
  return Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, Math.round(value)))
}

// Chunked UTF-8 -> base64 so non-ASCII labels inside the SVG survive.
function svgToDataUri(svg: string): string {
  const bytes = new TextEncoder().encode(svg)
  let binary = ''
  const CHUNK = 0x8000
  for (let i = 0; i < bytes.length; i += CHUNK) {
    binary += String.fromCharCode(...bytes.subarray(i, i + CHUNK))
  }
  return `data:image/svg+xml;base64,${btoa(binary)}`
}

function persist() {
  if (!result.value) return
  try {
    sessionStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        result: result.value,
        warnings: warnings.value,
        activeIndex: activeIndex.value,
        zoom: zoom.value,
      }),
    )
  } catch {
    // Storage disabled or over quota: the viewer still works, just without
    // surviving a reload.
  }
}

function restore() {
  let saved: any = null
  try {
    saved = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || 'null')
  } catch {
    saved = null
  }
  if (!saved || !saved.result || !Array.isArray(saved.result.pages) || !saved.result.pages.length) {
    return
  }
  result.value = saved.result as VsdxParseResponse
  warnings.value = Array.isArray(saved.warnings) ? saved.warnings : []
  const last = saved.result.pages.length - 1
  activeIndex.value = Math.min(Math.max(0, Number(saved.activeIndex) || 0), last)
  zoom.value = clampZoom(Number(saved.zoom) || 100)
}

onMounted(restore)

async function handleFileChange(file: UploadFile) {
  const raw = file.raw
  if (!raw) return
  if (!raw.name.toLowerCase().endsWith('.vsdx')) {
    errorMessage.value = '仅支持 .vsdx 文件'
    uploadRef.value?.clearFiles()
    return
  }
  await loadDocument(raw)
}

async function loadDocument(file: File) {
  loading.value = true
  errorMessage.value = ''
  warnings.value = []
  result.value = null
  zoom.value = 100
  activeIndex.value = 0
  try {
    const data = await parseVsdx(file)
    if (!data.pages.length) {
      errorMessage.value = '文件中没有可显示的页面'
      return
    }
    result.value = data
    warnings.value = data.warnings || []
    persist()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '解析失败'
  } finally {
    loading.value = false
    uploadRef.value?.clearFiles()
  }
}

function zoomIn() {
  zoom.value = clampZoom(zoom.value + ZOOM_STEP)
}

function zoomOut() {
  zoom.value = clampZoom(zoom.value - ZOOM_STEP)
}

function resetZoom() {
  zoom.value = 100
}

function fitWidth() {
  const page = currentPage.value
  const container = scrollRef.value
  if (!page || !container || !container.clientWidth) {
    resetZoom()
    return
  }
  const available = container.clientWidth - 24
  zoom.value = clampZoom((available / page.width) * 100)
}

function handleTabChange() {
  zoom.value = 100
}

watch(activeIndex, () => {
  zoom.value = 100
})

watch([activeIndex, zoom], persist)

function closeDocument() {
  try {
    sessionStorage.removeItem(STORAGE_KEY)
  } catch {
    // ignore
  }
  result.value = null
  warnings.value = []
  errorMessage.value = ''
  activeIndex.value = 0
  zoom.value = 100
  uploadRef.value?.clearFiles()
}
</script>

<style scoped>
.visio-viewer {
  max-width: 1400px;
  margin: 0 auto;
}

.card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.title {
  margin: 0;
  font-size: 20px;
  color: #303133;
}

.sub-title {
  margin-top: 6px;
  font-size: 13px;
  color: #909399;
}

.upload-area {
  margin-bottom: 8px;
}

.upload-text {
  font-size: 14px;
  color: #606266;
}

.upload-text em {
  color: #409eff;
  font-style: normal;
}

.upload-tip {
  margin-top: 8px;
  font-size: 12px;
  color: #909399;
  line-height: 1.6;
}

.msg {
  margin-top: 12px;
}

.warning-item {
  font-size: 12px;
  line-height: 1.7;
}

.result-card {
  margin-top: 16px;
}

.file-name {
  margin: 0;
  font-size: 16px;
  color: #303133;
  word-break: break-all;
}

.actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.zoom-label {
  min-width: 48px;
  text-align: center;
  font-size: 13px;
  color: #606266;
}

.page-meta {
  margin-bottom: 8px;
  font-size: 13px;
  color: #909399;
}

.svg-scroll {
  overflow: auto;
  max-height: 72vh;
  padding: 12px;
  background: #f5f7fa;
  border: 1px solid #ebeef5;
  border-radius: 4px;
}

.svg-scroll img {
  display: block;
  max-width: none;
  background: #fff;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.12);
}

@media (max-width: 640px) {
  .actions {
    width: 100%;
  }

  .svg-scroll {
    max-height: 60vh;
  }
}
</style>
