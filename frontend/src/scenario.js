// 使用场景（家庭 / 企业）：全局设置，决定称呼（家庭成员 / 员工、分组 / 部门、学习时间 / 工作时间）和默认的分析指标
import { reactive } from 'vue'
import http from './api.js'
import { i18n } from './i18n/index.js'

const KEY = 'rosdpi.scene'
function cached() {
  try { return localStorage.getItem(KEY) === 'enterprise' ? 'enterprise' : 'home' } catch (e) { return 'home' }
}
function remember(id) {
  try { localStorage.setItem(KEY, id) } catch (e) { /* ignore */ }
}

// 先用上次的场景，避免企业场景刷新时菜单先闪出“家庭成员”
export const scene = reactive({ id: cached(), loaded: false, people: [], departments: [] })

export async function loadScene(force = false) {
  if (scene.loaded && !force) return scene
  try {
    const r = await http.get('/people/meta')
    Object.assign(scene, { id: r.scenario, people: r.people, departments: r.departments, loaded: true })
    remember(r.scenario)
  } catch (e) { /* 未登录或接口不可用时保持默认 */ }
  return scene
}

/** 页面从别的接口拿到场景时同步一下（人员列表、行为洞察都会带 scenario） */
export function syncScene(id) {
  if (id && id !== scene.id) {
    scene.id = id
    remember(id)
  }
}

/** 切换场景（管理员）：其余分析设置换成新场景的默认值，返回新配置 */
export async function setScene(id) {
  const r = await http.put('/analysis/settings', { scenario: id })
  syncScene(r.config.scenario)
  return r.config
}

/** 按场景取称呼：L('person') → 成员 / 员工 */
export const L = (key, args) => i18n.global.t(`scn.${scene.id}.${key}`, args || {})

/** 秒 → "2 小时 5 分" / "2h 5m" */
export function hours(sec) {
  sec = Math.max(0, Math.round(sec || 0))
  const zh = i18n.global.locale.value === 'zh'
  const h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60)
  if (zh) return h ? `${h} 小时${m ? ` ${m} 分` : ''}` : `${m} 分钟`
  return h ? `${h}h${m ? ` ${m}m` : ''}` : `${m}m`
}
