// 导出 CSV：带 UTF-8 BOM，Excel 直接打开不乱码。columns: [{ label, value: row => any }]
export function exportCsv(name, columns, rows) {
  const cell = v => {
    const s = v == null ? '' : String(v)
    return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
  }
  const lines = [columns.map(c => cell(c.label)).join(',')]
  for (const r of rows) lines.push(columns.map(c => cell(c.value(r))).join(','))
  const blob = new Blob(['﻿' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' })
  const a = document.createElement('a')
  const d = new Date()
  const p = n => String(n).padStart(2, '0')
  a.href = URL.createObjectURL(blob)
  a.download = `${name}-${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}.csv`
  document.body.appendChild(a)
  a.click()
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove() }, 0)
}

/** 时长：秒 → "3 天 2 小时" / "45 分钟" */
export function duration(sec, zh = true) {
  sec = Math.max(0, Math.floor(sec || 0))
  const d = Math.floor(sec / 86400), h = Math.floor(sec % 86400 / 3600), m = Math.floor(sec % 3600 / 60)
  if (zh) return d ? `${d} 天 ${h} 小时` : h ? `${h} 小时 ${m} 分` : `${m} 分钟`
  return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`
}
