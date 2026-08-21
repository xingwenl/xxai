// React 子应用注册表：本项目原生应用（manifest.type === "react"）由宿主 React 组件渲染，
// 三方 zip 应用保持 iframe 形态（manifest.type === "iframe"）

import type { ComponentType } from 'react'
import BookmarksPage from '../components/bookmarks-page'

export interface ThemeLike {
  primary: string
  gradient: [string, string]
  mid: string
  faint: string
}

export interface ReactAppProps {
  theme: ThemeLike
}

export const REACT_APPS: Record<string, ComponentType<ReactAppProps>> = {
  'bookmarks-organizer': BookmarksPage,
}
