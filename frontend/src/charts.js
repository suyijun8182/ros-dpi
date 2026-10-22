// ECharts 配置生成。颜色从 CSS 变量读取，切换主题/语言后重新生成即可。
// 规范（dataviz）：细线 2px、发丝网格、2px 底色间隙分隔色块、颜色跟随实体（应用大类）而不是排名、
// 只给关键点（峰值）直接标注，其余交给图例、提示框和旁边的数值表。
import { appName, bytes, catHex, catName, groupHex, groupName, pct, rate } from './format.js'
import { i18n } from './i18n/index.js'

const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim()
const t = (k, p) => i18n.global.t(k, p)
const FONT = '"Barlow Semi Condensed", "Barlow", "PingFang SC", "Microsoft YaHei", sans-serif'
const STEP = { minute: 60, hour: 3600, day: 86400 }

function tooltip(extra = {}) {
  return {
    backgroundColor: css('--panel'), borderColor: css('--line-strong'), borderWidth: 1, padding: [8, 12],
    textStyle: { color: css('--ink'), fontSize: 13, fontFamily: FONT }, extraCssText: 'box-shadow:0 4px 16px rgba(0,0,0,.08);border-radius:6px', ...extra,
  }
}

function fmtTime(ts, gran) {
  const d = new Date(ts * 1000)
  const p = n => String(n).padStart(2, '0')
  if (gran === 'day') return `${d.getMonth() + 1}/${d.getDate()}`
  return `${p(d.getHours())}:${p(d.getMinutes())}`
}

function axes(labels, gran, fmt) {
  return {
    xAxis: {
      type: 'category', boundaryGap: gran === 'day', data: labels,
      axisLine: { lineStyle: { color: css('--line-strong') } }, axisTick: { show: false },
      axisLabel: { color: css('--faint'), hideOverlap: true, fontFamily: FONT, fontSize: 12 },
    },
    yAxis: {
      type: 'value', splitNumber: 4,
      splitLine: { lineStyle: { color: css('--line') } },
      axisLabel: { color: css('--faint'), fontFamily: FONT, fontSize: 12, formatter: v => (v === 0 ? '0' : fmt(v).replace('.0 ', ' ')) },
    },
  }
}

const legend = () => ({ top: 0, left: 0, icon: 'roundRect', itemWidth: 10, itemHeight: 10, itemGap: 14,
  textStyle: { color: css('--muted'), fontFamily: FONT, fontSize: 13 } })

/** 上下行趋势：下行（蓝）在上、上行（橙）以负值画在零线下方，像一对双绞线。峰值直接标注。 */
export function trendOption(points, gran = 'hour', asRate = false) {
  const val = v => (asRate ? v / STEP[gran] : v)
  const fmt = v => (asRate ? rate(Math.abs(v)) : bytes(Math.abs(v)))
  const down = css('--down'), up = css('--up')
  const series = (name, key, color, sign) => ({
    name, type: gran === 'day' ? 'bar' : 'line', barMaxWidth: 14, barGap: '-100%',
    smooth: 0.25, symbol: 'none', lineStyle: { width: 2, color },
    areaStyle: gran === 'day' ? undefined : { color, opacity: 0.16 },
    itemStyle: { color, borderRadius: sign > 0 ? [4, 4, 0, 0] : [0, 0, 4, 4] },
    data: points.map(p => sign * val(p[key])),
    // 只标下行峰值：一个数字讲清"最忙的时候有多忙"
    markPoint: sign > 0 && points.some(p => p[key] > 0) ? {
      symbol: 'circle', symbolSize: 7, itemStyle: { color, borderColor: css('--panel'), borderWidth: 2 },
      label: { position: 'top', distance: 6, color: css('--muted'), fontFamily: FONT, fontSize: 12, formatter: p => t('chart.peak', { v: fmt(p.value) }) },
      data: [{ type: 'max' }],
    } : undefined,
  })
  return {
    textStyle: { fontFamily: FONT },
    grid: { left: 4, right: 12, top: 34, bottom: 2, containLabel: true },
    legend: legend(),
    tooltip: tooltip({ trigger: 'axis', axisPointer: { type: 'line', lineStyle: { color: css('--line-strong') } }, valueFormatter: fmt }),
    ...axes(points.map(p => fmtTime(p.ts, gran)), gran, fmt),
    series: [series(t('common.down'), 'down', down, 1), series(t('common.up'), 'up', up, -1)],
  }
}

/** 按应用大类堆叠的趋势（Panabit 的"应用流量趋势"）。最多 7 个大类 + 其他，颜色固定跟随大类。 */
export function stackedOption(tg, asRate = false) {
  const step = tg.step || STEP[tg.gran]
  const fmt = v => (asRate ? rate(v) : bytes(v))
  const panel = css('--panel')
  const series = tg.series.map(s => {
    const color = s.id === '__other' ? css('--line-strong') : groupHex(s.id)
    return {
      name: groupName(s), id: s.id, type: tg.gran === 'day' ? 'bar' : 'line', stack: 'all',
      smooth: 0.2, symbol: 'none', barMaxWidth: 18,
      lineStyle: { width: 1, color: panel }, areaStyle: { color, opacity: 0.88 },
      // 堆叠柱之间留 2px 底色间隙，代替描边
      itemStyle: { color, borderColor: panel, borderWidth: tg.gran === 'day' ? 1 : 0 },
      emphasis: { focus: 'series' },
      data: s.values.map(v => (asRate ? v / step : v)),
    }
  })
  return {
    textStyle: { fontFamily: FONT },
    grid: { left: 4, right: 12, top: 58, bottom: 2, containLabel: true },
    legend: { ...legend(), type: 'scroll' },
    tooltip: tooltip({
      trigger: 'axis', axisPointer: { type: 'line', lineStyle: { color: css('--line-strong') } },
      formatter: ps => {
        const sum = ps.reduce((a, p) => a + (p.value || 0), 0)
        const rows = ps.filter(p => p.value > 0).sort((a, b) => b.value - a.value)
          .map(p => `<div style="display:flex;gap:14px;justify-content:space-between"><span>${p.marker}${p.seriesName}</span><b>${fmt(p.value)}</b></div>`)
        return `<div style="min-width:180px">${ps[0]?.axisValue ?? ''}　<b>${fmt(sum)}</b>${rows.join('')}</div>`
      },
    }),
    ...axes(tg.ts.map(ts => fmtTime(ts, tg.gran)), tg.gran, fmt),
    series,
  }
}

/** 构成环图：内环 = 应用大类，外环 = 小类（同色深浅）。数值和名称在旁边的图例表里，图上不放文字。 */
export function donutOption(groups) {
  const panel = css('--panel')
  const sum = groups.reduce((a, g) => a + g.total, 0) || 1
  const ring = { type: 'pie', startAngle: 90, avoidLabelOverlap: false, label: { show: false }, labelLine: { show: false },
    itemStyle: { borderColor: panel, borderWidth: 2, borderRadius: 3 }, emphasis: { scale: true, scaleSize: 4 } }
  const gs = groups.filter(g => g.total > 0)
  return {
    tooltip: tooltip({
      trigger: 'item',
      formatter: p => `${p.marker}${p.name}<br/><b>${bytes(p.value)}</b>　<span style="color:${css('--muted')}">${pct(p.value / sum)}</span>`,
    }),
    series: [
      { ...ring, name: 'group', radius: ['42%', '63%'],
        data: gs.map(g => ({ name: groupName(g), value: g.total, id: g.id, kind: 'group', itemStyle: { color: groupHex(g.id) } })) },
      { ...ring, name: 'category', radius: ['67%', '84%'],
        data: gs.flatMap(g => g.children.filter(c => c.total > 0).map(c => ({
          name: `${groupName(g)} · ${catName(c)}`, value: c.total, id: c.id, kind: 'category', itemStyle: { color: catHex(c.id) },
        }))) },
    ],
  }
}

/** 流向桑基图：终端 → 应用大类 → 应用 */
export function sankeyOption(graph) {
  const ink = css('--ink'), muted = css('--muted')
  const label = n => {
    if (n.kind === 'host') return n.key ? n.name : t('flow.otherHosts')
    if (n.kind === 'group') return groupName(n)
    if (!n.app) {
      const g = graph.nodes.find(x => x.id === `g:${n.group}`)
      return t('flow.otherApps', { cat: g ? groupName(g) : '' })
    }
    return appName(n)
  }
  const minLabel = (graph.total || 0) * 0.012
  const idx = new Map(graph.nodes.map((n, i) => [n.id, i]))
  const color = n => (n.kind === 'host' ? (n.online ? css('--pair-green') : css('--line-strong'))
    : n.kind === 'app' && n.category ? catHex(n.category) : groupHex(n.group))
  const share = v => pct(v / (graph.total || 1), 0)
  return {
    textStyle: { fontFamily: FONT },
    tooltip: tooltip({
      trigger: 'item',
      formatter: p => (p.dataType === 'edge'
        ? `${label(p.data.s)} → ${label(p.data.tg)}<br/><b>${bytes(p.data.value)}</b>　<span style="color:${css('--down')}">↓${bytes(p.data.down)}</span>　<span style="color:${css('--up')}">↑${bytes(p.data.up)}</span>`
        : `${p.name}<br/><b>${bytes(p.value)}</b>　<span style="color:${muted}">${share(p.value)}</span>`),
    }),
    series: [{
      type: 'sankey', left: 4, right: 170, top: 8, bottom: 8, nodeWidth: 12, nodeGap: 10, draggable: false,
      layoutIterations: 48, emphasis: { focus: 'adjacency' },
      // 占比太小的节点挤在一起时标签会重叠，只在悬停时通过提示框查看
      label: {
        color: ink, fontFamily: FONT, fontSize: 13, rich: { v: { color: muted, fontSize: 12 } },
        formatter: p => (p.value < minLabel ? '' : `${p.name}  {v|${bytes(p.value)} · ${share(p.value)}}`),
      },
      // 连线颜色取下游节点（大类/应用），一眼看出流量去了哪类应用
      lineStyle: { color: 'target', opacity: 0.28, curveness: 0.5 },
      itemStyle: { borderWidth: 0, borderRadius: 2 },
      data: graph.nodes.map(n => ({ name: label(n), id: n.id, raw: n, itemStyle: { color: color(n) } })),
      // 用下标连线：终端备注名可能和应用/分类重名
      links: graph.links.map(l => {
        const si = idx.get(l.source), ti = idx.get(l.target)
        return { source: si, target: ti, value: l.value, up: l.up, down: l.down, s: graph.nodes[si], tg: graph.nodes[ti] }
      }),
    }],
  }
}

/** 健康指数仪表盘：维盟首页那种刻度弧 + 中间大分数。分段颜色用状态色（差 / 中 / 良 / 优）。 */
export function gaugeOption(score) {
  const color = score >= 90 ? css('--accent') : score >= 75 ? css('--pair-blue') : score >= 60 ? css('--warn') : css('--bad')
  return {
    series: [{
      type: 'gauge', startAngle: 205, endAngle: -25, min: 0, max: 100, radius: '92%', center: ['50%', '60%'],
      progress: { show: true, width: 10, roundCap: true, itemStyle: { color } },
      axisLine: { roundCap: true, lineStyle: { width: 10, color: [[1, css('--sunk')]] } },
      axisTick: { distance: -24, length: 6, splitNumber: 4, lineStyle: { color: css('--line-strong'), width: 1 } },
      splitLine: { distance: -26, length: 9, lineStyle: { color: css('--line-strong'), width: 2 } },
      axisLabel: { show: false },
      pointer: { show: false }, anchor: { show: false }, title: { show: false },
      detail: { valueAnimation: true, offsetCenter: [0, '-2%'], fontFamily: FONT, fontSize: 38, fontWeight: 600, color: css('--ink'),
        formatter: v => `${Math.round(v)}` },
      data: [{ value: score }],
    }],
  }
}

/** 在线终端数随时间：单条线，不需要图例（标题说明是什么） */
export function onlineOption(points, gran = 'minute', compact = false) {
  const color = css('--accent')
  return {
    textStyle: { fontFamily: FONT },
    grid: compact ? { left: 0, right: 0, top: 4, bottom: 0 } : { left: 4, right: 12, top: 16, bottom: 2, containLabel: true },
    tooltip: tooltip({ trigger: 'axis', axisPointer: { type: 'line', lineStyle: { color: css('--line-strong') } },
      valueFormatter: v => t('overview.hostsN', { n: v }) }),
    xAxis: { type: 'category', show: !compact, boundaryGap: false, data: points.map(p => fmtTime(p.ts, gran)),
      axisLine: { lineStyle: { color: css('--line-strong') } }, axisTick: { show: false },
      axisLabel: { color: css('--faint'), hideOverlap: true, fontFamily: FONT, fontSize: 12 } },
    yAxis: { type: 'value', show: !compact, minInterval: 1, splitNumber: 4, splitLine: { lineStyle: { color: css('--line') } },
      axisLabel: { color: css('--faint'), fontFamily: FONT, fontSize: 12 } },
    series: [{ type: 'line', name: t('overview.online'), smooth: 0.25, symbol: 'none', step: false,
      lineStyle: { width: 2, color }, areaStyle: { color, opacity: compact ? 0.18 : 0.12 }, data: points.map(p => p.n) }],
  }
}
