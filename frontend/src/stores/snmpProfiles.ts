import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getSNMPProfiles, type SNMPProfile } from '@/api/snmpProfiles'

/**
 * SNMP 凭据模板的共享缓存。
 *
 * 新增交换机、批量配置、交换机详情、SNMP 配置页都要拉同一份列表来渲染下拉框。
 * 各处分别去拉有两个问题：一是同一屏里可能发好几次重复请求，二是模板页刚改完
 * 名字，另一个页面里下拉框还显示旧名字。集中在这里，谁改完谁调 load(true)。
 *
 * 只缓存**不含口令**的模板元信息 —— 接口本身也不返回口令，下拉框选中的是模板
 * 的 id，凭据由服务端按 id 解析，前端从头到尾拿不到明文。
 */
export const useSNMPProfilesStore = defineStore('snmpProfiles', () => {
  const profiles = ref<SNMPProfile[]>([])
  const loading = ref(false)
  const loaded = ref(false)
  const error = ref<string | null>(null)

  /**
   * 拉取模板列表。默认会复用已加载的缓存，避免每次打开对话框都请求一次；
   * force=true 用于模板增删改之后强制刷新。
   */
  async function load(force = false) {
    if (loaded.value && !force) return
    loading.value = true
    error.value = null
    try {
      // page_size 取大值：下拉框要的是「全部可选模板」，不是分页浏览。
      // 模板数量本身很少（当前 1 条），一次拿完最简单。
      const res = await getSNMPProfiles({ page: 1, page_size: 200 })
      profiles.value = res.items
      loaded.value = true
    } catch (e: any) {
      error.value = e.message || '加载 SNMP 模板失败'
    } finally {
      loading.value = false
    }
  }

  /** 只取启用的模板，用于下拉选项 */
  function enabledProfiles() {
    return profiles.value.filter(p => p.enabled)
  }

  function byId(id?: number | null) {
    if (!id) return undefined
    return profiles.value.find(p => p.id === id)
  }

  return { profiles, loading, loaded, error, load, enabledProfiles, byId }
})
