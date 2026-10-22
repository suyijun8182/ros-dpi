// ECharts 配置生成。颜色从 CSS 变量读取，切换主题/语言后重新生成即可。
// 风格对齐维盟 WayOS 4.0（debug5）：
// - 折线：上行钢蓝、下行青绿，两条都在零线以上；细直线，图例居中（线 + 空心圆），纵轴单位紧凑（"114.44 M"）；
// - 构成：实心饼图 + 右侧竖排可翻页图例；提示框白底、边框跟随数据颜色、数值加粗。
import { bytes, countryName, groupHex, groupName, pct, rate } from './format.js'
import { i18n } from './i18n/index.js'

const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim()
const t = (k, p) => i18n.global.t(k, p)
const FONT = '"Barlow Semi Condensed", "Barlow", "PingFang SC", "Microsoft YaHei", sans-serif'
const STEP = { minute: 60, hour: 3600, day: 86400 }

function tooltip(extra = {}) {
  return {
    backgroundColor: css('--panel'), borderColor: css('--line'), borderWidth: 1, padding: [10, 14],
    textStyle: { color: css('--ink'), fontSize: 13, fontFamily: FONT },
    extraCssText: 'box-shadow:0 6px 20px rgba(30,40,70,.12);border-radius:8px', ...extra,
  }
}

const pad = n => String(n).padStart(2, '0')
export function fmtTime(ts, gran) {
  const d = new Date(ts * 1000)
  if (gran === 'day') return `${d.getMonth() + 1}/${d.getDate()}`
  if (gran === 'second') return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** 纵轴的紧凑单位：bit 用 1000 进制（"143.05 M"），字节用 1024 进制（"1.25 G"） */
function axisUnit(v, base) {
  const units = ['', 'K', 'M', 'G', 'T']
  let i = 0
  while (Math.abs(v) >= base && i < units.length - 1) { v /= base; i++ }
  return v === 0 ? '0' : `${+v.toFixed(2)} ${units[i]}`
}

/** 每种量的数值格式：rate-bit（bit/s）、rate-byte（B/s）、bytes（流量）、count（个数） */
function formatter(kind) {
  if (kind === 'rate-bit') return { tip: v => rate(v), axis: v => axisUnit(v * 8, 1000), unit: 'bit/s' }
  if (kind === 'rate-byte') return { tip: v => `${bytes(v)}/s`, axis: v => axisUnit(v, 1024), unit: 'B/s' }
  if (kind === 'count') return { tip: v => `${v}`, axis: v => `${v}`, unit: '' }
  return { tip: v => bytes(v), axis: v => axisUnit(v, 1024), unit: 'B' }
}

/**
 * 维盟式折线图。lines: [{ name, color, data }]；labels: 横轴文字。
 * 图例居中在顶部，series 的空心圆让图例显示成“线 + 圆”。
 */
function lineChart(lines, labels, kind, { area = false, compact = false } = {}) {
  const f = formatter(kind)
  return {
    textStyle: { fontFamily: FONT },
    grid: compact ? { left: 0, right: 0, top: 4, bottom: 0 } : { left: 8, right: 18, top: 44, bottom: 4, containLabel: true },
    legend: compact ? undefined : {
      top: 4, left: 'center', itemWidth: 28, itemHeight: 12, itemGap: 22,
      textStyle: { color: css('--ink'), fontFamily: FONT, fontSize: 13 },
    },
    tooltip: tooltip({
      trigger: 'axis', axisPointer: { type: 'line', lineStyle: { color: css('--line-strong') } },
      formatter: ps => `<div style="min-width:170px"><div style="color:${css('--muted')};margin-bottom:4px">${ps[0]?.axisValue ?? ''}</div>` +
        ps.map(p => `<div style="display:flex;justify-content:space-between;gap:18px;line-height:1.9"><span>${p.marker}${p.seriesName.replace(/\(.*\)$/, '')}</span><b>${f.tip(p.value)}</b></div>`).join('') + '</div>',
    }),
    xAxis: {
      type: 'category', show: !compact, boundaryGap: false, data: labels,
      axisLine: { lineStyle: { color: css('--line-strong') } }, axisTick: { show: false },
      axisLabel: { color: css('--muted'), hideOverlap: true, fontFamily: FONT, fontSize: 12 },
    },
    yAxis: {
      type: 'value', show: !compact, splitNumber: 5, minInterval: kind === 'count' ? 1 : 0,
      splitLine: { lineStyle: { color: css('--line') } },
      axisLabel: { color: css('--muted'), fontFamily: FONT, fontSize: 12, formatter: f.axis },
    },
    series: lines.map(l => ({
      name: l.name, type: 'line', data: l.data, smooth: false,
      // 只有几个点时把点画出来，不然一个点的线什么都看不见
      symbol: 'emptyCircle', symbolSize: 7, showSymbol: l.data.length <= 3,
      lineStyle: { width: 1.6, color: l.color }, itemStyle: { color: l.color, borderWidth: 2 },
      areaStyle: area ? { color: l.color, opacity: 0.12 } : undefined,
      emphasis: { focus: 'none' },
    })),
  }
}

const upColor = () => css('--line-up')
const downColor = () => css('--line-down')

/** 上下行折线（实时流量 / 历史流量）。points: [{ts, up, down}]；asRate 时 points 已是 B/s */
export function trendOption(points, gran = 'hour', { asRate = false, unit = 'bit' } = {}) {
  const kind = asRate ? (unit === 'byte' ? 'rate-byte' : 'rate-bit') : 'bytes'
  const suffix = asRate ? `(${formatter(kind).unit})` : ''
  const name = k => t(asRate ? `chart.${k}Rate` : `chart.${k}Bytes`) + suffix
  return lineChart([
    { name: name('up'), color: upColor(), data: points.map(p => p.up) },
    { name: name('down'), color: downColor(), data: points.map(p => p.down) },
  ], points.map(p => fmtTime(p.ts, gran)), kind)
}

/** 按应用大类拆分的历史流量：每个大类一条线（颜色固定跟随大类），最多 7 个大类 + 其他 */
export function groupsOption(tg) {
  const lines = tg.series.map(s => ({
    name: groupName(s), color: s.id === '__other' ? css('--line-strong') : groupHex(s.id), data: s.values,
  }))
  const opt = lineChart(lines, tg.ts.map(ts => fmtTime(ts, tg.gran)), 'bytes')
  opt.legend = { ...opt.legend, type: 'scroll' }
  return opt
}

/** 在线终端数随时间（历史用户）。compact 时是没有坐标轴的小曲线 */
export function onlineOption(points, gran = 'minute', compact = false) {
  return lineChart([{ name: t('overview.online'), color: css('--accent'), data: points.map(p => p.n) }],
    points.map(p => fmtTime(p.ts, gran)), 'count', { area: compact, compact })
}

/**
 * 维盟式实心饼图 + 右侧竖排可翻页图例。items: [{ id, name, value, color }]。
 * 图例显示名称和占比；数值在提示框里。
 */
// narrow：窄屏把图例放到饼图下方横排，避免竖排图例压住饼图
// 两个 #rrggbb 按比例混色（canvas 不认 CSS color-mix）
function hexMix(a, b, p) {
  const rgb = h => { const n = parseInt(h.replace('#', '').slice(0, 6), 16); return [n >> 16 & 255, n >> 8 & 255, n & 255] }
  if (!/^#[0-9a-f]{6}/i.test(a) || !/^#[0-9a-f]{6}/i.test(b)) return a
  const x = rgb(a), y = rgb(b)
  return '#' + x.map((v, i) => Math.round(v * p + y[i] * (1 - p)).toString(16).padStart(2, '0')).join('')
}

/** 流向图：从本地（home）飞向各国，线宽、气泡大小随流量（平方根刻度）；流量最大的 5 个国家标名字和流量 */
export function flowMapOption(rows, home, centers, active, homeName, narrow = false) {
  const sum = rows.reduce((a, x) => a + x.bytes, 0) || 1
  const panel = css('--panel'), ink = css('--ink'), muted = css('--muted'), accent = css('--accent')
  const brand = css('--brand-ink'), sunk = css('--sunk'), warn = css('--warn')
  const land = hexMix(sunk, ink, 0.92)
  const from = centers[home] || [104, 34.5]
  const dests = rows.filter(r => r.cc !== home && centers[r.cc]).sort((a, b) => b.bytes - a.bytes)
  const local = rows.find(r => r.cc === home)
  const max = Math.max(1, ...dests.map(r => r.bytes))
  const k = b => Math.sqrt(b / max)
  const tip = r => `<b>${r.name}</b><div style="margin-top:4px"><b>${bytes(r.bytes)}</b> <span style="color:${muted}">${pct(r.bytes / sum)}</span></div>`
  const point = (r, i) => ({ name: r.name, cc: r.cc, bytes: r.bytes, value: [...centers[r.cc], r.bytes], rank: i,
    symbolSize: 7 + 20 * k(r.bytes), itemStyle: active === r.cc ? { color: warn, borderColor: ink, borderWidth: 1.5 } : undefined })
  return {
    textStyle: { fontFamily: FONT },
    tooltip: tooltip({
      trigger: 'item',
      formatter: p => {
        const d = p.data || {}
        if (d.cc && d.bytes != null) return tip(d)
        if (p.componentType === 'geo') {
          const r = rows.find(x => x.cc === p.name)
          return r ? tip(r) : ''
        }
        return d.home ? `<b>${d.name}</b>` + (local ? tip({ ...local, name: '' }).replace('<b></b>', '') : '') : ''
      },
    }),
    geo: {
      map: 'world', roam: false, silent: false, boundingCoords: [[-168, 78], [190, -56]], top: 8, bottom: 8, left: 8, right: 8,
      itemStyle: { areaColor: land, borderColor: panel, borderWidth: 0.6 },
      emphasis: { label: { show: false }, itemStyle: { areaColor: hexMix(accent, land, 0.35) } },
      select: { disabled: true },
      regions: [
        { name: home, itemStyle: { areaColor: hexMix(brand, land, 0.28) } },
        ...dests.map(r => ({ name: r.cc, itemStyle: { areaColor: hexMix(accent, land, 0.12 + 0.3 * k(r.bytes)) } })),
      ],
    },
    series: [
      { // 飞线
        type: 'lines', coordinateSystem: 'geo', zlevel: 1, silent: true,
        effect: { show: true, period: 5, trailLength: 0.2, symbol: 'arrow', symbolSize: 5, color: accent },
        lineStyle: { color: accent, opacity: 0.45, curveness: 0.28 },
        data: dests.map(r => ({ coords: [from, centers[r.cc]], lineStyle: { width: 0.8 + 3.5 * k(r.bytes) } })),
      },
      { // 流量最大的 5 个：带涟漪、标名字
        type: 'effectScatter', coordinateSystem: 'geo', zlevel: 2, rippleEffect: { brushType: 'stroke', scale: 2.6, period: 4 },
        itemStyle: { color: accent, shadowBlur: 6, shadowColor: hexMix(accent, panel, 0.4) },
        label: { show: true, position: narrow ? 'top' : 'right', color: ink, fontSize: narrow ? 11 : 12, fontWeight: 600, distance: 6,
          formatter: p => (narrow ? p.data.name : `${p.data.name}  {s|${bytes(p.data.bytes)}}`), rich: { s: { color: muted, fontWeight: 400, fontSize: 11 } },
          textBorderColor: panel, textBorderWidth: 3 },
        data: dests.slice(0, 5).map(point),
      },
      { // 其余国家
        type: 'scatter', coordinateSystem: 'geo', zlevel: 2,
        itemStyle: { color: hexMix(accent, panel, 0.75) }, data: dests.slice(5).map(point),
      },
      { // 本地
        type: 'scatter', coordinateSystem: 'geo', zlevel: 3, symbol: 'pin', symbolSize: 30,
        itemStyle: { color: brand }, label: { show: true, position: 'bottom', color: ink, fontSize: 12, fontWeight: 600,
          textBorderColor: panel, textBorderWidth: 3, formatter: () => homeName },
        data: [{ name: homeName, home: true, value: from }],
      },
    ],
  }
}

/** 矩形树图：大类 → 小类，面积 = 流量。items: [{id, name, value, color, children: [...]}] */
export function treemapOption(items) {
  const sum = items.reduce((a, x) => a + x.value, 0) || 1
  const ink = css('--ink'), panel = css('--panel')
  // 文字颜色按方块深浅选：深色块白字，浅色块用正文色
  const lum = h => { const n = parseInt(String(h).replace('#', '').slice(0, 6), 16); return ((n >> 16 & 255) * 0.299 + (n >> 8 & 255) * 0.587 + (n & 255) * 0.114) / 255 }
  const fg = c => (/^#[0-9a-f]{6}/i.test(c) && lum(c) < 0.62 ? '#ffffff' : ink)
  // 大类：外框和标题条用大类本身的颜色（父节点露出来的部分画的是边框色）
  const node = x => ({ ...x, itemStyle: x.children ? { color: x.color, borderColor: x.color } : { color: x.color },
    label: { color: fg(x.color) }, upperLabel: { color: fg(x.color) },
    children: x.children && x.children.map(node) })
  return {
    textStyle: { fontFamily: FONT },
    tooltip: tooltip({
      formatter: p => {
        const v = p.data && p.data.value
        if (!v) return ''
        const path = (p.treePathInfo || []).slice(1).map(x => x.name).join(' / ')
        return `<div style="display:flex;align-items:center;gap:10px">${p.marker}<span>${path}</span>`
          + `<b style="margin-left:14px">${bytes(v)}</b><span style="color:${css('--muted')}">${pct(v / sum)}</span></div>`
      },
    }),
    series: [{
      type: 'treemap', roam: false, nodeClick: false, breadcrumb: { show: false }, top: 0, left: 0, right: 0, bottom: 0,
      sort: 'desc', squareRatio: 1.4, visibleMin: 300,
      upperLabel: { show: true, height: 24 },
      levels: [
        // 第 0 层是虚拟的根节点：不显示标题
        { itemStyle: { borderWidth: 0, gapWidth: 4 }, upperLabel: { show: false } },
        // 第 1 层：大类（顶部一条标题栏）
        { itemStyle: { borderColor: panel, borderWidth: 3, gapWidth: 2, borderRadius: 6 },
          upperLabel: { show: true, height: 24, fontWeight: 600, fontSize: 13, padding: [0, 8],
            formatter: p => `${p.name}  ${pct(p.value / sum, 0)}` } },
        // 第 2 层：小类
        { itemStyle: { borderColor: panel, borderWidth: 1, gapWidth: 1, borderRadius: 4 }, upperLabel: { show: false },
          label: { show: true, fontSize: 12, lineHeight: 16, padding: [6, 8], overflow: 'truncate',
            formatter: p => `${p.name}\n{s|${bytes(p.value)}}`, rich: { s: { fontSize: 11, opacity: 0.85 } } } },
      ],
      data: items.map(node),
    }],
  }
}

export function pieOption(items, { legend = true, narrow = false } = {}) {
  const sum = items.reduce((a, x) => a + x.value, 0) || 1
  const share = new Map(items.map(x => [x.name, pct(x.value / sum, 1)]))
  return {
    textStyle: { fontFamily: FONT },
    tooltip: tooltip({
      trigger: 'item',
      formatter: p => {
        return `<div style="display:flex;align-items:center;gap:10px">${p.marker}<span>${p.name}</span><b style="margin-left:14px">${bytes(p.value)}</b><span style="color:${css('--muted')}">${pct(p.value / sum)}</span></div>`
      },
    }),
    legend: legend ? {
      ...(narrow ? { type: 'plain', orient: 'horizontal', left: 'center', bottom: 0, itemGap: 10 }
        : { type: 'scroll', orient: 'vertical', right: 0, top: 'middle', itemGap: 12 }),
      itemWidth: 22, itemHeight: 12,
      icon: 'roundRect', textStyle: { color: css('--ink'), fontFamily: FONT, fontSize: 13, rich: { p: { color: css('--muted'), fontSize: 12, padding: [0, 0, 0, 6] } } },
      formatter: n => `${n}{p|${share.get(n) || ''}}`,
      pageIconColor: css('--brand-ink'), pageIconInactiveColor: css('--line-strong'), pageIconSize: 11,
      pageTextStyle: { color: css('--muted'), fontFamily: FONT }, pageButtonItemGap: 8,
    } : undefined,
    series: [{
      type: 'pie', radius: !legend ? '82%' : narrow ? '58%' : '72%',
      center: !legend ? ['50%', '50%'] : narrow ? ['50%', '36%'] : ['36%', '52%'], startAngle: 90,
      label: { show: false }, labelLine: { show: false },
      itemStyle: { borderColor: css('--panel'), borderWidth: 1 },
      emphasis: { scale: true, scaleSize: 6 },
      data: items.map(x => ({ name: x.name, value: x.value, id: x.id, itemStyle: { color: x.color } })),
    }],
  }
}

/** 健康指数仪表盘：维盟式刻度弧，两侧标“差 中 良 优”，中间“95分”。 */
export function gaugeOption(score) {
  const color = score >= 90 ? css('--accent') : score >= 75 ? css('--pair-blue') : score >= 60 ? css('--warn') : css('--bad')
  const marks = { 12.5: 'poor', 37.5: 'fair', 62.5: 'good', 87.5: 'excellent' }
  return {
    series: [{
      type: 'gauge', startAngle: 200, endAngle: -20, min: 0, max: 100, splitNumber: 8, radius: '76%', center: ['50%', '66%'],
      progress: { show: true, width: 8, roundCap: true, itemStyle: { color } },
      axisLine: { roundCap: true, lineStyle: { width: 8, color: [[1, css('--sunk')]] } },
      axisTick: { distance: -22, length: 7, splitNumber: 3, lineStyle: { color, width: 1.2, opacity: 0.6 } },
      splitLine: { distance: -24, length: 10, lineStyle: { color, width: 2 } },
      axisLabel: { distance: -46, color: css('--muted'), fontSize: 13, formatter: v => (marks[v] ? t('health.level.' + marks[v]) : '') },
      pointer: { show: false }, anchor: { show: false }, title: { show: false },
      detail: { valueAnimation: true, offsetCenter: [0, '8%'], fontFamily: FONT, fontSize: 34, fontWeight: 600, color,
        formatter: v => `{v|${Math.round(v)}}{u|${t('health.points')}}`,
        rich: { v: { fontSize: 34, fontWeight: 600, color, fontFamily: FONT }, u: { fontSize: 15, color, padding: [8, 0, 0, 2] } } },
      data: [{ value: score }],
    }],
  }
}
