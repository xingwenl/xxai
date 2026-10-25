/**
 * 「念记」笔记界面：左栏分类 / 中栏列表 / 右栏编辑器。
 *
 * 数据只来自 src/lib/store.ts：整份快照用 useSyncExternalStore 订阅，写操作统一走
 * store 的串行队列，界面不复制数据源。正文是纯文本 Markdown，编辑用 textarea
 * （不用 contentEditable），工具栏只负责在光标处插入 Markdown 记号。
 */
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import type { CSSProperties } from 'react'
import {
  subscribe,
  getData,
  getStorageMode,
  listNotes,
  getNote,
  listCategories,
  trashNotes,
  createNote,
  updateNote,
  setCategory,
  addCategory,
  deleteNote,
  restoreNote,
  purgeNote,
} from './lib/store'
import type { NoteQuery, NoteListResult, CreateNoteInput, UpdateNoteInput } from './lib/store'
import type { CategoryCount, Note, NoteView } from './lib/types'
import { excerptOf, fallbackTitle, formatNoteDate, formatLongDate } from './lib/format'

/** 侧栏两个特殊视图：全部笔记与废纸篓；其余取值都是分类名。 */
const ALL = '__all__'
const TRASH = '__trash__'
/** 输入后 500ms 落库，连续输入只写最后一次。 */
const SAVE_DELAY = 500
/** 列表上限与工具契约一致。 */
const LIST_LIMIT = 200
/** 仓库回退标题：空草稿在数据里就是这个词，界面复用它做 placeholder 与判断。 */
const PLACEHOLDER_TITLE = fallbackTitle('', '')
/** 仓库回退标题在界面上按"无标题"显示：输入框留空走 placeholder，卡片标题降一级颜色。 */
const isPlaceholderTitle = (title: string) => title === PLACEHOLDER_TITLE

type SaveState = 'saved' | 'saving' | 'error'

/** 内置分类各一组柔和渐变；封面不给用户传图，只靠分类确定性取色。 */
const COVER_GRADIENTS: Record<string, string> = {
  思考: 'linear-gradient(135deg, #e8efe6 0%, #cfdfd2 100%)',
  灵感: 'linear-gradient(135deg, #f1eae2 0%, #e3d5c8 100%)',
  阅读: 'linear-gradient(135deg, #e8ecf2 0%, #d6dee9 100%)',
  旅行: 'linear-gradient(135deg, #e9efe9 0%, #d6e4dc 100%)',
  工作: 'linear-gradient(135deg, #e9e7d9 0%, #d8d5c3 100%)',
}

/** 分类 → 封面渐变：同一分类颜色恒定，自定义分类用名称哈希在色相环上取色。 */
function coverStyle(category: string): CSSProperties {
  const preset = COVER_GRADIENTS[category]
  if (preset) return { backgroundImage: preset }
  let hue = 0
  for (let index = 0; index < category.length; index += 1) {
    hue = (hue * 31 + category.charCodeAt(index)) % 360
  }
  return {
    backgroundImage: `linear-gradient(135deg, hsl(${hue} 22% 91%) 0%, hsl(${(hue + 26) % 360} 20% 83%) 100%)`,
  }
}

/** 设计稿同款线条图标（stroke-width 1.7 由 styles.css 统一控制）。 */
const ICON_PATHS = {
  search: (
    <>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-4-4" />
    </>
  ),
  plus: <path d="M12 5v14M5 12h14" />,
  note: (
    <>
      <path d="M6 3h9l4 4v14H6z" />
      <path d="M15 3v5h5M9 12h7M9 16h5" />
    </>
  ),
  trash: (
    <>
      <path d="M5 7h14M9 7V4h6v3M7 7l1 13h8l1-13" />
    </>
  ),
  more: (
    <>
      <circle cx="5" cy="12" r="1" />
      <circle cx="12" cy="12" r="1" />
      <circle cx="19" cy="12" r="1" />
    </>
  ),
  link: (
    <>
      <path d="M10 13a5 5 0 0 0 7 0l2-2a5 5 0 0 0-7-7l-1 1" />
      <path d="M14 11a5 5 0 0 0-7 0l-2 2a5 5 0 0 0 7 7l1-1" />
    </>
  ),
} as const

type IconName = keyof typeof ICON_PATHS

function Icon({ name }: { name: IconName }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      {ICON_PATHS[name]}
    </svg>
  )
}

export default function App() {
  // 单一数据源：store 每次写入都会替换快照并通知订阅者。
  const data = useSyncExternalStore(subscribe, getData)
  const categories = useMemo<CategoryCount[]>(() => listCategories(), [data])
  const deletedNotes = useMemo<NoteView[]>(() => trashNotes(), [data])
  const allCount = useMemo(() => listNotes({}).total, [data])

  const [view, setView] = useState<string>(ALL)
  const [search, setSearch] = useState('')
  const [activeId, setActiveId] = useState<string | null>(null)
  const [titleDraft, setTitleDraft] = useState('')
  const [contentDraft, setContentDraft] = useState('')
  const [saveState, setSaveState] = useState<SaveState>('saved')
  const [menuOpen, setMenuOpen] = useState(false)
  const [toast, setToast] = useState('')
  const [addingCategory, setAddingCategory] = useState(false)
  const [categoryDraft, setCategoryDraft] = useState('')
  const [categoryError, setCategoryError] = useState('')
  const [confirmPurge, setConfirmPurge] = useState(false)

  const titleRef = useRef<HTMLInputElement | null>(null)
  const contentRef = useRef<HTMLTextAreaElement | null>(null)
  const menuRef = useRef<HTMLDivElement | null>(null)
  const saveTimer = useRef<number | null>(null)
  const toastTimer = useRef<number | null>(null)
  const pendingPatch = useRef<UpdateNoteInput | null>(null)

  const isTrash = view === TRASH

  /** 当前笔记：优先走 store 的 getNote，废纸篓里的软删笔记再从快照兜底。 */
  const activeNote = useMemo<Note | null>(() => {
    if (!activeId) return null
    return getNote(activeId) ?? data.notes.find((note) => note.id === activeId) ?? null
  }, [activeId, data])

  /** 分类下拉：内置 + 自定义分类，外加当前笔记可能存在的历史分类。 */
  const categoryNames = useMemo(() => {
    const names = categories.map((item) => item.name)
    if (activeNote && !names.includes(activeNote.category)) names.push(activeNote.category)
    return names
  }, [activeNote, categories])

  const visibleNotes = useMemo<NoteView[]>(() => {
    const keyword = search.trim()
    if (isTrash) {
      if (!keyword) return deletedNotes
      const lower = keyword.toLowerCase()
      return deletedNotes.filter((note) => `${note.title}${note.excerpt}`.toLowerCase().includes(lower))
    }
    const query: NoteQuery = {
      query: keyword || undefined,
      category: view === ALL ? undefined : view,
      limit: LIST_LIMIT,
    }
    const result: NoteListResult = listNotes(query)
    return result.items
  }, [deletedNotes, isTrash, search, view])

  const showToast = useCallback((text: string) => {
    setToast(text)
    if (toastTimer.current !== null) window.clearTimeout(toastTimer.current)
    toastTimer.current = window.setTimeout(() => setToast(''), 1800)
  }, [])

  /** 立即落库：切换笔记、删除、卸载前都先 flush，避免 500ms 缓冲里的字丢掉。 */
  const flushSave = useCallback(() => {
    if (saveTimer.current !== null) {
      window.clearTimeout(saveTimer.current)
      saveTimer.current = null
    }
    const patch = pendingPatch.current
    if (!patch) return
    pendingPatch.current = null
    setSaveState('saving')
    updateNote(patch).then(
      () => setSaveState(pendingPatch.current ? 'saving' : 'saved'),
      () => {
        setSaveState('error')
        showToast('保存失败，稍后会自动重试')
      },
    )
  }, [showToast])

  const scheduleSave = useCallback((patch: UpdateNoteInput) => {
    if (pendingPatch.current && pendingPatch.current.id !== patch.id) flushSave()
    // 同一篇笔记的多次输入合并成一次写库
    pendingPatch.current = { ...(pendingPatch.current ?? {}), ...patch }
    setSaveState('saving')
    if (saveTimer.current !== null) window.clearTimeout(saveTimer.current)
    saveTimer.current = window.setTimeout(flushSave, SAVE_DELAY)
  }, [flushSave])

  // 卸载前把未落库内容写完（例如宿主切走 iframe），避免丢字。
  useEffect(() => () => flushSave(), [flushSave])

  // 外部数据变化（含 AI 工具写入）时同步草稿；本地还有未落库编辑时不动，防止覆盖用户输入。
  useEffect(() => {
    if (pendingPatch.current) return
    if (!activeId) {
      setTitleDraft('')
      setContentDraft('')
      return
    }
    setTitleDraft(activeNote?.title ?? '')
    setContentDraft(activeNote?.content ?? '')
  }, [activeId, activeNote])

  // textarea 随内容长高，滚动交给编辑器容器，避免内层出现第二条滚动条。
  useEffect(() => {
    const element = contentRef.current
    if (!element) return
    element.style.height = 'auto'
    element.style.height = `${element.scrollHeight}px`
  }, [activeId, contentDraft, isTrash])

  useEffect(() => () => {
    if (toastTimer.current !== null) window.clearTimeout(toastTimer.current)
  }, [])

  // 「更多」菜单：点击外部或按 Esc 关闭。
  useEffect(() => {
    if (!menuOpen) return
    const handlePointer = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) setMenuOpen(false)
    }
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMenuOpen(false)
    }
    document.addEventListener('mousedown', handlePointer)
    document.addEventListener('keydown', handleKey)
    return () => {
      document.removeEventListener('mousedown', handlePointer)
      document.removeEventListener('keydown', handleKey)
    }
  }, [menuOpen])

  // 换笔记时重置「彻底删除」的二次确认状态
  useEffect(() => setConfirmPurge(false), [activeId])

  /** 切换视图：只有当前笔记仍属于新视图时才保留选中，否则回到空态引导。 */
  const switchView = (next: string) => {
    flushSave()
    setView(next)
    setSearch('')
    setMenuOpen(false)
    setConfirmPurge(false)
    setActiveId((current) => {
      if (!current) return null
      const note = data.notes.find((item) => item.id === current)
      if (!note) return null
      if (next === TRASH) return note.deleted_at ? current : null
      if (note.deleted_at) return null
      return next === ALL || note.category === next ? current : null
    })
  }

  const selectNote = (id: string) => {
    if (id === activeId) return
    flushSave()
    setMenuOpen(false)
    setActiveId(id)
  }

  const handleCreate = async () => {
    flushSave()
    const category = view !== ALL && view !== TRASH ? view : categories[0]?.name ?? '思考'
    const input: CreateNoteInput = { content: '', category }
    try {
      const note = await createNote(input)
      if (isTrash) setView(ALL)
      setSearch('')
      setActiveId(note.id)
      // 新建后直接聚焦标题，少点一次
      window.requestAnimationFrame(() => titleRef.current?.focus())
    } catch {
      showToast('新建失败，请稍后重试')
    }
  }

  const handleTitleChange = (value: string) => {
    setTitleDraft(value)
    if (activeNote) scheduleSave({ id: activeNote.id, title: value })
  }

  const handleContentChange = (value: string) => {
    setContentDraft(value)
    if (activeNote) scheduleSave({ id: activeNote.id, content: value })
  }

  const handleCategoryChange = async (name: string) => {
    if (!activeNote) return
    flushSave()
    await setCategory(activeNote.id, name)
    showToast(`已归到「${name}」`)
  }

  const handleCopy = async () => {
    if (!activeNote) return
    setMenuOpen(false)
    const text = [titleDraft.trim(), contentDraft].filter(Boolean).join('\n\n')
    try {
      if (!navigator.clipboard) throw new Error('clipboard unavailable')
      await navigator.clipboard.writeText(text)
      showToast('正文已复制')
    } catch {
      showToast('复制失败，请手动选中正文')
    }
  }

  const handleTrashNote = async (id: string) => {
    flushSave()
    setMenuOpen(false)
    await deleteNote(id)
    setActiveId(null)
    showToast('已移到废纸篓')
  }

  const handleRestore = async (id: string) => {
    await restoreNote(id)
    setActiveId(null)
    showToast('已恢复到笔记列表')
  }

  const handlePurge = async (id: string) => {
    // 彻底删除不可撤销，第一次点击只进入确认态
    if (!confirmPurge) {
      setConfirmPurge(true)
      return
    }
    await purgeNote(id)
    setConfirmPurge(false)
    setActiveId(null)
    showToast('笔记已彻底删除')
  }

  const submitCategory = async () => {
    const name = categoryDraft.trim()
    if (!name) {
      setAddingCategory(false)
      setCategoryDraft('')
      setCategoryError('')
      return
    }
    if (name.length > 20) {
      setCategoryError('分类名最多 20 个字')
      return
    }
    if (categories.some((item) => item.name === name)) {
      setCategoryError('已有同名分类')
      return
    }
    await addCategory(name)
    setAddingCategory(false)
    setCategoryDraft('')
    setCategoryError('')
    setView(name)
    setActiveId(null)
  }

  // 工具栏：用 Markdown 记号替换/包裹选区，没有选区时插入占位文字并选中它。
  const wrapSelection = (prefix: string, suffix: string, placeholder: string) => {
    const element = contentRef.current
    if (!element || !activeNote) return
    const start = element.selectionStart ?? contentDraft.length
    const end = element.selectionEnd ?? start
    const body = contentDraft.slice(start, end) || placeholder
    const next = `${contentDraft.slice(0, start)}${prefix}${body}${suffix}${contentDraft.slice(end)}`
    setContentDraft(next)
    scheduleSave({ id: activeNote.id, content: next })
    const caret = start + prefix.length
    window.requestAnimationFrame(() => {
      element.focus()
      element.setSelectionRange(caret, caret + body.length)
    })
  }

  const prefixLine = (prefix: string) => {
    const element = contentRef.current
    if (!element || !activeNote) return
    const start = element.selectionStart ?? 0
    const end = element.selectionEnd ?? start
    const lineStart = contentDraft.lastIndexOf('\n', Math.max(0, start - 1)) + 1
    if (contentDraft.startsWith(prefix, lineStart)) {
      element.focus()
      return
    }
    const next = `${contentDraft.slice(0, lineStart)}${prefix}${contentDraft.slice(lineStart)}`
    setContentDraft(next)
    scheduleSave({ id: activeNote.id, content: next })
    window.requestAnimationFrame(() => {
      element.focus()
      element.setSelectionRange(start + prefix.length, end + prefix.length)
    })
  }

  const listTitle = isTrash ? '废纸篓' : view === ALL ? '全部笔记' : view
  const listSummary = isTrash ? `${deletedNotes.length} 篇已删除` : `${visibleNotes.length} 篇笔记`

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">N</span>
          <span className="brand-text">念记</span>
        </div>

        <button type="button" className="new-note" aria-label="新建笔记" title="新建笔记" onClick={() => void handleCreate()}>
          <Icon name="plus" />
          <span className="new-note-text">新建笔记</span>
        </button>

        <nav>
          <p className="nav-label">空间</p>
          <button
            type="button"
            className={`nav-row ${view === ALL ? 'active' : ''}`}
            aria-label="我的笔记"
            title="我的笔记"
            aria-current={view === ALL ? 'true' : undefined}
            onClick={() => switchView(ALL)}
          >
            <Icon name="note" />
            <span className="nav-text">我的笔记</span>
            <b>{allCount}</b>
          </button>

          <p className="nav-label categories-label">分类</p>
          {categories.map((item) => (
            <button
              key={item.name}
              type="button"
              className={`nav-row ${view === item.name ? 'active' : ''}`}
              aria-label={item.name}
              title={item.name}
              aria-current={view === item.name ? 'true' : undefined}
              onClick={() => switchView(item.name)}
            >
              <span className="category-dot" aria-hidden="true" />
              <span className="nav-text">{item.name}</span>
              <b>{item.count}</b>
            </button>
          ))}

          {addingCategory ? (
            <form
              className="category-form"
              onSubmit={(event) => {
                event.preventDefault()
                void submitCategory()
              }}
            >
              <input
                className="category-input"
                value={categoryDraft}
                maxLength={20}
                autoFocus
                placeholder="分类名称"
                aria-label="新分类名称"
                onChange={(event) => {
                  setCategoryDraft(event.target.value)
                  setCategoryError('')
                }}
                onKeyDown={(event) => {
                  if (event.key === 'Escape') {
                    setAddingCategory(false)
                    setCategoryDraft('')
                    setCategoryError('')
                  }
                }}
              />
              {categoryError && <p className="category-error" role="alert">{categoryError}</p>}
            </form>
          ) : (
            <button
              type="button"
              className="add-category"
              aria-label="新建分类"
              title="新建分类"
              onClick={() => setAddingCategory(true)}
            >
              <Icon name="plus" />
              <span className="nav-text">新分类</span>
            </button>
          )}
        </nav>

        <div className="sidebar-bottom">
          <button
            type="button"
            className={`nav-row ${isTrash ? 'active' : ''}`}
            aria-label="废纸篓"
            title="废纸篓"
            aria-current={isTrash ? 'true' : undefined}
            onClick={() => switchView(TRASH)}
          >
            <Icon name="trash" />
            <span className="nav-text">废纸篓</span>
            <b>{deletedNotes.length}</b>
          </button>
          <p className="storage-line">{getStorageMode() === 'desktop' ? '桌面存储' : '本地存储'}</p>
        </div>
      </aside>

      <section className="note-list">
        <header className="list-header">
          <div className="list-heading">
            <h1>{listTitle}</h1>
            <p>{listSummary}</p>
          </div>
          <div className="search">
            <Icon name="search" />
            <input
              type="search"
              value={search}
              placeholder="搜索笔记"
              aria-label="搜索笔记"
              onChange={(event) => setSearch(event.target.value)}
            />
          </div>
        </header>

        <div className="cards">
          {visibleNotes.map((note) => {
            const selected = note.id === activeId
            const stamp = note.deleted_at ?? note.updated_at
            return (
              <button
                key={note.id}
                type="button"
                className={`note-card ${selected ? 'selected' : ''}`}
                aria-current={selected ? 'true' : undefined}
                onClick={() => selectNote(note.id)}
              >
                <span className="card-cover" style={coverStyle(note.category)} aria-hidden="true" />
                <span className="card-content">
                  <span className="card-meta">
                    <span className="card-tag">{note.category}</span>
                    <time dateTime={stamp}>{formatNoteDate(stamp)}</time>
                  </span>
                  <span className={`note-title ${isPlaceholderTitle(note.title) ? 'is-placeholder' : ''}`}>
                    {note.title || PLACEHOLDER_TITLE}
                  </span>
                  <span className="note-excerpt">{excerptOf(note.excerpt, 96) || '还没有正文'}</span>
                </span>
              </button>
            )
          })}
          {visibleNotes.length === 0 && (
            <p className="empty">
              {search.trim()
                ? '没有匹配的笔记，换个关键词试试'
                : isTrash
                  ? '废纸篓是空的'
                  : '这里还没有笔记，点左上角「新建笔记」开始记录'}
            </p>
          )}
        </div>
      </section>

      <section className="editor">
        {!isTrash && activeNote ? (
          <>
            <header className="editor-top">
              <div className={`save-state ${saveState}`}>
                <span className="save-dot" aria-hidden="true" />
                <small>{saveState === 'saving' ? '保存中' : saveState === 'error' ? '保存失败' : '已保存'}</small>
              </div>
              <div className="editor-actions">
                <div className="menu-wrap" ref={menuRef}>
                  <button
                    type="button"
                    className="icon-btn"
                    aria-label="更多操作"
                    aria-haspopup="menu"
                    aria-expanded={menuOpen}
                    onClick={() => setMenuOpen((open) => !open)}
                  >
                    <Icon name="more" />
                  </button>
                  {menuOpen && (
                    <div className="menu" role="menu">
                      <button type="button" role="menuitem" onClick={() => void handleCopy()}>复制正文</button>
                      <button
                        type="button"
                        role="menuitem"
                        className="danger"
                        onClick={() => void handleTrashNote(activeNote.id)}
                      >
                        移到废纸篓
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </header>

            <div className="editor-body">
              <div className="tagline">
                <select
                  className="category-select"
                  value={activeNote.category}
                  aria-label="选择笔记分类"
                  onChange={(event) => void handleCategoryChange(event.target.value)}
                >
                  {categoryNames.map((name) => (
                    <option key={name} value={name}>{name}</option>
                  ))}
                </select>
                <time dateTime={activeNote.updated_at}>{formatLongDate(activeNote.updated_at)}</time>
              </div>

              <input
                ref={titleRef}
                className="title-input"
                value={isPlaceholderTitle(titleDraft) ? '' : titleDraft}
                maxLength={120}
                placeholder={PLACEHOLDER_TITLE}
                aria-label="笔记标题"
                onChange={(event) => handleTitleChange(event.target.value)}
                onKeyDown={(event) => {
                  // 标题里按 Enter 直接跳到正文，符合「先写标题再写内容」的习惯
                  if (event.key === 'Enter') {
                    event.preventDefault()
                    contentRef.current?.focus()
                  }
                }}
              />

              <div className="cover" style={coverStyle(activeNote.category)} aria-hidden="true" />

              <textarea
                ref={contentRef}
                className="content-input"
                value={contentDraft}
                placeholder="从这里开始书写。支持 Markdown 记号，工具栏可以把记号插到光标处。"
                aria-label="笔记正文"
                spellCheck={false}
                onChange={(event) => handleContentChange(event.target.value)}
              />
            </div>

            <div className="toolbar" role="toolbar" aria-label="插入 Markdown 记号">
              <button type="button" onClick={() => prefixLine('## ')} aria-label="插入二级标题">
                <strong>H2</strong>
              </button>
              <button type="button" onClick={() => wrapSelection('**', '**', '加粗文字')} aria-label="插入加粗">
                <strong>B</strong>
              </button>
              <button type="button" onClick={() => wrapSelection('*', '*', '斜体文字')} aria-label="插入斜体">
                <i>I</i>
              </button>
              <span className="tool-divider" aria-hidden="true" />
              <button type="button" onClick={() => wrapSelection('[', '](url)', '链接文字')} aria-label="插入链接">
                <Icon name="link" />
              </button>
              <button type="button" onClick={() => prefixLine('- ')} aria-label="插入无序列表">
                <span aria-hidden="true">–</span>
              </button>
              <button type="button" onClick={() => prefixLine('> ')} aria-label="插入引用">
                <span aria-hidden="true">&gt;</span>
              </button>
            </div>
          </>
        ) : isTrash ? (
          <>
            <header className="editor-top">
              <span className="readonly-badge">废纸篓 · 只读预览</span>
            </header>
            <div className="editor-body trash-view">
              {activeNote ? (
                <>
                  <div className="tagline">
                    <span className="card-tag">{activeNote.category}</span>
                    <time dateTime={activeNote.deleted_at ?? activeNote.updated_at}>
                      删除于 {formatLongDate(activeNote.deleted_at ?? activeNote.updated_at)}
                    </time>
                  </div>
                  <h2 className={`trash-title ${isPlaceholderTitle(activeNote.title) ? 'is-placeholder' : ''}`}>
                    {activeNote.title || PLACEHOLDER_TITLE}
                  </h2>
                  <pre className="trash-preview">{activeNote.content || '这篇笔记没有正文。'}</pre>
                  <div className="trash-actions">
                    <button type="button" className="primary-btn" onClick={() => void handleRestore(activeNote.id)}>
                      恢复
                    </button>
                    <button
                      type="button"
                      className={`danger-btn ${confirmPurge ? 'confirm' : ''}`}
                      onClick={() => void handlePurge(activeNote.id)}
                    >
                      {confirmPurge ? '确认彻底删除' : '彻底删除'}
                    </button>
                  </div>
                </>
              ) : (
                <div className="editor-empty-inner">
                  <h2>{deletedNotes.length ? '选择一篇已删除的笔记' : '废纸篓是空的'}</h2>
                  <p>
                    {deletedNotes.length
                      ? '这里只做只读预览，可以恢复到列表或彻底删除。'
                      : '删除的笔记会先进入废纸篓，随时可以恢复。'}
                  </p>
                </div>
              )}
            </div>
          </>
        ) : (
          <div className="editor-empty">
            <span className="empty-mark" aria-hidden="true">N</span>
            <h2>{allCount === 0 ? '还没有笔记' : '选择一篇笔记开始'}</h2>
            <p>
              {allCount === 0
                ? '点下面的按钮写下第一篇；也可以直接对桌面助手说「记一条笔记：今天的想法」，内容会实时出现在这里。'
                : '左侧列表点开任意一篇继续书写；桌面助手记下的内容也会实时同步到这里。'}
            </p>
            <button type="button" className="empty-action" onClick={() => void handleCreate()}>
              <Icon name="plus" />
              <span>新建笔记</span>
            </button>
          </div>
        )}

        {toast && <div className="toast" role="status">{toast}</div>}
      </section>
    </main>
  )
}
