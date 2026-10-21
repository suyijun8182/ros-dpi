import axios from 'axios'
import { reactive } from 'vue'
import router from './router.js'

export const auth = reactive({ token: read('rosdpi.token'), username: read('rosdpi.user') })

function read(k) {
  try { return localStorage.getItem(k) || '' } catch (e) { return '' }
}

export function setAuth(token, username) {
  auth.token = token || ''
  auth.username = username || ''
  try {
    if (token) { localStorage.setItem('rosdpi.token', token); localStorage.setItem('rosdpi.user', username) }
    else { localStorage.removeItem('rosdpi.token'); localStorage.removeItem('rosdpi.user') }
  } catch (e) { /* ignore */ }
}

const http = axios.create({ baseURL: '/api', timeout: 20000 })

http.interceptors.request.use(cfg => {
  if (auth.token) cfg.headers.Authorization = `Bearer ${auth.token}`
  return cfg
})

http.interceptors.response.use(r => r.data, err => {
  if (err.response?.status === 503 && !err.config.url.startsWith('/setup/')) {
    setupState.configured = false
    router.push({ name: 'setup' })
  } else if (err.response?.status === 401 && !err.config.url.startsWith('/auth/')) {
    setAuth('')
    router.push({ name: 'login', query: { next: router.currentRoute.value.fullPath } })
  }
  err.message = err.response?.data?.detail || err.message
  return Promise.reject(err)
})

// 安装向导状态：数据库是否已配置（未配置时所有页面都先进入 /setup）
export const setupState = reactive({ checked: false, configured: true, present: true })

export async function checkSetup() {
  const r = await http.get('/setup/status')
  Object.assign(setupState, { checked: true, configured: r.configured, present: r.config_present })
  return setupState
}

export const enc = s => encodeURIComponent(s)
export default http
