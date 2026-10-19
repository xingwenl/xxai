import { defineConfig, type Plugin } from 'vite';
import vue from '@vitejs/plugin-vue';
import dts from 'vite-plugin-dts';
import { resolve } from 'path';
import replace from '@rollup/plugin-replace'; // 引入插件

/**
 * 本地 Demo 的同源 token 代理（仅 dev server 生效）。
 *
 * demo 页面只请求同源 `POST /demo-api/agent-token`，由 dev server 用开发者 shell 的
 * 环境变量向 AI Base 换取短期 token。这样 `client_secret` 既不进仓库、也不进浏览器，
 * 页面里不再出现任何 Embed Client 凭据。
 */
function demoTokenProxy(): Plugin {
  const agentApiBase = (
    process.env.AGENT_API_BASE || 'http://127.0.0.1:8000'
  ).replace(/\/+$/, '');
  const clientId = process.env.EMBED_CLIENT_ID || '';
  const clientSecret = process.env.EMBED_CLIENT_SECRET || '';
  const defaultAgentId = process.env.EMBED_AGENT_ID || '';
  const defaultOrigin = process.env.EMBED_ORIGIN || '';

  return {
    name: 'demo-token-proxy',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use('/demo-api/agent-token', async (req, res) => {
        const send = (status: number, body: unknown) => {
          res.statusCode = status;
          res.setHeader('Content-Type', 'application/json; charset=utf-8');
          res.end(JSON.stringify(body));
        };

        if (req.method !== 'POST') {
          send(405, { message: '只支持 POST' });
          return;
        }
        if (!clientId || !clientSecret) {
          send(400, {
            message:
              '缺少 EMBED_CLIENT_ID / EMBED_CLIENT_SECRET。启动 demo 前先设置环境变量，例如：EMBED_CLIENT_ID=xxx EMBED_CLIENT_SECRET=yyy EMBED_AGENT_ID=1 EMBED_ORIGIN=http://localhost:5174 npm run demo',
          });
          return;
        }

        const chunks: Buffer[] = [];
        for await (const chunk of req) {
          chunks.push(chunk as Buffer);
        }
        let payload: Record<string, unknown> = {};
        if (chunks.length) {
          try {
            payload = JSON.parse(Buffer.concat(chunks).toString('utf8'));
          } catch {
            send(400, { message: '请求体不是合法 JSON' });
            return;
          }
        }

        const agentId = Number(payload.agent_id ?? defaultAgentId);
        if (!Number.isInteger(agentId) || agentId <= 0) {
          send(400, { message: '缺少可用的 agent_id（页面入参或 EMBED_AGENT_ID）' });
          return;
        }

        // agent_id / origin 由服务端配置决定，浏览器只能指定要模拟的终端用户
        const origin =
          String(payload.origin || defaultOrigin || req.headers.origin || '');
        try {
          const upstream = await fetch(`${agentApiBase}/api/v1/embed/tokens`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              client_id: clientId,
              client_secret: clientSecret,
              agent_id: agentId,
              external_user_id: String(payload.external_user_id ?? 'demo-user'),
              origin,
            }),
          });
          const text = await upstream.text();
          res.statusCode = upstream.status;
          res.setHeader('Content-Type', 'application/json; charset=utf-8');
          res.end(text);
        } catch (error) {
          send(502, {
            message: `无法连接 AI Base（${agentApiBase}）：${(error as Error).message}`,
          });
        }
      });
    },
  };
}

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
    demoTokenProxy(),
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
