// 统一页面头部：毛玻璃圆角条（应用页 / 插件视图 / 设置页共用）
// 结构：左侧（可选返回按钮 + 图标 + 标题/副标题） + 中间内容区 + 右侧内容区

import type { ReactNode } from 'react'

export default function PageHeader({
  icon,
  title,
  subtitle,
  onBack,
  center,
  trailing,
}: {
  icon?: ReactNode
  title: string
  subtitle?: string
  onBack?: () => void
  center?: ReactNode
  trailing?: ReactNode
}) {
  return (
    <div
      className="pointer-events-auto flex items-center justify-between px-5 py-3 gap-4"
      style={{
        borderRadius: 20,
        background: 'rgba(255,255,255,0.55)',
        backdropFilter: 'blur(24px) saturate(180%)',
        WebkitBackdropFilter: 'blur(24px) saturate(180%)',
        border: '1px solid rgba(255,255,255,0.72)',
        boxShadow: '0 6px 28px rgba(var(--primary-rgb, 6 182 212) / 0.10), 0 1px 4px rgba(var(--primary-rgb) / 0.07), inset 0 1px 0 rgba(255,255,255,0.8)',
      }}
    >
      {/* 左侧：返回 + 图标 + 标题 */}
      <div className="flex items-center gap-3 min-w-0">
        {onBack && (
          <button
            onClick={onBack}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-[13px] font-600 flex-shrink-0"
            style={{ background: 'rgba(var(--primary-rgb) / 0.10)', color: 'var(--primary)' }}
          >
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" className="w-3.5 h-3.5">
              <path d="M10 12L6 8l4-4" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            返回
          </button>
        )}
        {icon && (
          <div
            className="w-8 h-8 rounded-2xl flex items-center justify-center flex-shrink-0"
            style={{ background: 'rgba(var(--primary-rgb) / 0.10)', color: 'var(--primary)' }}
          >
            {icon}
          </div>
        )}
        <div className="min-w-0">
          <h1 className="font-700 text-[16px] leading-tight truncate" style={{ color: 'var(--foreground)' }}>
            {title}
          </h1>
          {subtitle && (
            <p className="text-[11px] leading-none mt-0.5" style={{ fontFamily: "'DM Mono', monospace", color: 'var(--muted-foreground)' }}>
              {subtitle}
            </p>
          )}
        </div>
      </div>

      {/* 中间内容区（如搜索框） */}
      {center && <div className="flex-1 min-w-0 flex">{center}</div>}

      {/* 右侧内容区 */}
      {trailing && <div className="flex items-center gap-2 flex-shrink-0">{trailing}</div>}
    </div>
  )
}
