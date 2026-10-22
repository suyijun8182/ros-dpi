// 使用场景（家用 / 企业）：决定称呼（家庭成员 / 人员、分组 / 部门、学习时间 / 工作时间）和默认的分析指标
import { reactive } from 'vue'
import http from './api.js'
import { i18n } from './i18n/index.js'

export const scene = reactive({ id: 'home', loaded: false, people: [], departments: [] })

export async function loadScene(force = false) {
  if (scene.loaded && !force) return scene
  try {
    const r = await http.get('/people/meta')
    Object.assign(scene, { id: r.scenario, people: r.people, departments: r.departments, loaded: true })
  } catch (e) { /* 未登录或接口不可用时保持默认 */ }
  return scene
}

/** 按场景取称呼：L('person') → 家庭成员 / 人员 */
export const L = (key, args) => i18n.global.t(`scn.${scene.id}.${key}`, args || {})

/** 秒 → "2 小时 5 分" / "2h 5m" */
export function hours(sec) {
  sec = Math.max(0, Math.round(sec || 0))
  const zh = i18n.global.locale.value === 'zh'
  const h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60)
  if (zh) return h ? `${h} 小时${m ? ` ${m} 分` : ''}` : `${m} 分钟`
  return h ? `${h}h${m ? ` ${m}m` : ''}` : `${m}m`
}
