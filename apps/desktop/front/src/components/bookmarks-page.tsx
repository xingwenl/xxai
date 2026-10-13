// 书签整理页：左侧分类导航 + 右侧书签列表，支持搜索、复制链接、全部打开

import { useCallback, useEffect, useMemo, useState } from 'react'
import { getBookmarkSummary, type BookmarkGroup, type BookmarkItem, type BookmarkSummary } from '../lib/api'
import { toast } from '../lib/toast'
import type { ThemeLike } from '../lib/react-apps'

const REFRESH_INTERVAL_MS = 5000

function formatTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('zh-CN', { hour12: false })
}

function faviconFallback(url: string): string {
  try {
    return `https://www.google.com/s2/favicons?domain=${new URL(url).hostname}&sz=32`
  } catch {
    return ''
  }
}

function matches(item: BookmarkItem, q: string): boolean {
  return (
    item.title.toLowerCase().includes(q) ||
    item.url.toLowerCase().includes(q) ||
    item.folderPath.toLowerCase().includes(q)
  )
}

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    // 旧版 WebView 无 Clipboard API 时的兜底方案
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    const ok = document.execCommand('copy')
    ta.remove()
    return ok
  }
}

/** 打开一批书签：优先走 pywebview 宿主桥（系统默认浏览器），浏览器调试模式回退 window.open。 */
async function openUrls(urls: string[]): Promise<{ opened: number; viaBridge: boolean }> {
  const bridge = window.pywebview?.api?.open_urls
  if (bridge) {
    const res = await bridge(urls) as { opened: number }
    return { opened: res.opened, viaBridge: true }
  }
  let opened = 0
  for (const url of urls) {
    window.open(url, '_blank', 'noopener')
    opened += 1
  }
  return { opened, viaBridge: false }
}

export default function BookmarksPage({
  theme,
}: {
  theme: ThemeLike
}) {
  const [snapshot, setSnapshot] = useState<BookmarkSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  // null 表示「全部书签」，其余为选中的分类（folderPath）
  const [selectedFolder, setSelectedFolder] = useState<string | null>(null)
  const [query, setQuery] = useState('')

  // silent=true 用于静默轮询：扩展整理完成后页面自动更新，不打断浏览
  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const data = await getBookmarkSummary()
      setSnapshot(data)
      setError(null)
    } catch (e) {
      setError(String((e as Error).message || e))
    } finally {
      if (!silent) setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    const timer = setInterval(() => load(true), REFRESH_INTERVAL_MS)
    return () => clearInterval(timer)
  }, [load])

  const q = query.trim().toLowerCase()
  const filteredGroups = useMemo<BookmarkGroup[]>(() => {
    if (!snapshot) return []
    if (!q) return snapshot.groups
    return snapshot.groups
      .map((g) => ({ ...g, items: g.items.filter((i) => matches(i, q)) }))
      .filter((g) => g.items.length > 0)
  }, [snapshot, q])

  // 选择分类时清空搜索，聚焦该分类；输入搜索时回到全局结果
  const visibleGroups = selectedFolder
    ? filteredGroups.filter((g) => g.folderPath === selectedFolder)
    : filteredGroups

  const handleCopy = async (item: BookmarkItem) => {
    const ok = await copyText(item.url)
    toast(ok ? '链接已复制' : '复制失败', item.title || item.url, ok ? 'success' : 'error')
  }

  const handleOpenAll = async (group: BookmarkGroup) => {
    try {
      const { opened, viaBridge } = await openUrls(group.items.map((i) => i.url))
      toast(
        viaBridge ? '已打开' : '已在浏览器尝试打开',
        `${opened} 个链接${viaBridge ? '（系统默认浏览器）' : '（若未弹出，请允许该站点弹窗）'}`,
        'success',
      )
    } catch (e) {
      toast('打开失败', String((e as Error).message || e), 'error')
    }
  }

  return (
    <div className="h-full flex flex-col" style={{ padding: '16px 4px 32px' }}>
      <div className="pb-3 flex-shrink-0 flex items-center gap-2">
        <div
          className="flex items-center gap-2 px-3.5 py-2 flex-1 max-w-md"
          style={{
            borderRadius: 12,
            background: 'rgba(var(--hairline-rgb) / 0.05)',
            border: '1px solid rgba(var(--hairline-rgb) / 0.18)',
            color: 'var(--muted-foreground)',
          }}
        >
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" className="w-3.5 h-3.5 flex-shrink-0">
            <circle cx="7" cy="7" r="4.5" />
            <path d="M10.5 10.5L14 14" strokeLinecap="round" />
          </svg>
          <input
            className="flex-1 bg-transparent outline-none text-[13px] placeholder:text-[#9bb8c3]"
            style={{ color: 'var(--foreground)' }}
            placeholder="搜索书签标题、URL、分类…"
            value={query}
            onChange={(e) => { setQuery(e.target.value); setSelectedFolder(null) }}
          />
          {query && (
            <button
              onClick={() => setQuery('')}
              className="text-[11px] w-4 h-4 rounded-full flex items-center justify-center flex-shrink-0"
              style={{ background: '#9bb8c3', color: '#fff' }}
            >
              ×
            </button>
          )}
        </div>
        <button
          onClick={() => { load(); toast('已刷新', '书签整理结果', 'success') }}
          className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-[13px] font-600 flex-shrink-0"
          style={{ background: 'rgba(var(--primary-ink-rgb) / 0.10)', color: 'var(--primary-ink)' }}
        >
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" className="w-3.5 h-3.5">
            <path d="M13.5 8a5.5 5.5 0 11-1.6-3.9M13.5 2.5v2.5H11" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          刷新
        </button>
      </div>

      {loading && snapshot === null ? (
        <EmptyState icon="⏳" title="正在加载整理结果…" hint="loading bookmarks summary" />
      ) : snapshot === null ? (
        <EmptyGuide onRefresh={() => load()} theme={theme} />
      ) : (
        <>
          <StatsRow snapshot={snapshot} />
          <div className="flex flex-1 min-h-0 gap-4 mt-4">
            {/* 左侧分类导航 */}
            <FolderNav
              groups={filteredGroups}
              total={snapshot.unique}
              selected={selectedFolder}
              theme={theme}
              onSelect={(folder) => { setSelectedFolder(folder); setQuery('') }}
            />
            {/* 右侧书签列表 */}
            <div className="flex-1 min-w-0 overflow-y-auto flex flex-col gap-4 pr-1">
              {visibleGroups.length === 0 ? (
                <EmptyState icon="🔍" title="没有匹配的书签" hint="换个关键词或分类试试" />
              ) : (
                visibleGroups.map((group) => (
                  <GroupCard key={group.folderPath} group={group} onCopy={handleCopy} onOpenAll={handleOpenAll} />
                ))
              )}
            </div>
          </div>
        </>
      )}

      {error && snapshot !== null && (
        <div className="mt-2 text-[12px] flex-shrink-0" style={{ color: '#9f1239' }}>
          自动刷新失败：{error}
        </div>
      )}
    </div>
  )
}

function StatsRow({ snapshot }: { snapshot: BookmarkSummary }) {
  const items = [
    { label: '全部书签', value: snapshot.total, icon: '🗂️' },
    { label: '去重后', value: snapshot.unique, icon: '✨' },
    { label: '文件夹分类', value: snapshot.groups.length, icon: '📁' },
    { label: '过滤内部页', value: snapshot.filtered, icon: '🚫' },
  ]
  return (
    <div className="flex-shrink-0">
      <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(4, 1fr)' }}>
        {items.map((item) => (
          <div
            key={item.label}
            className="px-4 py-2.5 flex items-center gap-2.5"
            style={{
              borderRadius: 14,
              background: 'rgba(var(--surface-rgb) / 0.88)',
              backdropFilter: 'blur(20px) saturate(120%)',
              WebkitBackdropFilter: 'blur(20px) saturate(120%)',
              border: '1px solid rgba(var(--hairline-rgb) / 0.18)',
              boxShadow: '0 2px 12px rgba(var(--shadow-rgb) / 0.10), inset 0 1px 0 rgba(255,255,255,0.8)',
            }}
          >
            <span className="text-[15px]">{item.icon}</span>
            <div className="flex-1 min-w-0">
              <div className="text-[10.5px] truncate" style={{ color: 'var(--muted-foreground)' }}>{item.label}</div>
              <div className="text-[17px] font-700 leading-tight" style={{ color: 'var(--foreground)' }}>{item.value}</div>
            </div>
          </div>
        ))}
      </div>
      <div className="mt-2 text-[11px]" style={{ color: 'var(--muted-foreground)' }}>
        整理时间：{formatTime(snapshot.collectedAt)}（每 5 秒自动刷新）
      </div>
    </div>
  )
}

function FolderNav({
  groups,
  total,
  selected,
  theme,
  onSelect,
}: {
  groups: BookmarkGroup[]
  total: number
  selected: string | null
  theme: ThemeLike
  onSelect: (folder: string | null) => void
}) {
  const navItem = (active: boolean) => ({
    background: active ? 'var(--fill-gradient)' : 'rgba(var(--surface-rgb) / 0.72)',
    color: active ? 'var(--primary-foreground)' : 'var(--foreground)',
    boxShadow: active ? '0 4px 12px rgba(var(--shadow-rgb) / 0.18)' : 'none',
  })
  return (
    <aside
      className="w-56 flex-shrink-0 overflow-y-auto p-2"
      style={{
        borderRadius: 20,
        background: 'rgba(var(--surface-rgb) / 0.88)',
        backdropFilter: 'blur(24px) saturate(120%)',
        WebkitBackdropFilter: 'blur(24px) saturate(120%)',
        border: '1px solid rgba(var(--hairline-rgb) / 0.18)',
        boxShadow: '0 4px 24px rgba(var(--shadow-rgb) / 0.08), inset 0 1px 0 rgba(255,255,255,0.8)',
      }}
    >
      <div className="px-2 pt-1 pb-2 text-[11px] font-600" style={{ color: 'var(--muted-foreground)' }}>分类</div>
      <button
        onClick={() => onSelect(null)}
        className="w-full flex items-center gap-2 rounded-xl px-3 py-2 mb-1 text-[13px] font-500 transition-all duration-200"
        style={navItem(selected === null)}
      >
        <span className="text-[14px]">🗂️</span>
        <span className="flex-1 text-left truncate">全部书签</span>
        <span className="text-[11px] font-600 opacity-80">{total}</span>
      </button>
      {groups.map((group) => {
        const active = selected === group.folderPath
        return (
          <button
            key={group.folderPath}
            onClick={() => onSelect(group.folderPath)}
            className="w-full flex items-center gap-2 rounded-xl px-3 py-2 mb-1 text-[13px] font-500 transition-all duration-200"
            style={navItem(active)}
          >
            <span className="text-[14px]">📁</span>
            <span className="flex-1 text-left truncate" title={group.folderPath}>{group.folderPath}</span>
            <span className="text-[11px] font-600 opacity-80">{group.count}</span>
          </button>
        )
      })}
    </aside>
  )
}

function GroupCard({
  group,
  onCopy,
  onOpenAll,
}: {
  group: BookmarkGroup
  onCopy: (item: BookmarkItem) => void
  onOpenAll: (group: BookmarkGroup) => void
}) {
  return (
    <section
      className="p-4"
      style={{
        borderRadius: 20,
        background: 'rgba(var(--surface-rgb) / 0.88)',
        backdropFilter: 'blur(24px) saturate(120%)',
        WebkitBackdropFilter: 'blur(24px) saturate(120%)',
        border: '1px solid rgba(var(--hairline-rgb) / 0.18)',
        boxShadow: '0 4px 24px rgba(var(--shadow-rgb) / 0.08), inset 0 1px 0 rgba(255,255,255,0.8)',
      }}
    >
      <div className="flex items-center gap-2 mb-3">
        <span className="text-[15px]">📁</span>
        <h2 className="font-600 text-[14px] truncate flex-1" style={{ color: 'var(--foreground)' }}>{group.folderPath}</h2>
        <span
          className="text-[11px] px-2 py-0.5 rounded-full font-500 flex-shrink-0"
          style={{ background: 'rgba(var(--primary-ink-rgb) / 0.10)', color: 'var(--primary-ink)' }}
        >
          {group.count} 个书签
        </span>
        <button
          onClick={() => onOpenAll(group)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-[12px] font-600 flex-shrink-0"
          style={{ background: 'rgba(var(--primary-ink-rgb) / 0.10)', color: 'var(--primary-ink)' }}
        >
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" className="w-3.5 h-3.5">
            <path d="M6 3.5h6.5V10M9.5 6.5L3 13" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          全部打开
        </button>
      </div>
      <div className="flex flex-col gap-1.5">
        {group.items.map((item, idx) => (
          <div
            key={idx}
            className="flex items-center gap-3 rounded-xl px-3 py-2 group"
            style={{
              background: 'rgba(var(--surface-rgb) / 0.72)',
              border: '1px solid rgba(var(--hairline-rgb) / 0.18)',
            }}
          >
            {faviconFallback(item.url) ? (
              <img
                src={faviconFallback(item.url)}
                alt=""
                className="w-5 h-5 rounded flex-shrink-0"
                onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none' }}
              />
            ) : (
              <span className="text-[15px]">🔗</span>
            )}
            <a
              href={item.url}
              target="_blank"
              rel="noreferrer"
              className="flex-1 min-w-0 text-left"
              title={`打开 ${item.url}`}
            >
              <div className="text-[13px] truncate" style={{ color: 'var(--foreground)' }}>{item.title || item.url}</div>
              <div className="text-[11px] truncate font-mono" style={{ color: 'var(--muted-foreground)' }}>{item.url}</div>
            </a>
            <button
              onClick={() => onCopy(item)}
              title="复制链接"
              className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 transition-colors"
              style={{ background: 'rgba(var(--primary-ink-rgb) / 0.10)', color: 'var(--primary-ink)' }}
            >
              <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" className="w-3.5 h-3.5">
                <rect x="5.5" y="5.5" width="8" height="8" rx="1.5" />
                <path d="M10.5 5.5v-2A1.5 1.5 0 009 2H4a1.5 1.5 0 00-1.5 1.5v5A1.5 1.5 0 004 10h1.5" strokeLinejoin="round" />
              </svg>
            </button>
          </div>
        ))}
      </div>
    </section>
  )
}

function EmptyState({ icon, title, hint }: { icon: string; title: string; hint: string }) {
  return (
    <div
      className="flex flex-col items-center justify-center py-24 gap-3"
      style={{
        borderRadius: 20,
        background: 'rgba(var(--surface-rgb) / 0.80)',
        backdropFilter: 'blur(16px)',
        WebkitBackdropFilter: 'blur(16px)',
        border: '1px solid rgba(var(--hairline-rgb) / 0.18)',
        boxShadow: '0 2px 12px rgba(var(--shadow-rgb) / 0.06)',
      }}
    >
      <div className="text-3xl">{icon}</div>
      <div className="font-500 text-[15px]" style={{ color: 'var(--muted-foreground)' }}>{title}</div>
      <div className="text-[12px]" style={{ fontFamily: "'DM Mono', monospace", color: 'var(--color-mid)' }}>{hint}</div>
    </div>
  )
}

function EmptyGuide({ onRefresh, theme }: { onRefresh: () => void; theme: ThemeLike }) {
  const steps = [
    ['1', '启动 ai-base 桌面应用（当前已在本应用内）'],
    ['2', 'Chrome 打开 chrome://extensions，开启「开发者模式」'],
    ['3', '点击「加载已解压的扩展程序」，选择 apps/chrome-extension 目录'],
    ['4', '点击浏览器工具栏的「书签整理助手」，再点「整理书签」'],
  ]
  return (
    <div
      className="flex flex-col items-center py-14 px-8 mt-4"
      style={{
        borderRadius: 20,
        background: 'rgba(var(--surface-rgb) / 0.80)',
        backdropFilter: 'blur(16px)',
        WebkitBackdropFilter: 'blur(16px)',
        border: '1px solid rgba(var(--hairline-rgb) / 0.18)',
        boxShadow: '0 2px 12px rgba(var(--shadow-rgb) / 0.06)',
      }}
    >
      <div className="text-4xl mb-2">🧭</div>
      <div className="font-600 text-[16px]" style={{ color: 'var(--foreground)' }}>还没有整理结果</div>
      <div className="text-[12px] mt-1 mb-6" style={{ color: 'var(--muted-foreground)' }}>
        安装 Chrome 扩展后，一键整理你的收藏书签
      </div>
      <ol className="flex flex-col gap-2 w-full max-w-md">
        {steps.map(([no, text]) => (
          <li key={no} className="flex items-center gap-3 rounded-xl px-3 py-2.5" style={{ background: 'rgba(var(--surface-rgb) / 0.88)' }}>
            <span
              className="w-5 h-5 rounded-full flex items-center justify-center text-[11px] font-700 flex-shrink-0"
              style={{ background: 'var(--fill-gradient)', color: 'var(--primary-foreground)' }}
            >
              {no}
            </span>
            <span className="text-[13px]" style={{ color: 'var(--foreground)' }}>{text}</span>
          </li>
        ))}
      </ol>
      <button
        onClick={onRefresh}
        className="mt-6 px-5 py-2 rounded-xl text-[13px] font-600"
        style={{ background: 'var(--fill-gradient)', color: 'var(--primary-foreground)', boxShadow: '0 3px 12px rgba(var(--shadow-rgb) / 0.20)' }}
      >
        我已整理，刷新查看
      </button>
    </div>
  )
}
