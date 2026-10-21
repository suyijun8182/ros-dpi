// 构建前检查中英文案 key 是否一致
import zh from '../src/i18n/zh.js'
import en from '../src/i18n/en.js'

const flat = (o, p = '') => Object.entries(o).flatMap(([k, v]) =>
  v && typeof v === 'object' ? flat(v, p + k + '.') : [p + k])
const a = new Set(flat(zh)), b = new Set(flat(en))
const onlyZh = [...a].filter(k => !b.has(k)), onlyEn = [...b].filter(k => !a.has(k))
if (onlyZh.length || onlyEn.length) {
  if (onlyZh.length) console.error('en 缺少：', onlyZh.join(', '))
  if (onlyEn.length) console.error('zh 缺少：', onlyEn.join(', '))
  process.exit(1)
}
console.log(`i18n ok (${a.size} keys)`)
