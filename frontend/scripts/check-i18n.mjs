// 构建前检查：中英文案 key 是否一致；每条文案都能被 vue-i18n 编译（@ | { } 是语法字符，写错会让页面在运行时报错）
import { baseCompile } from '@intlify/message-compiler'
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
const leaves = (o, p = '') => Object.entries(o).flatMap(([k, v]) =>
  v && typeof v === 'object' ? leaves(v, p + k + '.') : [[p + k, v]])
const bad = []
for (const [lang, msgs] of [['zh', zh], ['en', en]]) {
  for (const [k, v] of leaves(msgs)) {
    if (typeof v !== 'string') continue
    baseCompile(v, { onError: e => bad.push(`${lang}.${k}: ${e.message}（${JSON.stringify(v).slice(0, 60)}）`) })
  }
}
if (bad.length) {
  console.error("文案无法编译（字面量 @ 要写成 {'@'}）：\n" + bad.join('\n'))
  process.exit(1)
}
console.log(`i18n ok (${a.size} keys)`)
