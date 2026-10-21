// 通用弹窗：遮罩 + 居中卡片，支持 Esc / 点遮罩关闭，渲染到 body 避免被父级 overflow 或 transform 裁剪。
// 设置页及后续页面需要「浮层里做一件事」时复用它，不要在业务组件里各写一套 fixed 遮罩。

import { useEffect, useId, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

export interface DialogProps {
  open: boolean
  /** 标题，展示在卡片头部 */
  title: ReactNode
  /** 标题下方的补充说明（可选） */
  description?: ReactNode
  children: ReactNode
  /** 底部操作区；不传则不渲染分隔线与按钮栏 */
  footer?: ReactNode
  onClose: () => void
  /** 卡片最大宽度（px），默认 520 */
  width?: number
  /** 点击遮罩是否关闭，默认 true */
  closeOnBackdrop?: boolean
}

export default function Dialog({
  open,
  title,
  description,
  children,
  footer,
  onClose,
  width = 520,
  closeOnBackdrop = true,
}: DialogProps) {
  const titleId = useId()
  const panelRef = useRef<HTMLDivElement>(null)
  // onClose 每次渲染都可能是新函数，用 ref 保存避免把 Esc 监听反复解绑重绑
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  useEffect(() => {
    if (!open) return
    // 打开时把焦点移进卡片（优先第一个输入控件，没有则聚焦卡片本身，避免一进来就落在
    // 右上角关闭按钮上）；关闭后还给原来的元素，键盘用户不会丢失位置
    const previous = document.activeElement as HTMLElement | null
    const panel = panelRef.current
    const field = panel?.querySelector<HTMLElement>(
      'input:not([disabled]), select:not([disabled]), textarea:not([disabled])',
    )
    const focusTarget = field ?? panel
    focusTarget?.focus()

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onCloseRef.current()
      }
    }
    window.addEventListener('keydown', handleKeyDown)

    // 弹窗期间锁住背景滚动，避免滚轮带着设置页一起动
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    return () => {
      window.removeEventListener('keydown', handleKeyDown)
      document.body.style.overflow = previousOverflow
      previous?.focus?.()
    }
  }, [open])

  if (!open) return null

  return createPortal(
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center p-4"
      role="presentation"
      style={{ background: 'rgba(15 23 42 / 0.34)', backdropFilter: 'blur(6px)', WebkitBackdropFilter: 'blur(6px)' }}
      onMouseDown={(event) => {
        // 只有按下就落在遮罩上才关，避免在输入框里拖选文字误触关闭
        if (closeOnBackdrop && event.target === event.currentTarget) onClose()
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className="w-full max-h-[85vh] flex flex-col rounded-2xl overflow-hidden outline-none"
        style={{
          maxWidth: width,
          background: 'rgba(var(--surface-rgb) / 0.98)',
          border: '1px solid rgba(var(--hairline-rgb) / 0.2)',
          boxShadow: '0 24px 64px rgba(var(--shadow-rgb) / 0.28)',
        }}
      >
        <header
          className="px-5 pt-4 pb-3 flex items-start justify-between gap-3 flex-shrink-0"
          style={{ borderBottom: '1px solid rgba(var(--hairline-rgb) / 0.14)' }}
        >
          <div className="min-w-0">
            <h2 id={titleId} className="text-[14px] font-600 truncate" style={{ color: 'var(--foreground)' }}>
              {title}
            </h2>
            {description && (
              <p className="text-[12px] mt-1 leading-relaxed" style={{ color: 'var(--color-mid)' }}>
                {description}
              </p>
            )}
          </div>
          <button
            type="button"
            aria-label="关闭"
            onClick={onClose}
            className="w-7 h-7 rounded-lg flex items-center justify-center text-[13px] flex-shrink-0"
            style={{ background: 'rgba(var(--hairline-rgb) / 0.10)', color: 'var(--color-mid)' }}
          >
            ✕
          </button>
        </header>

        <div className="px-5 py-4 overflow-y-auto">{children}</div>

        {footer && (
          <div
            className="px-5 py-3 flex items-center justify-end gap-2 flex-shrink-0"
            style={{ borderTop: '1px solid rgba(var(--hairline-rgb) / 0.14)' }}
          >
            {footer}
          </div>
        )}
      </div>
    </div>,
    document.body,
  )
}
