import React, { useState, useRef, useCallback, useEffect } from 'react'
import { getPlugins, type Plugin } from './lib/api'
import { toast } from './lib/toast'
import PluginView from './components/plugin-view'
import Settings from './components/settings'
import ReactAppView from './components/react-app-view'
import PageHeader from './components/page-header'
import { AppCard, type AppItem } from './components/app-card'

// ── themes ────────────────────────────────────────────────────────────────────

interface Theme {
  id: string
  name: string
  primary: string      // main brand
  light: string        // light tint bg  e.g. card/secondary
  muted: string        // very light bg
  border: string       // hairline
  dark: string         // deep text / dark shade
  mid: string          // medium text
  faint: string        // placeholder / faint
  gradient: [string, string]  // logo gradient
}

const THEMES: Theme[] = [
  {
    id: 'cyan',
    name: '青春蓝',
    primary:  '#06b6d4',
    light:    '#e0f7fa',
    muted:    '#eaf6f9',
    border:   '#cce9f0',
    dark:     '#0d1f26',
    mid:      '#5b8fa0',
    faint:    '#9bb8c3',
    gradient: ['#06b6d4', '#22d3ee'],
  },
  {
    id: 'violet',
    name: '梦幻紫',
    primary:  '#7c3aed',
    light:    '#ede9fe',
    muted:    '#f5f3ff',
    border:   '#ddd6fe',
    dark:     '#1e1033',
    mid:      '#6d5a9e',
    faint:    '#a899cc',
    gradient: ['#7c3aed', '#a78bfa'],
  },
  {
    id: 'rose',
    name: '珊瑚粉',
    primary:  '#f43f5e',
    light:    '#ffe4e6',
    muted:    '#fff1f2',
    border:   '#fecdd3',
    dark:     '#2d0a12',
    mid:      '#9f4455',
    faint:    '#c98090',
    gradient: ['#f43f5e', '#fb7185'],
  },
  {
    id: 'emerald',
    name: '自然绿',
    primary:  '#059669',
    light:    '#d1fae5',
    muted:    '#ecfdf5',
    border:   '#a7f3d0',
    dark:     '#052e16',
    mid:      '#2d7a58',
    faint:    '#6dab8e',
    gradient: ['#059669', '#34d399'],
  },
  {
    id: 'amber',
    name: '暖阳橙',
    primary:  '#d97706',
    light:    '#fef3c7',
    muted:    '#fffbeb',
    border:   '#fde68a',
    dark:     '#271a00',
    mid:      '#92600a',
    faint:    '#c49a3c',
    gradient: ['#d97706', '#fbbf24'],
  },
  {
    id: 'slate',
    name: '烟灰蓝',
    primary:  '#475569',
    light:    '#e2e8f0',
    muted:    '#f1f5f9',
    border:   '#cbd5e1',
    dark:     '#0f172a',
    mid:      '#64748b',
    faint:    '#94a3b8',
    gradient: ['#475569', '#94a3b8'],
  },
  {
    id: 'indigo',
    name: '深邃靛',
    primary:  '#4f46e5',
    light:    '#e0e7ff',
    muted:    '#eef2ff',
    border:   '#c7d2fe',
    dark:     '#1e1b4b',
    mid:      '#5a5299',
    faint:    '#8b83c8',
    gradient: ['#4f46e5', '#818cf8'],
  },
  {
    id: 'pink',
    name: '糖果粉',
    primary:  '#db2777',
    light:    '#fce7f3',
    muted:    '#fdf2f8',
    border:   '#fbcfe8',
    dark:     '#3b0022',
    mid:      '#9d3a6a',
    faint:    '#c47a9a',
    gradient: ['#db2777', '#f472b6'],
  },
]

function hexToRgb(hex: string) {
  const r = parseInt(hex.slice(1,3),16)
  const g = parseInt(hex.slice(3,5),16)
  const b = parseInt(hex.slice(5,7),16)
  return `${r} ${g} ${b}`
}

/** 按比例混合两个颜色（ratio 为 b 的占比），用于从品牌色派生整套界面层色。 */
function mix(a: string, b: string, ratio: number): string {
  const A = [1,3,5].map((i) => parseInt(a.slice(i, i + 2), 16))
  const B = [1,3,5].map((i) => parseInt(b.slice(i, i + 2), 16))
  return '#' + A.map((v, i) => Math.round(v * (1 - ratio) + B[i] * ratio).toString(16).padStart(2, '0')).join('')
}

/** WCAG 相对亮度（0 = 黑，1 = 白）。 */
function relLum(hex: string) {
  const chan = (v: number) => {
    const s = v / 255
    return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
  }
  const [r, g, b] = [1, 3, 5].map((i) => chan(parseInt(hex.slice(i, i + 2), 16)))
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

/** 两色的 WCAG 对比度。 */
function contrast(a: string, b: string) {
  const [hi, lo] = [relLum(a), relLum(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

/**
 * 让品牌原色尽量少地偏离，只调到「与指定文字色的对比度达标」为止：
 * 文字是深色就往白里提，文字是白色就往暗里压；返回调整后的颜色与实际混合比例。
 */
function leastMix(base: string, toward: string, fg: string, target = 4.5) {
  for (let r = 0; r <= 0.6; r += 0.02) {
    const c = mix(base, toward, r)
    if (contrast(c, fg) >= target) return { color: c, ratio: r }
  }
  return { color: mix(base, toward, 0.6), ratio: 0.6 }
}

/**
 * 主题变量。
 *
 * 内容区底色与面板统一为纯白，层次**不靠明度差**，改由发丝描边 + 中性阴影承担
 * （拖动/悬浮/选中态仍有明确的色块与描边反馈）；文字三层由品牌色派生，
 * 8 套主题共用同一套「亮度曲线」：
 * - 白底上的主题色文字走压深版 --primary-ink（正文约 12:1，次级与主题色文字都达到 AA）；
 * - 按钮 / 选中态的**填充**直接用品牌原色，只在对比度不够时才最少限度地偏离，
 *   文字色（--primary-foreground）在这条路上自动选黑或白，避免整片界面被压暗；
 * - 输入框、空态底等「凹陷」位置用 rgba(hairline / 0.05) 的微灰，保留结构感；
 * - 阴影统一走中性色，不再用主题色发光，避免白底上的彩色光晕。
 */
function themeVars(t: Theme): Record<string, string> {
  const canvas = '#ffffff'                      // 内容区底色：纯白
  const surface = '#ffffff'                     // 面板 / 卡片：同为白色，靠描边与阴影浮起
  const foreground = mix(t.dark, t.mid, 0.22)
  const mutedFg = mix(t.mid, t.dark, 0.3)
  const faint = mix(t.faint, t.dark, 0.24)
  const ink = mix(t.primary, t.dark, 0.45)      // 主题色的可读版本：白底上的文字 / 图标 / 数字
  // 填充底色：在「白字」与「深字」两条路里，取偏离原色更小的那条，保住鲜艳且文字达到 AA
  const forWhite = leastMix(t.primary, t.dark, '#ffffff')
  const forDark = leastMix(t.primary, '#ffffff', t.dark)
  const useDarkText = forDark.ratio <= forWhite.ratio
  const fill = useDarkText ? forDark.color : forWhite.color
  const onFill = useDarkText ? t.dark : '#ffffff'
  // 渐变终点朝文字的反方向再走一点，保证整条渐变上的对比度都不低于起点
  const fillEnd = useDarkText ? mix(fill, '#ffffff', 0.14) : mix(fill, t.dark, 0.14)
  return {
    '--background': canvas,
    '--foreground': foreground,
    '--card': surface,
    '--card-foreground': foreground,
    '--primary': t.primary,
    '--primary-rgb': hexToRgb(t.primary),
    '--primary-ink': ink,
    '--primary-ink-rgb': hexToRgb(ink),
    '--primary-foreground': onFill,
    '--secondary': t.light,
    '--secondary-foreground': mutedFg,
    '--muted': mix(t.muted, t.dark, 0.05),
    '--muted-foreground': mutedFg,
    '--accent': t.gradient[1],
    '--accent-foreground': t.dark,
    '--border': mix(t.border, t.dark, 0.12),
    '--ring': t.primary,
    '--color-mid': mutedFg,
    '--color-faint': faint,
    '--color-light': t.light,
    '--surface': surface,
    '--surface-rgb': hexToRgb(surface),
    '--hairline-rgb': hexToRgb(mix(t.dark, t.muted, 0.35)),
    '--shadow-rgb': hexToRgb(mix(t.dark, t.primary, 0.18)),
    // 品牌渐变：logo / 头像装饰用原色；按钮与选中态用「原色 → 微调」的填充渐变
    '--gradient-start': t.gradient[0],
    '--gradient-end': t.gradient[1],
    '--fill': fill,
    '--fill-gradient': `linear-gradient(135deg, ${fill}, ${fillEnd})`,
  }
}

// ── data ──────────────────────────────────────────────────────────────────────

// 侧栏导航：插件清单里没有分类字段，这些分类菜单点开永远是空列表，故只保留「全部应用」
const NAV_ITEMS = [
  { id: 'all', label: '全部应用', icon: GridIcon },
]

const CARD_COLORS = [
  '#06b6d4', '#7c3aed', '#f43f5e', '#059669',
  '#d97706', '#475569', '#4f46e5', '#db2777',
  '#0d9488', '#dc2626', '#ea580c', '#0284c7',
]

// 由插件 id 稳定派生卡片强调色（仅用于卡片装饰，不改变整体视觉）
function colorForId(id: string): string {
  let h = 0
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0
  return CARD_COLORS[h % CARD_COLORS.length]
}

const THEME_KEY = 'desktop:theme'
const PINNED_KEY = 'desktop:pinned'

function loadTheme(): Theme {
  const id = localStorage.getItem(THEME_KEY)
  return THEMES.find((t) => t.id === id) ?? THEMES[0]
}

function loadPinned(): string[] {
  try {
    const raw = localStorage.getItem(PINNED_KEY)
    if (!raw) return []
    const arr = JSON.parse(raw)
    return Array.isArray(arr) ? arr.filter((x) => typeof x === 'string') : []
  } catch {
    return []
  }
}

// 插件 → 应用卡片数据（icon 改为图标 URL，其余字段沿用 Figma 卡片结构）
function toAppItem(p: Plugin): AppItem {
  return {
    id: p.id,
    name: p.name,
    desc: p.description || '暂无描述',
    tag: (p.version || 'APP').toUpperCase(),
    // color: colorForId(p.id),
    iconUrl: p.iconUrl || undefined,
  }
}

// ── icons (inline SVG, zero deps) ─────────────────────────────────────────────

function GridIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" className="w-4.5 h-4.5">
      <rect x="2" y="2" width="7" height="7" rx="1.5" />
      <rect x="11" y="2" width="7" height="7" rx="1.5" />
      <rect x="2" y="11" width="7" height="7" rx="1.5" />
      <rect x="11" y="11" width="7" height="7" rx="1.5" />
    </svg>
  )
}
function PaletteIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" className="w-4.5 h-4.5">
      <path d="M10 2a8 8 0 100 16 4 4 0 000-8 4 4 0 010-8z" />
      <circle cx="6" cy="8" r="1" fill="currentColor" stroke="none" />
      <circle cx="14" cy="8" r="1" fill="currentColor" stroke="none" />
      <circle cx="10" cy="5" r="1" fill="currentColor" stroke="none" />
    </svg>
  )
}
function QrIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" className="w-4.5 h-4.5">
      <rect x="2" y="2" width="7" height="7" rx="1" />
      <rect x="11" y="2" width="7" height="7" rx="1" />
      <rect x="2" y="11" width="7" height="7" rx="1" />
      <path d="M11 11h2v2h-2zM15 11h2M15 13v2M11 15h2M13 17h4" strokeLinecap="round" />
    </svg>
  )
}
function SearchIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7" className="w-4 h-4">
      <circle cx="9" cy="9" r="6" />
      <path d="M15 15l3 3" strokeLinecap="round" />
    </svg>
  )
}
function GearIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" className="w-4.5 h-4.5">
      <circle cx="10" cy="10" r="3" />
      <path d="M10 2.5v2M10 15.5v2M2.5 10h2M15.5 10h2M4.6 4.6l1.4 1.4M14 14l1.4 1.4M15.4 4.6L14 6M6 14l-1.4 1.4" strokeLinecap="round" />
    </svg>
  )
}
function FullscreenToggle({ fullscreen, onToggle }: { fullscreen: boolean; onToggle: () => void }) {
  return (
    <button
      onClick={onToggle}
      title={fullscreen ? '退出全屏（Esc）' : '全屏展示'}
      className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-[13px] font-600"
      style={{ background: 'rgba(var(--primary-ink-rgb) / 0.10)', color: 'var(--primary-ink)' }}
    >
      {fullscreen ? (
        <>
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" className="w-3.5 h-3.5">
            <path d="M6 3v3H3M10 3v3h3M6 13v-3H3M10 13v-3h3" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          退出全屏
        </>
      ) : (
        <>
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" className="w-3.5 h-3.5">
            <path d="M3 6h3V3M13 6h-3V3M3 10h3v3M13 10h-3v3" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          全屏
        </>
      )}
    </button>
  )
}
function PinIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" className="w-3.5 h-3.5">
      <path d="M10 2l1.5 5h5L13 10l1.5 5L10 12l-4.5 3L7 10 3.5 7h5z" strokeLinejoin="round" />
    </svg>
  )
}

function Tooltip({ label }: { label: string }) {
  return (
    <div
      className="absolute left-full ml-3 px-2.5 py-1.5 rounded-lg text-[12px] font-500 whitespace-nowrap pointer-events-none z-50"
      style={{
        background: 'rgba(13,31,38,0.88)',
        color: '#fff',
        backdropFilter: 'blur(8px)',
        WebkitBackdropFilter: 'blur(8px)',
        boxShadow: '0 4px 16px rgba(var(--shadow-rgb, 12 58 69) / 0.10)',
        fontFamily: "'Outfit', sans-serif",
      }}
    >
      {label}
      {/* arrow */}
      <span
        className="absolute top-1/2 -translate-y-1/2 -left-1.5 w-0 h-0"
        style={{
          borderTop: '5px solid transparent',
          borderBottom: '5px solid transparent',
          borderRight: '6px solid rgba(13,31,38,0.88)',
        }}
      />
    </div>
  )
}

// ── ThemePicker ───────────────────────────────────────────────────────────────

function ThemePicker({ current, onChange, onClose }: {
  current: Theme
  onChange: (t: Theme) => void
  onClose: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose()
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [onClose])

  return (
    <div
      ref={ref}
      className="absolute left-full ml-3 z-50 p-3 flex flex-col gap-2"
      style={{
        top: '50%',
        transform: 'translateY(-50%)',
        width: 220,
        borderRadius: 20,
        background: 'rgba(var(--surface-rgb) / 0.94)',
        backdropFilter: 'blur(28px) saturate(120%)',
        WebkitBackdropFilter: 'blur(28px) saturate(120%)',
        border: '1px solid rgba(var(--hairline-rgb) / 0.12)',
        boxShadow: '0 12px 40px rgba(0,0,0,0.12), 0 2px 8px rgba(0,0,0,0.06), inset 0 1px 0 rgba(255,255,255,0.9)',
      }}
    >
      {/* header */}
      <div className="flex items-center justify-between px-1 mb-1">
        <span className="font-700 text-[13px]" style={{ color: current.dark }}>主题色</span>
        <span className="text-[11px]" style={{ fontFamily: "'DM Mono', monospace", color: current.faint }}>
          {current.name}
        </span>
      </div>

      {/* swatches grid */}
      <div className="grid gap-2" style={{ gridTemplateColumns: 'repeat(4, 1fr)' }}>
        {THEMES.map(t => {
          const isActive = t.id === current.id
          return (
            <button
              key={t.id}
              onClick={() => onChange(t)}
              className="flex flex-col items-center gap-1.5 p-2 rounded-2xl transition-all duration-200 hover:scale-105"
              style={{
                background: isActive ? t.light : 'transparent',
                border: isActive ? `1.5px solid ${t.primary}40` : '1.5px solid transparent',
              }}
            >
              {/* color dot */}
              <div
                className="w-7 h-7 rounded-xl flex-shrink-0"
                style={{
                  background: `linear-gradient(135deg, ${t.gradient[0]}, ${t.gradient[1]})`,
                  boxShadow: isActive ? `0 3px 10px ${t.primary}50` : `0 2px 6px ${t.primary}30`,
                  outline: isActive ? `2px solid ${t.primary}` : 'none',
                  outlineOffset: 2,
                }}
              />
              <span
                className="text-[10px] font-500 leading-none text-center"
                style={{ color: isActive ? t.primary : t.faint, fontFamily: "'Outfit', sans-serif" }}
              >
                {t.name}
              </span>
            </button>
          )
        })}
      </div>

      {/* preview strip */}
      <div
        className="mt-1 rounded-xl p-3 flex items-center gap-2"
        style={{ background: current.muted, border: `1px solid ${current.border}` }}
      >
        <div
          className="w-6 h-6 rounded-lg flex-shrink-0"
          style={{ background: `linear-gradient(135deg, ${current.gradient[0]}, ${current.gradient[1]})` }}
        />
        <div className="flex flex-col min-w-0">
          <span className="text-[11px] font-600 truncate" style={{ color: current.dark }}>{current.name}</span>
          <span className="text-[10px] font-400" style={{ fontFamily: "'DM Mono', monospace", color: current.faint }}>
            {current.primary}
          </span>
        </div>
      </div>
    </div>
  )
}

// ── Sidebar ───────────────────────────────────────────────────────────────────

function Sidebar({
  active,
  onSelect,
  theme,
  onThemeChange,
  visible,
  onToggle,
}: {
  active: string
  onSelect: (id: string) => void
  theme: Theme
  onThemeChange: (t: Theme) => void
  visible: boolean
  onToggle: () => void
}) {
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const [showTheme, setShowTheme] = useState(false)
  const [handleHovered, setHandleHovered] = useState(false)

  const g = theme.gradient

  return (
    <>
    <aside
      className="fixed z-40 flex flex-col items-center py-3 gap-1"
      style={{
        left: 16,
        top: '50%',
        width: 56,
        borderRadius: 22,
        background: 'rgba(var(--surface-rgb) / 0.88)',
        backdropFilter: 'blur(20px) saturate(120%)',
        WebkitBackdropFilter: 'blur(20px) saturate(120%)',
        border: '1px solid rgba(var(--hairline-rgb) / 0.18)',
        boxShadow: '0 10px 28px rgba(var(--shadow-rgb) / 0.10), 0 2px 6px rgba(var(--shadow-rgb) / 0.06)',
        transform: visible ? 'translate(0, -50%)' : 'translate(-80px, -50%)',
        opacity: visible ? 1 : 0,
        pointerEvents: visible ? 'auto' : 'none',
        transition: 'transform 0.35s cubic-bezier(0.32,0.72,0,1), opacity 0.25s ease',
      }}
    >
      {/* logo */}
      <div
        className="w-9 h-9 rounded-2xl flex items-center justify-center mb-1 flex-shrink-0 overflow-hidden"
        style={{
          background: `linear-gradient(135deg, ${g[0]}, ${g[1]})`,
          boxShadow: '0 3px 10px rgba(var(--shadow-rgb) / 0.22)',
        }}
      >
        <img src="/icon.png" alt="WW" draggable={false} className="w-full h-full object-cover" />
      </div>

      {/* divider */}
      <div className="w-7 h-px my-0.5 rounded-full" style={{ background: 'rgba(var(--hairline-rgb) / 0.12)' }} />

      {/* nav icons */}
      {NAV_ITEMS.map(({ id, label, icon: Icon }) => {
        const isActive = active === id
        return (
          <div key={id} className="relative flex items-center">
            <button
              onClick={() => onSelect(id)}
              onMouseEnter={() => setHoveredId(id)}
              onMouseLeave={() => setHoveredId(null)}
              className="w-10 h-10 rounded-2xl flex items-center justify-center transition-all duration-200"
              style={{
                background: isActive
                  ? 'var(--fill-gradient)'
                  : hoveredId === id
                  ? 'rgba(var(--primary-ink-rgb) / 0.10)'
                  : 'transparent',
                color: isActive ? 'var(--primary-foreground)' : hoveredId === id ? 'var(--primary-ink)' : 'var(--color-mid)',
                boxShadow: isActive ? '0 4px 12px rgba(var(--shadow-rgb) / 0.18)' : 'none',
                transform: hoveredId === id && !isActive ? 'scale(1.08)' : 'scale(1)',
              }}
            >
              <Icon />
            </button>
            {hoveredId === id && <Tooltip label={label} />}
          </div>
        )
      })}

      {/* divider */}
      <div className="w-7 h-px my-0.5 rounded-full" style={{ background: 'rgba(var(--hairline-rgb) / 0.12)' }} />

      {/* bookmarks button */}
      <div className="relative flex items-center">
        <button
          onClick={() => onSelect('bookmarks')}
          onMouseEnter={() => setHoveredId('bookmarks')}
          onMouseLeave={() => setHoveredId(null)}
          className="w-10 h-10 rounded-2xl flex items-center justify-center transition-all duration-200"
          style={{
            background: active === 'bookmarks'
              ? 'var(--fill-gradient)'
              : hoveredId === 'bookmarks'
              ? 'rgba(var(--primary-ink-rgb) / 0.10)'
              : 'transparent',
            color: active === 'bookmarks' ? 'var(--primary-foreground)' : hoveredId === 'bookmarks' ? 'var(--primary-ink)' : 'var(--color-mid)',
            boxShadow: active === 'bookmarks' ? '0 4px 12px rgba(var(--shadow-rgb) / 0.18)' : 'none',
            transform: hoveredId === 'bookmarks' && active !== 'bookmarks' ? 'scale(1.08)' : 'scale(1)',
          }}
        >
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" className="w-4.5 h-4.5">
            <path d="M3 4.5h14v11H3z" strokeLinejoin="round" />
            <path d="M3 7.5h14" strokeLinecap="round" />
          </svg>
        </button>
        {hoveredId === 'bookmarks' && <Tooltip label="书签整理" />}
      </div>

      {/* theme picker button */}
      <div className="relative flex items-center">
        <button
          onClick={() => setShowTheme(v => !v)}
          onMouseEnter={() => !showTheme && setHoveredId('theme')}
          onMouseLeave={() => setHoveredId(null)}
          className="w-10 h-10 rounded-2xl flex items-center justify-center transition-all duration-200"
          style={{
            background: showTheme
              ? 'var(--fill-gradient)'
              : hoveredId === 'theme'
              ? 'rgba(var(--primary-ink-rgb) / 0.10)'
              : 'transparent',
            color: showTheme ? 'var(--primary-foreground)' : hoveredId === 'theme' ? 'var(--primary-ink)' : 'var(--color-mid)',
            boxShadow: showTheme ? '0 4px 12px rgba(var(--shadow-rgb) / 0.18)' : 'none',
            transform: hoveredId === 'theme' && !showTheme ? 'scale(1.08)' : 'scale(1)',
          }}
        >
          {/* palette icon */}
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" className="w-4.5 h-4.5">
            <circle cx="10" cy="10" r="7.5" />
            <circle cx="7" cy="8" r="1.2" fill="currentColor" stroke="none" />
            <circle cx="13" cy="8" r="1.2" fill="currentColor" stroke="none" />
            <circle cx="10" cy="13" r="1.2" fill="currentColor" stroke="none" />
            <circle cx="7" cy="12" r="1.2" fill="currentColor" stroke="none" />
            <circle cx="13" cy="12" r="1.2" fill="currentColor" stroke="none" />
          </svg>
        </button>
        {hoveredId === 'theme' && !showTheme && <Tooltip label="切换主题" />}
        {showTheme && (
          <ThemePicker
            current={theme}
            onChange={(t) => { onThemeChange(t); setShowTheme(false) }}
            onClose={() => setShowTheme(false)}
          />
        )}
      </div>

      {/* settings button */}
      <div className="relative flex items-center">
        <button
          onClick={() => onSelect('settings')}
          onMouseEnter={() => setHoveredId('settings')}
          onMouseLeave={() => setHoveredId(null)}
          className="w-10 h-10 rounded-2xl flex items-center justify-center transition-all duration-200"
          style={{
            background: active === 'settings'
              ? 'var(--fill-gradient)'
              : hoveredId === 'settings'
              ? 'rgba(var(--primary-ink-rgb) / 0.10)'
              : 'transparent',
            color: active === 'settings' ? 'var(--primary-foreground)' : hoveredId === 'settings' ? 'var(--primary-ink)' : 'var(--color-mid)',
            boxShadow: active === 'settings' ? '0 4px 12px rgba(var(--shadow-rgb) / 0.18)' : 'none',
            transform: hoveredId === 'settings' && active !== 'settings' ? 'scale(1.08)' : 'scale(1)',
          }}
        >
          <GearIcon />
        </button>
        {hoveredId === 'settings' && <Tooltip label="设置" />}
      </div>

      {/* avatar */}
      <div
        className="relative w-8 h-8 rounded-full flex items-center justify-center text-[12px] font-700 cursor-pointer mt-0.5"
        style={{
          background: `linear-gradient(135deg, ${theme.light}, ${theme.border})`,
          color: 'var(--primary-ink)',
          border: '1.5px solid rgba(var(--primary-ink-rgb) / 0.28)',
        }}
        onMouseEnter={() => setHoveredId('user')}
        onMouseLeave={() => setHoveredId(null)}
      >
        图
        {hoveredId === 'user' && <Tooltip label="用户图图 · Free" />}
      </div>

      {/* divider */}
      <div className="w-7 h-px my-0.5 rounded-full" style={{ background: 'rgba(var(--hairline-rgb) / 0.12)' }} />

      {/* collapse button — 并入侧栏底部，与导航图标同款 */}
      <div className="relative flex items-center">
        <button
          onClick={onToggle}
          onMouseEnter={() => setHoveredId('collapse')}
          onMouseLeave={() => setHoveredId(null)}
          className="w-10 h-10 rounded-2xl flex items-center justify-center transition-all duration-200"
          style={{
            background: hoveredId === 'collapse' ? 'rgba(var(--primary-ink-rgb) / 0.10)' : 'transparent',
            color: hoveredId === 'collapse' ? 'var(--primary-ink)' : 'var(--color-mid)',
            transform: hoveredId === 'collapse' ? 'scale(1.08)' : 'scale(1)',
          }}
        >
          {/* 双左箭头：收起侧边栏 */}
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" className="w-4.5 h-4.5">
            <path d="M11 5l-4 5 4 5" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M15 5l-4 5 4 5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
        {hoveredId === 'collapse' && <Tooltip label="收起侧边栏" />}
      </div>
    </aside>

    {/* 收起后的边缘把手：极细毛玻璃竖条，hover / 点击（键盘）展开 */}
    {!visible && (
      <button
        onClick={onToggle}
        onMouseEnter={() => { setHandleHovered(true); onToggle() }}
        onMouseLeave={() => setHandleHovered(false)}
        className="fixed z-40 top-1/2 -translate-y-1/2 rounded-r-full transition-all duration-200"
        style={{
          left: 0,
          width: handleHovered ? 10 : 5,
          height: 56,
          background: handleHovered ? 'rgba(var(--surface-rgb) / 0.92)' : 'rgba(var(--surface-rgb) / 0.7)',
          backdropFilter: 'blur(8px)',
          WebkitBackdropFilter: 'blur(8px)',
          border: '1px solid rgba(var(--hairline-rgb) / 0.12)',
          boxShadow: '0 2px 8px rgba(var(--shadow-rgb) / 0.10)',
        }}
        title="显示侧边栏"
      />
    )}
    </>
  )
}

// ── main app ──────────────────────────────────────────────────────────────────

export default function App() {
  const [searchQ, setSearchQ] = useState('')
  const [openApp, setOpenApp] = useState<string | null>(null)
  const [fullscreen, setFullscreen] = useState(false)
  const [fsHeaderVisible, setFsHeaderVisible] = useState(false)
  const [fsSidebarVisible, setFsSidebarVisible] = useState(false)
  const [page, setPage] = useState<'apps' | 'settings'>('apps')
  const [sliding, setSliding] = useState(false)
  const [theme, setTheme] = useState<Theme>(loadTheme)
  const [sidebarVisible, setSidebarVisible] = useState(true)
  const [plugins, setPlugins] = useState<Plugin[]>([])
  const [loaded, setLoaded] = useState(false)
  const [pinnedIds, setPinnedIds] = useState<string[]>(loadPinned)

  useEffect(() => {
    localStorage.setItem(THEME_KEY, theme.id)
  }, [theme])

  useEffect(() => {
    localStorage.setItem(PINNED_KEY, JSON.stringify(pinnedIds))
  }, [pinnedIds])

  // 插件 SDK 的 navigate/openApp 通过 hash 驱动宿主视图切换
  useEffect(() => {
    const onHash = () => {
      const m = window.location.hash.match(/^#\/app\/(.+)$/)
      if (m) {
        setPage('apps')
        setOpenApp(decodeURIComponent(m[1]))
        enterFullscreen()
        return
      }
      if (window.location.hash === '#/settings') {
        setPage('settings')
        setOpenApp(null)
        setFullscreen(false)
        return
      }
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const loadPlugins = useCallback(() => {
    getPlugins()
      .then((d) => {
        const items = d.items.filter((p) => p.enabled)
        setPlugins(items)
        setLoaded(true)
        setPinnedIds((prev) => prev.filter((id) => items.some((p) => p.id === id)))
      })
      .catch((e) => {
        setLoaded(true)
        toast('加载应用失败', String(e.message || e), 'error')
      })
  }, [])

  useEffect(loadPlugins, [loadPlugins])

  // 进入全屏沉浸模式：头部与侧栏默认隐藏，仅保留边缘毛玻璃把手
  const enterFullscreen = useCallback(() => {
    setFullscreen(true)
    setFsHeaderVisible(false)
    setFsSidebarVisible(false)
  }, [])

  const exitFullscreen = useCallback(() => {
    setFullscreen(false)
    setFsHeaderVisible(false)
    setFsSidebarVisible(false)
  }, [])

  // 全屏展示时按 Esc 退出全屏
  useEffect(() => {
    if (!(openApp && fullscreen)) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') exitFullscreen()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [openApp, fullscreen, exitFullscreen])

  function navigateTo(id: string) {
    setPage('apps')
    enterFullscreen()
    setSliding(true)
    setTimeout(() => { setOpenApp(id); setSliding(false) }, 10)
  }
  function navigateBack() {
    exitFullscreen()
    setSliding(true)
    setTimeout(() => { setOpenApp(null); setSliding(false) }, 10)
  }

  const apps = plugins.map(toAppItem)
  const pinnedApps = apps.filter((a) => pinnedIds.includes(a.id))

  const filtered = apps.filter((a) => {
    const matchSearch =
      !searchQ ||
      a.name.includes(searchQ) ||
      a.desc.includes(searchQ) ||
      a.tag.toLowerCase().includes(searchQ.toLowerCase())
    return matchSearch
  })

  const showPinned = !searchQ

  return (
    <div
      className="flex h-screen overflow-hidden"
      style={{ background: 'var(--background)', ...Object.fromEntries(Object.entries(themeVars(theme))) as React.CSSProperties }}
    >
      <Sidebar
        active={page === 'settings' ? 'settings' : openApp === 'bookmarks-organizer' ? 'bookmarks' : 'all'}
        onSelect={(id) => {
          setOpenApp(null)
          exitFullscreen()
          if (id === 'settings') setPage('settings')
          else if (id === 'bookmarks') navigateTo('bookmarks-organizer')
          else setPage('apps')
        }}
        theme={theme}
        onThemeChange={setTheme}
        visible={sidebarVisible}
        onToggle={() => setSidebarVisible(v => !v)}
      />

      {/* main — offset from floating sidebar */}
      <main
        className="flex-1 overflow-y-auto"
        style={{
          marginLeft: sidebarVisible ? 76 : 16,
          transition: 'margin-left 0.35s cubic-bezier(0.32,0.72,0,1), transform 0.32s cubic-bezier(0.32,0.72,0,1), opacity 0.22s ease',
          transform: sliding ? 'translateX(18px)' : 'translateX(0)',
          opacity: sliding ? 0 : 1,
        }}
      >
        {/* ── sub-app overlay（插件 iframe）── */}
        {openApp && (() => {
          const plugin = plugins.find((p) => p.id === openApp)
          if (!plugin) {
            return (
              <div className="flex flex-col items-center justify-center h-full gap-3" style={{ padding: '0 24px' }}>
                <div className="text-4xl">🧩</div>
                <div className="text-[13px]" style={{ color: 'var(--muted-foreground)' }}>该应用未安装或已停用</div>
                <button
                  onClick={navigateBack}
                  className="px-4 py-2 rounded-xl text-[13px] font-600"
                  style={{ background: 'var(--fill-gradient)', color: 'var(--primary-foreground)' }}
                >
                  返回
                </button>
              </div>
            )
          }
          const bar = (
            <PageHeader
              title={plugin.name}
              onBack={navigateBack}
              trailing={<FullscreenToggle fullscreen={false} onToggle={enterFullscreen} />}
            />
          )
          // 全屏展示由根层 fixed 覆盖层渲染（见下方），此处保持常规形态
          if (fullscreen) return null
          // 常规展示：保留侧栏与浮动返回条
          return (
            <div className="flex flex-col h-full" style={{ padding: '0 24px' }}>
              <div className="sticky top-0 z-20 w-full px-0 pt-4 pb-0 pointer-events-none">
                {bar}
              </div>
              <div className="flex-1 min-h-0 pb-6 mt-4">
                {plugin.type === 'react'
                  ? <ReactAppView appId={plugin.id} theme={theme} />
                  : <PluginView plugin={plugin} />}
              </div>
            </div>
          )
        })()}

        {/* ── settings view ── */}
        {page === 'settings' && !openApp && (
          <Settings
            theme={theme}
            onBack={() => setPage('apps')}
            onChanged={() => { loadPlugins(); setPinnedIds(loadPinned()) }}
          />
        )}

        {/* ── home view ── */}
        {page === 'apps' && !openApp && <>
        {/* ── floating topbar ── */}
        <div className="sticky top-0 z-20 px-6 pt-4 pb-0 pointer-events-none">
          <PageHeader
            icon={<GridIcon />}
            title="全部应用"
            subtitle={`${filtered.length} 个工具`}
            center={(
              // center: search
            <div
              className="flex items-center gap-2 px-3.5 py-2 w-full max-w-xs"
              style={{
                borderRadius: 12,
                background: 'rgba(var(--hairline-rgb) / 0.05)',
                border: '1px solid rgba(var(--hairline-rgb) / 0.18)',
                color: 'var(--muted-foreground)',
              }}
            >
              <SearchIcon />
              <input
                className="flex-1 bg-transparent outline-none text-[13px]"
                style={{ color: 'var(--foreground)' }}
                placeholder="搜索工具名称、标签…"
                value={searchQ}
                onChange={(e) => setSearchQ(e.target.value)}
              />
              {searchQ && (
                <button
                  onClick={() => setSearchQ('')}
                  className="text-[11px] w-4 h-4 rounded-full flex items-center justify-center flex-shrink-0"
                  style={{ background: 'var(--color-faint)', color: '#fff' }}
                >
                  ×
                </button>
              )}
            </div>
            )}
            trailing={(
              // right: badge row
              <>
              <div
                className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] font-500"
                style={{ borderRadius: 10, background: 'rgba(var(--primary-ink-rgb) / 0.10)', color: 'var(--primary-ink)' }}
              >
                <PinIcon />
                最近使用
              </div>
              <div
                className="w-8 h-8 rounded-full flex items-center justify-center text-[12px] font-700"
                style={{ background: 'rgba(var(--primary-ink-rgb) / 0.10)', color: 'var(--primary-ink)', border: '1.5px solid rgba(var(--primary-ink-rgb) / 0.25)' }}
              >
                图
              </div>
              </>
            )}
          />
        </div>

        <div className="px-6 pt-5 pb-8 flex flex-col gap-7">
          {/* pinned / quick access */}
          {showPinned && pinnedApps.length > 0 && (
            <section>
              {/* section title pill */}
              <div className="flex items-center gap-3 mb-4">
                <div
                  className="flex items-center gap-2 px-3.5 py-1.5"
                  style={{
                    borderRadius: 12,
                    background: 'rgba(var(--surface-rgb) / 0.88)',
                    backdropFilter: 'blur(16px)',
                    WebkitBackdropFilter: 'blur(16px)',
                    border: '1px solid rgba(var(--hairline-rgb) / 0.18)',
                    boxShadow: '0 2px 10px rgba(var(--shadow-rgb) / 0.08), inset 0 1px 0 rgba(255,255,255,0.8)',
                  }}
                >
                  <span style={{ color: 'var(--primary-ink)' }}><PinIcon /></span>
                  <span className="font-600 text-[13px]" style={{ color: 'var(--foreground)' }}>快速访问</span>
                  <span
                    className="text-[10px] px-1.5 py-0.5 rounded-md"
                    style={{ fontFamily: "'DM Mono', monospace", background: 'rgba(var(--primary-ink-rgb) / 0.10)', color: 'var(--primary-ink)' }}
                  >
                    已固定
                  </span>
                </div>
              </div>
              <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
                {pinnedApps.map((app) => (
                  <AppCard key={app.id} app={app} pinned onClick={() => navigateTo(app.id)} />
                ))}
              </div>
            </section>
          )}

          {/* stats strip — frosted glass card */}
          {showPinned && (
            <div
              className="grid gap-0"
              style={{
                gridTemplateColumns: 'repeat(4, 1fr)',
                borderRadius: 20,
                background: 'rgba(var(--surface-rgb) / 0.88)',
                backdropFilter: 'blur(20px) saturate(120%)',
                WebkitBackdropFilter: 'blur(20px) saturate(120%)',
                border: '1px solid rgba(var(--hairline-rgb) / 0.18)',
                boxShadow: '0 4px 20px rgba(var(--shadow-rgb) / 0.08), inset 0 1px 0 rgba(255,255,255,0.8)',
                overflow: 'hidden',
              }}
            >
              {[
                { label: '今日使用', value: '—', sub: '暂未统计', accent: 'var(--primary-ink)' },
                { label: '收藏工具', value: `${pinnedIds.length} 个`, sub: '点击卡片星标固定', accent: 'var(--primary-ink)' },
                { label: '平台工具', value: `${apps.length} 个`, sub: '持续更新中', accent: 'var(--primary-ink)' },
                { label: '最常用', value: pinnedApps[0]?.name ?? '—', sub: pinnedApps[0] ? '星标应用' : '暂无数据', accent: 'var(--muted-foreground)' },
              ].map((s, i) => (
                <div
                  key={s.label}
                  className="flex flex-col gap-1.5 p-5"
                  style={{
                    borderRight: i < 3 ? '1px solid rgba(var(--hairline-rgb) / 0.18)' : 'none',
                  }}
                >
                  <div className="text-[11px]" style={{ fontFamily: "'DM Mono', monospace", color: 'var(--muted-foreground)' }}>
                    {s.label}
                  </div>
                  <div className="font-700 text-[20px] leading-tight" style={{ color: s.accent }}>{s.value}</div>
                  <div className="text-[11px]" style={{ color: 'var(--color-mid)' }}>{s.sub}</div>
                </div>
              ))}
            </div>
          )}

          {/* all / filtered apps */}
          <section>
            {showPinned && (
              <div className="flex items-center gap-3 mb-4">
                <div
                  className="flex items-center gap-2 px-3.5 py-1.5"
                  style={{
                    borderRadius: 12,
                    background: 'rgba(var(--surface-rgb) / 0.88)',
                    backdropFilter: 'blur(16px)',
                    WebkitBackdropFilter: 'blur(16px)',
                    border: '1px solid rgba(var(--hairline-rgb) / 0.18)',
                    boxShadow: '0 2px 10px rgba(var(--shadow-rgb) / 0.08), inset 0 1px 0 rgba(255,255,255,0.8)',
                  }}
                >
                  <span style={{ color: 'var(--primary-ink)' }}><GridIcon /></span>
                  <span className="font-600 text-[13px]" style={{ color: 'var(--foreground)' }}>全部工具</span>
                  <span
                    className="text-[10px] px-1.5 py-0.5 rounded-md"
                    style={{ fontFamily: "'DM Mono', monospace", background: 'var(--muted)', color: 'var(--muted-foreground)' }}
                  >
                    {filtered.length}
                  </span>
                </div>
              </div>
            )}
            {filtered.length === 0 ? (
              <div
                className="flex flex-col items-center justify-center py-20 gap-3"
                style={{
                  borderRadius: 20,
                  background: 'rgba(var(--surface-rgb) / 0.80)',
                  backdropFilter: 'blur(16px)',
                  WebkitBackdropFilter: 'blur(16px)',
                  border: '1px solid rgba(var(--hairline-rgb) / 0.18)',
                  boxShadow: '0 2px 12px rgba(var(--shadow-rgb) / 0.06)',
                }}
              >
                <div className="text-3xl">{loaded ? '🔍' : '⏳'}</div>
                <div className="font-500 text-[15px]" style={{ color: 'var(--muted-foreground)' }}>
                  {loaded ? '未找到相关工具' : '正在加载应用…'}
                </div>
                <div className="text-[12px]" style={{ fontFamily: "'DM Mono', monospace", color: 'var(--color-mid)' }}>
                  {loaded ? 'try other keywords' : 'loading plugins'}
                </div>
              </div>
            ) : (
              <div
                className="grid gap-4"
                style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))' }}
              >
                {filtered.map((app) => (
                  <AppCard
                    key={app.id}
                    app={app}
                    pinned={pinnedIds.includes(app.id)}
                    onClick={() => navigateTo(app.id)}
                    onTogglePinned={() => setPinnedIds((prev) => (
                      prev.includes(app.id) ? prev.filter((id) => id !== app.id) : [...prev, app.id]
                    ))}
                  />
                ))}
              </div>
            )}
          </section>
        </div>
        </>}
      </main>

      {/* ── 插件全屏覆盖层：iframe 铺满全窗，顶部返回条与侧栏导航悬浮其上 ── */}
      {openApp && fullscreen && (() => {
        const plugin = plugins.find((p) => p.id === openApp)
        if (!plugin) return null
        return (
          <div className="fixed inset-0 z-50" style={{ background: 'var(--background)' }}>
            {/* iframe 铺满整个窗口 */}
            <div className="absolute inset-0">
              {plugin.type === 'react'
                ? <ReactAppView appId={plugin.id} theme={theme} />
                : <PluginView plugin={plugin} fullscreen />}
            </div>
            {/* 顶部毛玻璃横条把手：hover / 点击展开头部 */}
            {!fsHeaderVisible && (
              <button
                onClick={() => setFsHeaderVisible(true)}
                onMouseEnter={() => setFsHeaderVisible(true)}
                className="absolute top-0 left-1/2 -translate-x-1/2 z-30 rounded-b-full transition-all duration-200"
                style={{
                  width: 48,
                  height: 5,
                  background: 'rgba(var(--surface-rgb) / 0.80)',
                  backdropFilter: 'blur(8px)',
                  WebkitBackdropFilter: 'blur(8px)',
                  border: '1px solid rgba(var(--hairline-rgb) / 0.12)',
                  borderTop: 'none',
                  boxShadow: '0 2px 8px rgba(var(--shadow-rgb) / 0.10)',
                }}
                title="显示头部"
              />
            )}
            {/* 顶部悬浮头部（默认隐藏，展开后可收起 / 退出全屏） */}
            {fsHeaderVisible && (
              <div
                className="absolute top-0 left-0 right-0 z-20 px-6 pt-4 pointer-events-none"
                style={{ animation: 'headerIn 0.18s ease' }}
              >
                <PageHeader
                  title={plugin.name}
                  onBack={navigateBack}
                  trailing={(
                    <>
                      <button
                        onClick={() => setFsHeaderVisible(false)}
                        title="收起头部"
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-[13px] font-600"
                        style={{ background: 'rgba(var(--primary-ink-rgb) / 0.10)', color: 'var(--primary-ink)' }}
                      >
                        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" className="w-3.5 h-3.5">
                          <path d="M6 3l4 4-4 4" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                        收起
                      </button>
                      <FullscreenToggle fullscreen onToggle={exitFullscreen} />
                    </>
                  )}
                />
              </div>
            )}
            {/* 左侧悬浮导航（应用 / 设置 / 主题 / 头像）：默认隐藏，左边缘竖条把手展开 */}
            <Sidebar
              active={page === 'settings' ? 'settings' : openApp === 'bookmarks-organizer' ? 'bookmarks' : 'all'}
              onSelect={(id) => {
                setOpenApp(null)
                exitFullscreen()
                if (id === 'settings') setPage('settings')
                else if (id === 'bookmarks') navigateTo('bookmarks-organizer')
                else setPage('apps')
              }}
              theme={theme}
              onThemeChange={setTheme}
              visible={fsSidebarVisible}
              onToggle={() => setFsSidebarVisible(v => !v)}
            />
          </div>
        )
      })()}
    </div>
  )
}
