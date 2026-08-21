import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

// Desktop 宿主前端：构建产物 front/dist 由内嵌 FastAPI 托管
// 开发模式下 Vite dev server 代理 API / 插件静态 / 共享样式到本地 FastAPI
const devApiTarget = `http://127.0.0.1:${process.env.DESKTOP_API_PORT || '8765'}`

export default defineConfig({
  base: '/',
  // 共享品牌资源目录（apps/desktop/assets）：/icon.png 在开发与构建后均可直接引用
  publicDir: path.resolve(__dirname, '../assets'),
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 8443,
    proxy: {
      '/api': devApiTarget,
      '/apps': devApiTarget,
      '/css': devApiTarget,
    },
  },
  preview: {
    host: '0.0.0.0',
    port: 8443,
  },
})
