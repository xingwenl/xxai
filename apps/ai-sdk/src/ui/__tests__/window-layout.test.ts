import { describe, expect, it } from 'vitest'
import type { UIWindowBounds } from '../../core'
import {
  WINDOW_EDGE_MARGIN,
  clampWindowRect,
  defaultWindowRect,
  dragWindowRect,
  resizeWindowRect,
  resolveWindowBounds,
  type WindowLayoutContext,
} from '../window-layout'

const viewport = { viewportWidth: 1280, viewportHeight: 800 }

function context(overrides: Partial<WindowLayoutContext> = {}): WindowLayoutContext {
  return {
    ...viewport,
    position: 'right',
    bounds: resolveWindowBounds(undefined, viewport.viewportWidth, viewport.viewportHeight),
    ...overrides,
  }
}

describe('window layout', () => {
  it('resolves defaults with min and viewport caps', () => {
    const bounds = resolveWindowBounds(undefined, 1280, 800)

    expect(bounds).toEqual({
      width: 430,
      height: 680,
      minWidth: 320,
      minHeight: 480,
      maxWidth: 1280 - WINDOW_EDGE_MARGIN * 2,
      maxHeight: 800 - WINDOW_EDGE_MARGIN * 2,
    })
  })

  it('clamps user bounds to min/max and viewport', () => {
    const bounds = resolveWindowBounds(
      {
        width: 200,
        height: 900,
        minWidth: 400,
        minHeight: 300,
        maxWidth: 600,
        maxHeight: 700,
      },
      1280,
      800,
    )

    expect(bounds.width).toBe(400)
    expect(bounds.height).toBe(700)
    expect(bounds.minWidth).toBe(400)
    expect(bounds.minHeight).toBe(320)
    expect(bounds.maxWidth).toBe(600)
    expect(bounds.maxHeight).toBe(700)
  })

  it('places window at right-bottom by default', () => {
    const rect = defaultWindowRect(context())

    expect(rect).toEqual({
      x: 1280 - 430 - WINDOW_EDGE_MARGIN,
      y: 800 - 680 - WINDOW_EDGE_MARGIN,
      width: 430,
      height: 680,
    })
  })

  it('places window at left-bottom when positioned left', () => {
    const rect = defaultWindowRect(context({ position: 'left' }))

    expect(rect.x).toBe(WINDOW_EDGE_MARGIN)
  })

  it('clamps dragged position inside the viewport', () => {
    const start = defaultWindowRect(context())
    const dragged = dragWindowRect(
      start,
      -100000,
      -100000,
      context(),
    )

    expect(dragged.x).toBe(WINDOW_EDGE_MARGIN)
    expect(dragged.y).toBe(WINDOW_EDGE_MARGIN)
  })

  it('clamps dragged position so window stays fully visible', () => {
    const start = defaultWindowRect(context())
    const dragged = dragWindowRect(start, 100000, 100000, context())

    expect(dragged.x).toBe(1280 - start.width - WINDOW_EDGE_MARGIN)
    expect(dragged.y).toBe(800 - start.height - WINDOW_EDGE_MARGIN)
  })

  it('resizes within min and max bounds anchored at top-left', () => {
    const moved = dragWindowRect(
      defaultWindowRect(context()),
      -100000,
      -100000,
      context(),
    )
    const resized = resizeWindowRect(moved, 1000, 1000, context())

    expect(resized.x).toBe(WINDOW_EDGE_MARGIN)
    expect(resized.y).toBe(WINDOW_EDGE_MARGIN)
    expect(resized.width).toBe(1280 - WINDOW_EDGE_MARGIN * 2)
    expect(resized.height).toBe(800 - WINDOW_EDGE_MARGIN * 2)
  })

  it('resizes down to the configured minimum', () => {
    const start = defaultWindowRect(context())
    const resized = resizeWindowRect(start, -100000, -100000, context())

    expect(resized.width).toBe(320)
    expect(resized.height).toBe(480)
  })

  it('clamps a rect with oversized width or height', () => {
    const rect = clampWindowRect(
      { x: -50, y: -50, width: 5000, height: 5000 },
      context(),
    )

    expect(rect.x).toBe(WINDOW_EDGE_MARGIN)
    expect(rect.y).toBe(WINDOW_EDGE_MARGIN)
    expect(rect.width).toBe(1280 - WINDOW_EDGE_MARGIN * 2)
    expect(rect.height).toBe(800 - WINDOW_EDGE_MARGIN * 2)
  })

  it('keeps default size within small viewports', () => {
    const bounds = resolveWindowBounds(undefined, 320, 480)
    expect(bounds.width).toBeLessThanOrEqual(320)
    expect(bounds.height).toBeLessThanOrEqual(480)
  })

  // 回归：双栏断点曾把「面板宽度」写回 viewportWidth，导致缩放自反馈。
  // 窗口尺寸必须由真实视口决定；面板宽度只影响双栏断点，不参与此处计算。
  it('derives resize bounds from the viewport, not from the window width', () => {
    const viewportBounds = resolveWindowBounds(undefined, 1400, 900)
    // 视口 1400 时最小宽度是默认 320，最大不超过视口减留白。
    expect(viewportBounds.minWidth).toBe(320)
    expect(viewportBounds.maxWidth).toBe(1400 - WINDOW_EDGE_MARGIN * 2)

    // 真实视口下缩小到极限只能到 320，不能掉到 240：
    // minWidth 只有在视口本身小于 320+留白时才会被 clamp 降低。
    const shrunk = resizeWindowRect(
      defaultWindowRect(context()),
      -100000,
      -100000,
      context(),
    )
    expect(shrunk.width).toBe(320)

    // 视口越小，minWidth 会被 availableWidth 逐步压低（clamp 的下限才是 240）：
    // 这正是「视口」与「面板宽度」语义不同的证据，不能共用一个字段。
    const tinyViewport = resolveWindowBounds(undefined, 300, 640)
    expect(tinyViewport.minWidth).toBe(300 - WINDOW_EDGE_MARGIN * 2)
    expect(tinyViewport.minWidth).toBeLessThan(viewportBounds.minWidth)
  })

  it('keeps the floating default width when the viewport is wide', () => {
    // 430px 悬浮窗停在 1400px 视口上时，尺寸必须保持配置值。
    const rect = defaultWindowRect(
      {
        viewportWidth: 1400,
        viewportHeight: 900,
        position: 'right',
        bounds: resolveWindowBounds(undefined, 1400, 900),
      },
    )
    expect(rect.width).toBe(430)
  })
})
