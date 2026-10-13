// 轻量 toast：与启动器视觉一致的毛玻璃通知，宿主与 SDK 共用

type ToastType = 'info' | 'success' | 'error'

export function toast(title: string, body = '', type: ToastType = 'info'): void {
  let container = document.getElementById('desktop-toasts')
  if (!container) {
    container = document.createElement('div')
    container.id = 'desktop-toasts'
    Object.assign(container.style, {
      position: 'fixed',
      top: '16px',
      right: '16px',
      zIndex: '9999',
      display: 'flex',
      flexDirection: 'column',
      gap: '8px',
      width: '320px',
      pointerEvents: 'none',
    })
    document.body.appendChild(container)
  }

  const item = document.createElement('div')
  const accent = type === 'error' ? '#f43f5e' : type === 'success' ? '#059669' : '#06b6d4'
  Object.assign(item.style, {
    pointerEvents: 'auto',
    borderRadius: '16px',
    padding: '12px 16px',
    background: 'rgba(var(--surface-rgb) / 0.94)',
    backdropFilter: 'blur(20px) saturate(120%)',
    WebkitBackdropFilter: 'blur(20px) saturate(120%)',
    border: `1px solid ${accent}40`,
    boxShadow: '0 8px 28px rgba(0,0,0,0.10)',
    borderLeft: `3px solid ${accent}`,
    fontFamily: "'Outfit', -apple-system, sans-serif",
    animation: 'desktopToastIn 0.18s ease',
  })

  const titleEl = document.createElement('div')
  titleEl.textContent = title
  Object.assign(titleEl.style, { fontSize: '13px', fontWeight: 600, color: 'var(--foreground, #0d1f26)' })

  const bodyEl = document.createElement('div')
  bodyEl.textContent = body
  Object.assign(bodyEl.style, { fontSize: '12px', marginTop: '2px', color: 'var(--color-mid, #5b8fa0)' })

  item.append(titleEl, bodyEl)
  container.appendChild(item)
  setTimeout(() => item.remove(), 3800)
}
