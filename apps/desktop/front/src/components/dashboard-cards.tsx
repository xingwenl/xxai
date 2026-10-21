// 首页概览卡：展示子应用通过 desktop.dashboard.publish(...) 推送的关键信息
//
// 卡片完全由子应用推送的数据驱动，宿主不做业务解释：只渲染标题、指标与最近条目，
// 点击卡片打开对应子应用。没有任何卡片时整区不渲染，首页布局与之前保持一致。

import { useEffect, useState } from 'react'
import {
  getDashboardCards,
  subscribeDashboardCards,
  type DashboardCard,
} from '../lib/dashboard-bridge'

const MONO = "'DM Mono', monospace"

function CardView({ card, onClick }: { card: DashboardCard; onClick: () => void }) {
  const [hovered, setHovered] = useState(false)
  const hasBody = card.metrics.length > 0 || card.recent.length > 0

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onClick()
        }
      }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className="flex flex-col gap-3.5 p-5 outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
      style={{
        borderRadius: 20,
        cursor: 'pointer',
        background: 'rgba(var(--surface-rgb) / 0.88)',
        backdropFilter: 'blur(20px) saturate(120%)',
        WebkitBackdropFilter: 'blur(20px) saturate(120%)',
        border: `1px solid rgba(var(--hairline-rgb) / ${hovered ? 0.4 : 0.18})`,
        boxShadow:
          '0 4px 20px rgba(var(--shadow-rgb) / 0.08), inset 0 1px 0 rgba(255,255,255,0.8)',
        transition: 'border-color 160ms ease, transform 160ms ease',
        transform: hovered ? 'translateY(-1px)' : 'none',
      }}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div
            className="font-600 text-[14px] truncate"
            style={{ color: 'var(--foreground)' }}
            title={card.title}
          >
            {card.title}
          </div>
          <div className="text-[11px] truncate" style={{ fontFamily: MONO, color: 'var(--muted-foreground)' }}>
            {card.pluginName}
          </div>
        </div>
        <span
          className="text-[10px] px-1.5 py-0.5 rounded-md shrink-0"
          style={{ fontFamily: MONO, background: 'rgba(var(--primary-ink-rgb) / 0.10)', color: 'var(--primary-ink)' }}
        >
          {card.metrics.length + card.recent.length > 0 ? 'LIVE' : 'EMPTY'}
        </span>
      </div>

      {card.metrics.length > 0 && (
        <div className="grid gap-2" style={{ gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' }}>
          {card.metrics.map((metric) => (
            <div key={metric.label} className="min-w-0">
              <div
                className="text-[10px] truncate"
                style={{ fontFamily: MONO, color: 'var(--muted-foreground)' }}
                title={metric.label}
              >
                {metric.label}
              </div>
              <div className="font-600 text-[18px] truncate" style={{ color: 'var(--foreground)' }} title={metric.value}>
                {metric.value}
              </div>
            </div>
          ))}
        </div>
      )}

      {card.recent.length > 0 && (
        <ul className="flex flex-col gap-1.5" style={{ borderTop: '1px solid rgba(var(--hairline-rgb) / 0.18)', paddingTop: 12 }}>
          {card.recent.map((item, index) => (
            <li
              key={`${item.text}-${index}`}
              className="flex items-baseline justify-between gap-3 text-[12px]"
              style={{ color: 'var(--foreground)' }}
            >
              <span className="truncate" title={item.text}>
                {item.text}
              </span>
              {item.hint && (
                <span className="shrink-0 text-[11px]" style={{ fontFamily: MONO, color: 'var(--muted-foreground)' }}>
                  {item.hint}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}

      {!hasBody && card.emptyText && (
        <div className="text-[12px]" style={{ color: 'var(--muted-foreground)' }}>
          {card.emptyText}
        </div>
      )}
    </div>
  )
}

export function DashboardCards({
  onOpen,
  pluginIds,
}: {
  onOpen: (id: string) => void
  /** 当前启用的插件 id：停用或已卸载的插件即使残留卡片也不展示 */
  pluginIds: string[]
}) {
  const [cards, setCards] = useState<DashboardCard[]>(getDashboardCards)

  useEffect(() => subscribeDashboardCards(() => setCards(getDashboardCards())), [])

  const visible = cards.filter((card) => pluginIds.includes(card.pluginId))
  if (visible.length === 0) return null

  return (
    <section>
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
          <svg viewBox="0 0 20 20" fill="none" stroke="var(--primary-ink)" strokeWidth="1.6" className="w-4 h-4">
            <path d="M3 16.5V11m5 5.5V6m5 10.5V9m5 7.5V3.5" strokeLinecap="round" />
          </svg>
          <span className="font-600 text-[13px]" style={{ color: 'var(--foreground)' }}>
            概览
          </span>
          <span
            className="text-[10px] px-1.5 py-0.5 rounded-md"
            style={{ fontFamily: MONO, background: 'rgba(var(--primary-ink-rgb) / 0.10)', color: 'var(--primary-ink)' }}
          >
            {visible.length} 张卡片
          </span>
        </div>
      </div>
      <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))' }}>
        {visible.map((card) => (
          <CardView key={card.pluginId} card={card} onClick={() => onOpen(card.pluginId)} />
        ))}
      </div>
    </section>
  )
}
