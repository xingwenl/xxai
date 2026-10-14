import path from 'path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react-swc'
import tailwindcss from '@tailwindcss/vite'
import { tanstackRouter } from '@tanstack/router-plugin/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    tanstackRouter({
      target: 'react',
      autoCodeSplitting: true,
    }),
    react(),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 8080,
    proxy: {
      '/api': {
        changeOrigin: true,
        // 保留 /api/v1 前缀，直接转发到 FastAPI 根地址。
        // 允许用 VITE_PROXY_TARGET 覆盖，便于本地联调脚本把前端接到临时后端实例。
        target: process.env.VITE_PROXY_TARGET ?? 'http://localhost:8000',
        ws: true,
      },
    },
  },
})
