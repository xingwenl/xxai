import type { UIWindowBounds } from '../core'

export const WINDOW_EDGE_MARGIN = 8

export interface WindowRect {
  x: number
  y: number
  width: number
  height: number
}

export interface WindowLayoutContext {
  viewportWidth: number
  viewportHeight: number
  position: 'left' | 'right'
  bounds: Required<UIWindowBounds>
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), Math.max(min, max))
}

export function resolveWindowBounds(
  user: UIWindowBounds | undefined,
  viewportWidth: number,
  viewportHeight: number,
): Required<UIWindowBounds> {
  const availableWidth = Math.max(viewportWidth - WINDOW_EDGE_MARGIN * 2, 1)
  const availableHeight = Math.max(viewportHeight - WINDOW_EDGE_MARGIN * 2, 1)
  const minWidth = clamp(user?.minWidth ?? 320, 240, availableWidth)
  const minHeight = clamp(user?.minHeight ?? 480, 320, availableHeight)
  const maxWidth = clamp(user?.maxWidth ?? availableWidth, minWidth, availableWidth)
  const maxHeight = clamp(user?.maxHeight ?? availableHeight, minHeight, availableHeight)
  return {
    width: clamp(user?.width ?? 430, minWidth, maxWidth),
    height: clamp(user?.height ?? 680, minHeight, maxHeight),
    minWidth,
    minHeight,
    maxWidth,
    maxHeight,
  }
}

export function defaultWindowRect(context: WindowLayoutContext): WindowRect {
  const { bounds, viewportWidth, viewportHeight, position } = context
  return {
    x:
      position === 'left'
        ? WINDOW_EDGE_MARGIN
        : Math.max(
            WINDOW_EDGE_MARGIN,
            viewportWidth - bounds.width - WINDOW_EDGE_MARGIN,
          ),
    y: Math.max(WINDOW_EDGE_MARGIN, viewportHeight - bounds.height - WINDOW_EDGE_MARGIN),
    width: bounds.width,
    height: bounds.height,
  }
}

export function clampWindowRect(
  rect: WindowRect,
  context: WindowLayoutContext,
): WindowRect {
  const { viewportWidth, viewportHeight, bounds } = context
  const width = clamp(rect.width, bounds.minWidth, bounds.maxWidth)
  const height = clamp(rect.height, bounds.minHeight, bounds.maxHeight)
  return {
    width,
    height,
    x: clamp(rect.x, WINDOW_EDGE_MARGIN, viewportWidth - width - WINDOW_EDGE_MARGIN),
    y: clamp(rect.y, WINDOW_EDGE_MARGIN, viewportHeight - height - WINDOW_EDGE_MARGIN),
  }
}

export function dragWindowRect(
  rect: WindowRect,
  deltaX: number,
  deltaY: number,
  context: WindowLayoutContext,
): WindowRect {
  return clampWindowRect(
    { ...rect, x: rect.x + deltaX, y: rect.y + deltaY },
    context,
  )
}

export function resizeWindowRect(
  rect: WindowRect,
  deltaX: number,
  deltaY: number,
  context: WindowLayoutContext,
): WindowRect {
  const { viewportWidth, viewportHeight, bounds } = context
  // 锚定左上角：向右下扩展，同时受用户配置与视口右侧/底部边界约束。
  const maxWidth = Math.min(bounds.maxWidth, viewportWidth - rect.x - WINDOW_EDGE_MARGIN)
  const maxHeight = Math.min(
    bounds.maxHeight,
    viewportHeight - rect.y - WINDOW_EDGE_MARGIN,
  )
  return {
    ...rect,
    width: clamp(rect.width + deltaX, bounds.minWidth, maxWidth),
    height: clamp(rect.height + deltaY, bounds.minHeight, maxHeight),
  }
}
