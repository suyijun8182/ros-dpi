<template>
  <!-- 登录 / 安装向导版式：左侧等距插画，右侧大标题 + 圆角卡片（参考维盟登录页的构图，插画自绘） -->
  <div class="auth">
    <div class="art" aria-hidden="true">
      <svg viewBox="0 0 560 460" class="scene">
        <!-- 地面等距网格：两组分别平行于 (2,1) 和 (2,-1) 方向，边缘淡出 -->
        <defs>
          <radialGradient id="fade" cx="50%" cy="55%" r="50%"><stop offset="0" stop-color="#fff" stop-opacity="1" /><stop offset="1" stop-color="#fff" stop-opacity="0" /></radialGradient>
          <mask id="gm"><rect width="560" height="460" fill="url(#fade)" /></mask>
        </defs>
        <g stroke="var(--grid)" stroke-width="1.2" mask="url(#gm)">
          <path v-for="k in 13" :key="'u' + k" :d="`M${280 + (k - 7) * 40 - 240} ${255 - (k - 7) * 20 - 120} l480 240`" />
          <path v-for="k in 13" :key="'v' + k" :d="`M${280 + (k - 7) * 40 - 240} ${255 + (k - 7) * 20 + 120} l480 -240`" />
        </g>
        <!-- 平台 -->
        <path d="M280 150 L470 245 L280 340 L90 245 Z" fill="var(--plate)" />
        <path d="M90 245 L280 340 L280 362 L90 267 Z" fill="var(--plate-l)" />
        <path d="M280 340 L470 245 L470 267 L280 362 Z" fill="var(--plate-r)" />
        <!-- 流量线：从路由器流向三个应用色块 -->
        <path d="M280 236 C 330 260, 360 262, 398 280" stroke="#4fd0cf" stroke-width="5" fill="none" stroke-linecap="round" />
        <path d="M280 236 C 230 262, 200 266, 162 282" stroke="#f0954a" stroke-width="5" fill="none" stroke-linecap="round" />
        <path d="M280 236 C 282 270, 284 292, 286 318" stroke="#5a92e8" stroke-width="5" fill="none" stroke-linecap="round" />
        <!-- 三个应用色块（小立方） -->
        <g v-for="c in cubes" :key="c.x">
          <path :d="`M${c.x} ${c.y} l22 11 l-22 11 l-22 -11 Z`" :fill="c.top" />
          <path :d="`M${c.x - 22} ${c.y + 11} l22 11 v24 l-22 -11 Z`" :fill="c.l" />
          <path :d="`M${c.x} ${c.y + 22} l22 -11 v24 l-22 11 Z`" :fill="c.r" />
        </g>
        <!-- 路由器底座光圈 -->
        <ellipse cx="280" cy="236" rx="74" ry="37" fill="#2b6583" opacity=".18" />
        <ellipse cx="280" cy="236" rx="50" ry="25" fill="#4fd0cf" opacity=".28" />
        <!-- 路由器 -->
        <path d="M280 186 L340 216 L280 246 L220 216 Z" fill="#4fd0cf" />
        <path d="M220 216 L280 246 L280 262 L220 232 Z" fill="#2db3b4" />
        <path d="M280 246 L340 216 L340 232 L280 262 Z" fill="#22999b" />
        <g stroke="#2b6583" stroke-width="5" stroke-linecap="round">
          <path d="M244 205 V160" /><path d="M262 197 V150" /><path d="M298 197 V150" /><path d="M316 205 V160" />
        </g>
        <circle cx="300" cy="226" r="3" fill="#ffffff" /><circle cx="312" cy="220" r="3" fill="#ffffff" />
        <!-- 上方的三层分层（logo 的意象） -->
        <g transform="translate(400 70)">
          <path d="M0 52 L40 72 L0 92 L-40 72 Z" fill="var(--layer)" />
          <path d="M0 30 L40 50 L0 70 L-40 50 Z" fill="#6aa0bd" />
          <path d="M0 8 L40 28 L0 48 L-40 28 Z" fill="#4fd0cf" />
          <circle cx="0" cy="28" r="4" fill="#ffffff" />
        </g>
        <path d="M400 168 C 400 190, 360 196, 330 200" stroke="var(--dash)" stroke-width="2" stroke-dasharray="4 6" fill="none" />
        <!-- 点缀 -->
        <g fill="none" stroke="var(--deco)" stroke-width="2.5" stroke-linecap="round">
          <path d="M96 120 h14 M103 113 v14" /><path d="M500 360 h12 M506 354 v12" /><circle cx="150" cy="80" r="7" />
        </g>
      </svg>
    </div>
    <div class="side">
      <div class="head">
        <Logo big />
        <h1>{{ t('auth.headline') }}</h1>
        <p class="muted">{{ t('auth.tagline') }}</p>
      </div>
      <slot />
      <div class="foot">
        <button type="button" class="btn ghost sm" @click="setLang(locale === 'zh' ? 'en' : 'zh')">{{ t('common.lang') }}</button>
        <button type="button" class="btn ghost sm" @click="toggleTheme">{{ t('common.theme') }}</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import { setLang } from '../i18n/index.js'
import { toggleTheme } from '../state.js'
import Logo from './Logo.vue'

const { t, locale } = useI18n()
const cubes = [
  { x: 162, y: 270, top: '#f6b27a', l: '#e0782c', r: '#c9681f' },
  { x: 286, y: 306, top: '#8bb4f0', l: '#2f6fcb', r: '#2a5fae' },
  { x: 398, y: 268, top: '#8fe3e2', l: '#2db3b4', r: '#22999b' },
]
</script>

<style scoped>
.auth {
  --grid: rgba(43, 101, 131, .12); --plate: #ffffff; --plate-l: #dfe4f3; --plate-r: #cfd6ec; --layer: #eaf2f6;
  --dash: rgba(43, 101, 131, .45); --deco: rgba(98, 80, 214, .35);
  min-height: 100vh; display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(360px, 1fr); align-items: center; gap: 24px;
  padding: 24px clamp(16px, 5vw, 80px);
  background: radial-gradient(1200px 600px at 20% 30%, #f7f8fd, transparent), linear-gradient(135deg, #f4f5fb 0%, #e6e8f4 100%);
}
:root[data-theme="dark"] .auth { --plate: #1f2830; --plate-l: #18202a; --plate-r: #151c24; --layer: #2a3a46; --grid: rgba(116, 176, 209, .08); background: linear-gradient(135deg, #141a20 0%, #10151a 100%); }
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) .auth { --plate: #1f2830; --plate-l: #18202a; --plate-r: #151c24; --layer: #2a3a46; --grid: rgba(116, 176, 209, .08); background: linear-gradient(135deg, #141a20 0%, #10151a 100%); }
}
.art { display: grid; place-items: center; }
.scene { width: 100%; max-width: 620px; height: auto; }
.side { display: flex; flex-direction: column; gap: 22px; max-width: 440px; width: 100%; justify-self: center; }
.head { display: grid; gap: 10px; }
h1 { font: 700 30px/1.25 var(--sans); margin: 8px 0 0; text-wrap: balance; }
.head p { margin: 0; font-size: 14px; }
.foot { display: flex; gap: 8px; justify-content: center; }
:slotted(.box) { background: var(--panel); border-radius: 18px; padding: 26px 26px 22px; box-shadow: 0 18px 50px rgba(43, 60, 110, .10); display: flex; flex-direction: column; gap: 14px; }
@media (max-width: 900px) {
  .auth { grid-template-columns: 1fr; padding-top: 32px; }
  .art { display: none; }
}
</style>
