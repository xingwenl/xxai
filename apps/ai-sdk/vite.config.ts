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
    }),
    replace({
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
      fileName: (format) => `xxai-agent.${format}.js`,
    },
    rollupOptions: {
      // 不把 Vue external 化，直接打包进 SDK
      external: [],
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
