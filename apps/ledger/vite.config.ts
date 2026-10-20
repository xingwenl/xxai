import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 记账子应用：纯静态页面，由桌面宿主以 iframe 方式加载（file/静态目录皆可），
// 因此 base 用相对路径，避免资源 404。
export default defineConfig({
  base: './',
  plugins: [react()],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  server: {
    port: 5181,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: true,
        ws: true,
      },
    },
  },
})
