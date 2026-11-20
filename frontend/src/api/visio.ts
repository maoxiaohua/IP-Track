import apiClient, { formatApiDetail } from './index'

export interface VsdxPage {
  index: number
  name: string
  width: number
  height: number
  shape_count: number
  svg: string
}

export interface VsdxParseResponse {
  file_name: string
  pages: VsdxPage[]
  warnings: string[]
}

// The backend returns human-readable Chinese `detail` strings; render them
// directly and suppress the generic interceptor message.
const silentConfig = { skipDefaultErrorHandler: true } as any

export async function parseVsdx(file: File): Promise<VsdxParseResponse> {
  const form = new FormData()
  form.append('file', file)
  try {
    // The shared client defaults to application/json, which makes axios turn
    // FormData into a JSON string. Override it so the browser sends multipart.
    const { data } = await apiClient.post('/api/v1/visio/parse', form, {
      ...silentConfig,
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return data as VsdxParseResponse
  } catch (error: any) {
    const detail = formatApiDetail(error?.response?.data?.detail)
    throw new Error(detail || '解析失败，请确认文件为有效的 .vsdx')
  }
}
