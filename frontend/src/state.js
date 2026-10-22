import { reactive, watch } from 'vue'

function read(k, d) {
  try { return localStorage.getItem(k) || d } catch (e) { return d }
}

const media = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null
const systemTheme = () => (media && media.matches ? 'dark' : 'light')

// 全局时间范围，各页面共用；主题默认跟随系统
export const ui = reactive({
  range: ({ last7: 'week', last30: 'month' })[read('rosdpi.range', 'today')] || read('rosdpi.range', 'today'),
  theme: document.documentElement.dataset.theme || systemTheme(),
  trendMode: read('rosdpi.trendMode', 'pair'),    // 历史流量：pair 上下行合计 | groups 按应用大类
  rateUnit: read('rosdpi.rateUnit', 'bit'),        // 速率单位：bit（bit/s）| byte（Byte/s）
  side: read('rosdpi.side', 'full'),               // 侧边栏：full 图标 + 文字 | mini 只有图标
})

media && media.addEventListener && media.addEventListener('change', () => {
  if (!document.documentElement.dataset.theme) ui.theme = systemTheme()
})

watch(() => ui.range, v => { try { localStorage.setItem('rosdpi.range', v) } catch (e) { /* ignore */ } })
watch(() => ui.rateUnit, v => { try { localStorage.setItem('rosdpi.rateUnit', v) } catch (e) { /* ignore */ } })
watch(() => ui.side, v => { try { localStorage.setItem('rosdpi.side', v) } catch (e) { /* ignore */ } })
watch(() => ui.trendMode, v => { try { localStorage.setItem('rosdpi.trendMode', v) } catch (e) { /* ignore */ } })

export function toggleTheme() {
  ui.theme = ui.theme === 'dark' ? 'light' : 'dark'
  document.documentElement.dataset.theme = ui.theme
  try { localStorage.setItem('rosdpi.theme', ui.theme) } catch (e) { /* ignore */ }
}

// 时间范围：今日 / 昨日 / 本周 / 本月。“近 7 天 / 近 30 天”和本周、本月重复，界面上不再提供（debug10）
export const RANGES = ['today', 'yesterday', 'week', 'month']
