import { createI18n } from 'vue-i18n'
import zh from './zh.js'
import en from './en.js'

function initial() {
  try {
    const saved = localStorage.getItem('rosdpi.lang')
    if (saved) return saved
  } catch (e) { /* 隐私模式 */ }
  return (navigator.language || 'zh').toLowerCase().startsWith('zh') ? 'zh' : 'en'
}

export const i18n = createI18n({ legacy: false, locale: initial(), fallbackLocale: 'zh', messages: { zh, en } })

export function setLang(l) {
  i18n.global.locale.value = l
  document.documentElement.lang = l === 'zh' ? 'zh-CN' : 'en'
  try { localStorage.setItem('rosdpi.lang', l) } catch (e) { /* ignore */ }
}
