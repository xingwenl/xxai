import React, { useState } from 'react'

export interface AppItem {
  id: string
  name: string
  desc: string
  category: string
  tag: string
  color?: string
  icon?: () => React.ReactElement
  iconUrl?: string
  hot?: boolean
  new?: boolean
}

function StarIcon({ filled }: { filled?: boolean }) {
  return (
    <svg viewBox="0 0 20 20" fill={filled ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="1.6" className="w-4 h-4">
      <path d="M10 2l2.4 5 5.6.8-4 3.9 1 5.5L10 14.5l-5 2.7 1-5.5L2 7.8l5.6-.8z" strokeLinejoin="round" />
    </svg>
  )
}

function FallbackIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" className="w-5 h-5">
      <rect x="2" y="2" width="7" height="7" rx="1.5" />
      <rect x="11" y="2" width="7" height="7" rx="1.5" />
      <rect x="2" y="11" width="7" height="7" rx="1.5" />
      <rect x="11" y="11" width="7" height="7" rx="1.5" />
    </svg>
  )
}

export function AppCard({ app, pinned, onClick, onTogglePinned }: {
  app: AppItem
  pinned?: boolean
  onClick?: () => void
  onTogglePinned?: () => void
}) {
  const [hovered, setHovered] = useState(false)
  const starred = !!pinned

  const Icon = app.icon
  // 卡片强调色：优先插件派生的 color，缺失时回退到用户设置的主题色
  const accent = app.color ?? 'var(--primary)'
  const tint = (hexAlpha: string, alpha: number) =>
    app.color ? app.color + hexAlpha : `rgba(var(--primary-rgb) / ${alpha})`

  return (
    <div
      role="button"
      tabIndex={0}
      className="group relative rounded-2xl border transition-all duration-200 cursor-pointer overflow-hidden flex flex-col outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
      style={{
        background: 'rgba(255,255,255,0.55)',
        backdropFilter: 'blur(20px) saturate(160%)',
        WebkitBackdropFilter: 'blur(20px) saturate(160%)',
        borderColor: hovered ? tint('66', 0.4) : 'rgba(255,255,255,0.75)',
        boxShadow: hovered
          ? `0 10px 34px ${tint('22', 0.13)}, 0 2px 8px ${tint('14', 0.08)}, inset 0 1px 0 rgba(255,255,255,0.9)`
          : '0 2px 10px rgba(var(--primary-rgb, 6 182 212) / 0.07), inset 0 1px 0 rgba(255,255,255,0.85)',
        transform: hovered ? 'translateY(-2px)' : 'none',
      }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocus={() => setHovered(true)}
      onBlur={() => setHovered(false)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onClick?.()
        }
      }}
      onClick={onClick}
    >
      {/* top accent stripe */}
      <div
        className="h-1 w-full transition-opacity duration-300"
        style={{
          background: `linear-gradient(90deg, ${accent}, ${tint('59', 0.35)})`,
          opacity: hovered ? 1 : 0.4,
        }}
      />

      <div className="p-5 flex flex-col flex-1 gap-3">
        {/* header row */}
        <div className="flex items-start justify-between">
          <div
            className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 transition-transform duration-200"
            style={{
              background: `linear-gradient(135deg, ${tint('1f', 0.12)}, ${tint('0d', 0.05)})`,
              color: accent,
              border: `1px solid ${tint('26', 0.15)}`,
              boxShadow: hovered ? `0 4px 12px ${tint('26', 0.15)}` : 'none',
              transform: hovered ? 'scale(1.08)' : 'scale(1)',
            }}
          >
            {Icon ? <Icon /> : app.iconUrl ? (
              <img src={app.iconUrl} alt={app.name} className="w-5 h-5" draggable={false} />
            ) : (
              <FallbackIcon />
            )}
          </div>
          <div className="flex items-center gap-1.5">
            {(app.hot || app.new || pinned) && (
              <span
                className="font-mono text-[10px] font-medium px-1.5 py-0.5 rounded-md leading-none"
                style={{
                  fontFamily: "'DM Mono', monospace",
                  background: pinned ? 'rgba(var(--primary-rgb, 6 182 212) / 0.10)' : tint('14', 0.08),
                  color: pinned ? 'var(--primary)' : accent,
                }}
              >
                {pinned ? 'PIN' : app.new ? 'NEW' : 'HOT'}
              </span>
            )}
            <button
              className="p-1 rounded-lg transition-colors duration-150"
              style={{ color: starred ? '#f59e0b' : 'var(--color-faint)' }}
              onClick={(e) => { e.stopPropagation(); onTogglePinned?.() }}
              title={starred ? '取消固定' : '固定到快速访问'}
            >
              <StarIcon filled={starred} />
            </button>
          </div>
        </div>

        {/* name + desc */}
        <div className="flex flex-col gap-1 flex-1">
          <h3 className="font-semibold text-[15px] leading-tight" style={{ color: 'var(--foreground)' }}>
            {app.name}
          </h3>
          <p className="text-[13px] leading-relaxed line-clamp-2" style={{ color: 'var(--muted-foreground)' }}>
            {app.desc}
          </p>
        </div>

        {/* tag */}
        <div className="flex items-center justify-between mt-auto pt-1">
          <span
            className="text-[11px] px-2 py-0.5 rounded-md leading-none tracking-wide"
            style={{
              fontFamily: "'DM Mono', monospace",
              background: tint('12', 0.07),
              color: accent,
            }}
          >
            {app.tag}
          </span>
          <span
            className="text-[12px] font-medium transition-all duration-150 flex items-center gap-1"
            style={{ color: hovered ? accent : 'transparent' }}
          >
            打开 →
          </span>
        </div>
      </div>
    </div>
  )
}
