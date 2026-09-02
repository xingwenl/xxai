import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发环境代理：/hua8-api -> 店铺运营平台（hua8），/api -> ai-base（含 WebSocket）。
// 生产环境由部署层（Nginx 等）做同样的反向代理，避免浏览器跨域与混合内容问题。
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5174,
    proxy: {
      '/hua8-api': {
        target: 'http://hua8.bbtree.xyz',
        changeOrigin: true,
        secure: false,
      },
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        secure: false,
        ws: true,
      },
    },
  },
})
