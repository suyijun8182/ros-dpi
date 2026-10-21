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

export function appName(a) {
  if (!a) return '-'
  return i18n.global.locale.value === 'zh' ? a.name : (a.name_en || a.name)
}

export function catName(a) {
  if (!a) return '-'
  if ('category_name' in a) return i18n.global.locale.value === 'zh' ? a.category_name : a.category_name_en
  return i18n.global.locale.value === 'zh' ? a.name : (a.name_en || a.name)
}

// 分类固定配色，所有图表保持一致
export const CAT_COLORS = {
  video: '#d9485f', short_video: '#e2638f', live: '#b65fc8', music: '#8a63d2', social: '#6d7be0',
  im: '#2f9a57', game: '#e07a2e', shopping: '#d4a72c', news: '#7fa83a', search: '#2a9d8f', cloud: '#3c8fd0',
  download: '#c0533a', update: '#7b8794', ai: '#1fa7b8', work: '#2c6bc9', finance: '#3aa57a', life: '#c98a3c',
  ads: '#8b5e3c', iot: '#4bb3a0', network: '#a3aeb0', web: '#5f78b8', unknown: '#b5bec0',
}

export const catColor = c => CAT_COLORS[c] || '#64748b'
