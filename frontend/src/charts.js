// ECharts 配置生成。颜色从 CSS 变量读取，切换主题/语言后重新生成即可。
import { appName, bytes, catColor, rate } from './format.js'
import { i18n } from './i18n/index.js'

const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim()
const t = (k, p) => i18n.global.t(k, p)
const FONT = '"Barlow Semi Condensed", "Barlow", "PingFang SC", "Microsoft YaHei", sans-serif'

function tooltip(extra = {}) {
  return {
    backgroundColor: css('--panel'), borderColor: css('--line-strong'), borderWidth: 1, padding: [8, 12],
    textStyle: { color: css('--ink'), fontSize: 13, fontFamily: FONT }, extraCssText: 'box-shadow:none;border-radius:6px', ...extra,
  }
}

function fmtTime(ts, gran) {
  const d = new Date(ts * 1000)
  const p = n => String(n).padStart(2, '0')
  if (gran === 'day') return `${d.getMonth() + 1}/${d.getDate()}`
  return `${p(d.getHours())}:${p(d.getMinutes())}`
}

/** 上下行趋势：下行（蓝）在上、上行（橙）以负值画在零线下方，像一对双绞线。 */
export function trendOption(points, gran = 'hour', asRate = false) {
  const step = { minute: 60, hour: 3600, day: 86400 }[gran]
  const val = v => (asRate ? v / step : v)
  const fmt = v => (asRate ? rate(Math.abs(v)) : bytes(Math.abs(v)))
  const down = css('--down'), up = css('--up')
  const series = (name, key, color, sign) => ({
    name, type: gran === 'day' ? 'bar' : 'line', barMaxWidth: 14, barGap: '-100%',
    smooth: 0.25, symbol: 'none', lineStyle: { width: 1.5, color },
    areaStyle: gran === 'day' ? undefined : { color, opacity: 0.22 },
    itemStyle: { color, borderRadius: sign > 0 ? [2, 2, 0, 0] : [0, 0, 2, 2] },
    data: points.map(p => sign * val(p[key])),
  })
  return {
    textStyle: { fontFamily: FONT },
    grid: { left: 4, right: 8, top: 30, bottom: 2, containLabel: true },
    legend: { top: 0, left: 0, icon: 'rect', itemWidth: 12, itemHeight: 3, textStyle: { color: css('--muted'), fontFamily: FONT, fontSize: 13 } },
    tooltip: tooltip({ trigger: 'axis', axisPointer: { type: 'line', lineStyle: { color: css('--line-strong') } }, valueFormatter: fmt }),
    xAxis: {
      type: 'category', boundaryGap: gran === 'day', data: points.map(p => fmtTime(p.ts, gran)),
      axisLine: { show: false }, axisTick: { show: false },
      axisLabel: { color: css('--faint'), hideOverlap: true, fontFamily: FONT, fontSize: 12 },
    },
    yAxis: {
      type: 'value', splitNumber: 4,
      splitLine: { lineStyle: { color: css('--line') } },
      axisLabel: { color: css('--faint'), fontFamily: FONT, fontSize: 12, formatter: v => (v === 0 ? '0' : fmt(v).replace('.0 ', ' ')) },
    },
    series: [series(t('common.down'), 'down', down, 1), series(t('common.up'), 'up', up, -1)],
  }
}

/** 流向桑基图：终端 → 分类 → 应用 */
export function sankeyOption(graph) {
  const zh = i18n.global.locale.value === 'zh'
  const ink = css('--ink'), muted = css('--muted')
  const label = n => {
    if (n.kind === 'host') return n.key ? n.name : t('flow.otherHosts')
    if (n.kind === 'category') return zh ? n.name : n.name_en
    if (!n.app) {
      const cat = graph.nodes.find(x => x.id === `c:${n.category}`)
      return t('flow.otherApps', { cat: cat ? (zh ? cat.name : cat.name_en) : '' })
    }
    return appName(n)
  }
  const minLabel = (graph.total || 0) * 0.012
  const idx = new Map(graph.nodes.map((n, i) => [n.id, i]))
  const color = n => (n.kind === 'host' ? (n.online ? css('--pair-green') : css('--line-strong')) : catColor(n.category))
  return {
    textStyle: { fontFamily: FONT },
    tooltip: tooltip({
      trigger: 'item',
      formatter: p => (p.dataType === 'edge'
        ? `${label(p.data.s)} → ${label(p.data.tg)}<br/><b>${bytes(p.data.value)}</b>　<span style="color:${css('--down')}">↓${bytes(p.data.down)}</span>　<span style="color:${css('--up')}">↑${bytes(p.data.up)}</span>`
        : `${p.name}<br/><b>${bytes(p.value)}</b>`),
    }),
    series: [{
      type: 'sankey', left: 4, right: 150, top: 8, bottom: 8, nodeWidth: 10, nodeGap: 9, draggable: false,
      layoutIterations: 48, emphasis: { focus: 'adjacency' },
      // 占比太小的节点挤在一起时标签会重叠，只在悬停时通过提示框查看
      label: {
        color: ink, fontFamily: FONT, fontSize: 13, rich: { v: { color: muted, fontSize: 12 } },
        formatter: p => (p.value < minLabel ? '' : `${p.name}  {v|${bytes(p.value)}}`),
      },
      lineStyle: { color: 'gradient', opacity: 0.32, curveness: 0.5 },
      itemStyle: { borderWidth: 0 },
      data: graph.nodes.map(n => ({ name: label(n), id: n.id, raw: n, itemStyle: { color: color(n) } })),
      // 用下标连线：终端备注名可能和应用/分类重名
      links: graph.links.map(l => {
        const si = idx.get(l.source), ti = idx.get(l.target)
        return { source: si, target: ti, value: l.value, up: l.up, down: l.down, s: graph.nodes[si], tg: graph.nodes[ti] }
      }),
    }],
  }
}
