import { i18n } from './i18n/index.js'

const UNITS = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']

export function bytes(n, digits = 1) {
  n = Number(n) || 0
  let i = 0
  while (Math.abs(n) >= 1024 && i < UNITS.length - 1) { n /= 1024; i++ }
  return `${n.toFixed(i === 0 ? 0 : digits)} ${UNITS[i]}`
}

// 速率按网络习惯用 bit/s
export function rate(bytesPerSec) {
  let n = (Number(bytesPerSec) || 0) * 8
  const u = ['bps', 'Kbps', 'Mbps', 'Gbps']
  let i = 0
  while (n >= 1000 && i < u.length - 1) { n /= 1000; i++ }
  return `${n.toFixed(i === 0 ? 0 : 1)} ${u[i]}`
}

export function pct(x, digits = 1) {
  return `${((Number(x) || 0) * 100).toFixed(digits)}%`
}

export function ago(ts) {
  if (!ts) return i18n.global.t('common.never')
  const s = Math.max(0, Date.now() / 1000 - ts)
  const zh = i18n.global.locale.value === 'zh'
  if (s < 60) return zh ? '刚刚' : 'just now'
  if (s < 3600) return zh ? `${Math.floor(s / 60)} 分钟前` : `${Math.floor(s / 60)} min ago`
  if (s < 86400) return zh ? `${Math.floor(s / 3600)} 小时前` : `${Math.floor(s / 3600)} h ago`
  return zh ? `${Math.floor(s / 86400)} 天前` : `${Math.floor(s / 86400)} d ago`
}

export function datetime(ts) {
  if (!ts) return '-'
  return new Date(ts * 1000).toLocaleString(i18n.global.locale.value === 'zh' ? 'zh-CN' : 'en', { hour12: false })
}

/** 国家代码 → 当前语言的国家 / 地区名（US → 美国）；"-" 或查不到时返回空串 */
const regionNames = {}
export function countryName(cc) {
  if (!cc || cc === '-' || cc === 'ZZ') return ''
  const lang = i18n.global.locale.value === 'zh' ? 'zh-CN' : 'en'
  try {
    regionNames[lang] = regionNames[lang] || new Intl.DisplayNames([lang], { type: 'region' })
    return regionNames[lang].of(cc.toUpperCase()) || cc
  } catch (e) { return cc }
}

export function appName(a) {
  if (!a) return '-'
  return i18n.global.locale.value === 'zh' ? a.name : (a.name_en || a.name)
}

export function catName(a) {
  if (!a) return '-'
  if ('category_name' in a) return i18n.global.locale.value === 'zh' ? a.category_name : a.category_name_en
  return i18n.global.locale.value === 'zh' ? a.name : (a.name_en || a.name)
}

export function groupName(g) {
  if (!g) return '-'
  if (g.id === '__other') return i18n.global.t('common.otherGroups')
  if ('group_name' in g) return i18n.global.locale.value === 'zh' ? g.group_name : g.group_name_en
  return i18n.global.locale.value === 'zh' ? g.name : (g.name_en || g.name)
}

/*
 * 配色按"应用大类"：8 个有意义的大类各占一个固定色相（style.css 的 --g-*，已用 dataviz 校验脚本验证色盲区分度），
 * 网络基础与未识别用中性灰。大类下的小类用同一色相的深浅区分，名字始终和色块一起出现。
 * 顺序 = 小类在大类内的深浅次序；新增分类时必须同步（后端测试会检查与 apps.yaml 一致）。
 */
export const CAT_GROUP = {
  video: 'media', short_video: 'media', live: 'media', music: 'media',
  game: 'game', mobile_game: 'game', console_game: 'game', game_tool: 'game',
  im: 'social', social: 'social', voip: 'social', mail: 'social',
  download: 'transfer', cloud: 'transfer', update: 'transfer', app_store: 'transfer',
  work: 'work', meeting: 'work', dev: 'work', remote: 'work', ai: 'work', education: 'work',
  shopping: 'life', life: 'life', travel: 'life', finance: 'life', bank: 'life', stock: 'life',
  news: 'info', search: 'info', reading: 'info', site: 'info', adult: 'info',
  iot: 'iot', camera: 'iot',
  network: 'base', system: 'base', cdn: 'base', proxy: 'base', security: 'base', ads: 'base', web: 'base',
  unknown: 'unknown',
}
export const GROUPS = ['media', 'game', 'social', 'transfer', 'work', 'life', 'info', 'iot', 'base', 'unknown']

// 小类深浅：与面板底色混合的比例
const SHADES = [100, 76, 58, 44, 34, 26, 20]
const shadeOf = cat => {
  const g = CAT_GROUP[cat]
  return g ? SHADES[Object.keys(CAT_GROUP).filter(k => CAT_GROUP[k] === g).indexOf(cat)] ?? 20 : 100
}

/** 模板里用：返回 CSS 颜色表达式，随深浅主题自动切换 */
export const groupColor = g => (GROUPS.includes(g) ? `var(--g-${g})` : 'var(--line-strong)')
export function catColor(cat) {
  const base = groupColor(CAT_GROUP[cat] || 'unknown')
  const p = shadeOf(cat)
  return p >= 100 ? base : `color-mix(in srgb, ${base} ${p}%, var(--panel))`
}

// ECharts 需要真实色值：从 CSS 变量读出后自己混色
const cssVar = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim()
const hex2rgb = h => { const n = parseInt(h.replace('#', ''), 16); return [n >> 16 & 255, n >> 8 & 255, n & 255] }
function mix(a, b, p) {
  const x = hex2rgb(a), y = hex2rgb(b)
  return '#' + x.map((v, i) => Math.round(v * p + y[i] * (1 - p)).toString(16).padStart(2, '0')).join('')
}
export const groupHex = g => cssVar(GROUPS.includes(g) ? `--g-${g}` : '--line-strong')
export const catHex = cat => mix(groupHex(CAT_GROUP[cat] || 'unknown'), cssVar('--panel'), shadeOf(cat) / 100)
