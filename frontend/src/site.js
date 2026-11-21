// 多站点（0.7.0）：当前站点。
// - 只有一个站点时 multi=false：不显示切换器，请求不带 site 参数，界面和 0.6.x 一样；
// - 多站点时当前站点放在地址的 ?site=<标识>（复制链接给别人打开的是同一个站点），没有时用这台浏览器上次选的，
//   再没有用第一个能看的站点；所有接口请求自动带上 site（api.js 的拦截器）。
import { reactive } from 'vue'

const KEY = 'rosdpi.site'

export const siteState = reactive({ loaded: false, multi: false, list: [], current: '' })

function remembered() {
  try { return localStorage.getItem(KEY) || '' } catch (e) { return '' }
}

export function siteName(slug) {
  const s = siteState.list.find(x => x.slug === slug)
  return s ? s.name : slug
}

/** 把地址里的 site（可能为空）落到 current 上，返回最终用的站点 */
export function pickSite(fromQuery) {
  if (!siteState.multi) { siteState.current = ''; return '' }
  const ok = slug => slug && siteState.list.some(x => x.slug === slug)
  const slug = ok(fromQuery) ? fromQuery : ok(siteState.current) ? siteState.current
    : ok(remembered()) ? remembered() : (siteState.list[0] || {}).slug || ''
  siteState.current = slug
  try { if (slug) localStorage.setItem(KEY, slug) } catch (e) { /* ignore */ }
  return slug
}

export async function loadSites(http) {
  const r = await http.get('/sites/mine')
  siteState.multi = !!r.multi && r.sites.length > 1
  siteState.list = r.sites
  siteState.loaded = true
  return siteState
}

export function resetSites() {
  Object.assign(siteState, { loaded: false, multi: false, list: [], current: '' })
}
