import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import dts from 'vite-plugin-dts';
import { resolve } from 'path';
import replace from '@rollup/plugin-replace'; // 引入插件

export default defineConfig({
  plugins: [
    vue(),
    dts({
      insertTypesEntry: true,
      outDir: 'dist',
      include: ['src/**/*.ts', 'src/**/*.vue'],
      exclude: ['src/**/*.test.ts', 'src/test/**'],
    }),
    replace({
      preventAssignment: true,
      'process.env.NODE_ENV': JSON.stringify(
        process.env.NODE_ENV || 'production',
      ),
    }),
  ],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },

  build: {
    lib: {
      entry: resolve(__dirname, 'src/index.ts'),
      name: 'XXAIAgent',
      fileName: (format) =>
        format === 'umd' ? 'xxai-agent.umd.cjs' : 'xxai-agent.es.js',
    },
    rollupOptions: {
      // 不把 Vue external 化，直接打包进 SDK
      // mermaid / echarts 保持外置：SDK 通过运行时动态解析加载图表引擎，
      // 一旦被内联会让产物从约 1M 涨到约 4M，也不利于宿主固定引擎版本
      external: ['mermaid', 'echarts'],
      output: {
        globals: {},
        exports: 'named',
      },
    },
  },
  server: {
    proxy: {
      '/api': {
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
        // mock代理目标地址
        target: 'http://localhost:8000/api',
        ws: true,
      },
    },
  },
});
