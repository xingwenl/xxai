// 全局助手：宿主壳层单例挂载 ai-sdk 悬浮窗，并把子应用注册的方法同步成宿主工具。
//
// 为什么是单例：floating 面板会挂到 document.body，重复 createAgentClient 会叠加多个
// 悬浮球；而且 destroy() 不会卸载内部 Vue 应用（会泄漏）。宿主壳层只创建一次，
// 工具集合随子应用的 desktop.tools.register/unregister 动态增减。

import {
  configureMarkdownDiagrams,
  createAgentClient,
  type AgentClient,
  type ToolDefinition,
} from 'xxai-agent';
import 'xxai-agent/style.css';
import { getAgentConfig, issueAgentToken, type AgentConfig } from './api';
import {
  listBridgeTools,
  subscribeBridgeTools,
  toAgentTool,
} from './tool-bridge';

// SDK 的图表引擎解析顺序是「显式注入 → globalThis → 运行时 import(变量说明符)」。
// 第三档在浏览器里必然失败：SDK 产物把说明符放在变量里（构建期 @vite-ignore），
// 浏览器无法解析裸模块名，只会抛 TypeError: Failed to resolve module specifier 'echarts'，
// 被 SDK 的 catch 吞掉后围栏降级成代码块——这就是「装了 echarts 却显示不出来」的原因。
// 宿主用字面量动态 import 让 Vite 切出独立 chunk，再显式注入：引擎按需加载，不进首屏主包。
let diagramEnginesReady: Promise<void> | null = null;

function loadDiagramEngines(): Promise<void> {
  diagramEnginesReady ??= Promise.all([import('mermaid'), import('echarts')])
    .then(([mermaid, echarts]) => {
      configureMarkdownDiagrams({
        mermaid: mermaid.default ?? mermaid,
        echarts,
      });
    })
    .catch((err) => {
      // 加载失败保持 SDK 默认降级（显示源码），不能影响助手挂载
      console.warn('[assistant] 图表引擎加载失败，图表将降级为代码块', err);
    });
  return diagramEnginesReady;
}

let client: AgentClient | null = null;
let unsubscribeBridge: (() => void) | null = null;
let mounting: Promise<void> | null = null;

/** 相对 endpoint 还原成当前页面的绝对 ws 地址（SDK 要求 WebSocket 协议地址）。 */
function resolveEndpoint(endpoint: string): string {
  if (/^wss?:\/\//i.test(endpoint)) return endpoint;
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const path = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
  return `${scheme}://${window.location.host}${path}`;
}

/** 把当前方法集合同步给助手：注销已消失的，再注册现存全部（覆盖 schema 变更）。 */
function syncTools(agent: AgentClient): void {
  const tools = listBridgeTools();
  const names = new Set(tools.map((tool) => tool.name));
  for (const existing of agent.getToolNames()) {
    if (!names.has(existing)) agent.unregisterTool(existing);
  }
  if (tools.length) {
    agent.registerTools(
      tools.map((tool) => toAgentTool(tool) as ToolDefinition),
    );
  }
}

/** 挂载全局助手；未配置智能体后端时静默跳过。重复调用安全。 */
export function mountAssistant(): Promise<void> {
  if (client) return Promise.resolve();
  if (mounting) return mounting;
  mounting = (async () => {
    let config: AgentConfig;
    try {
      config = await getAgentConfig();
    } catch (err) {
      console.warn('[assistant] 读取智能体配置失败', err);
      return;
    }
    if (!config.enabled) {
      console.info(
        '[assistant] 未配置智能体后端，跳过挂载：',
        config.reason ?? '',
      );
      return;
    }
    // 助手确认启用后再拉引擎 chunk，与换 token / 建连并行：避免首条带图消息在引擎就绪前
    // 渲染成代码块（SDK 的降级结果不会自动重试），也避免未启用助手的宿主白下载重引擎。
    const diagramEngines = loadDiagramEngines();
    // remote 模式：先换一张短期 token 拿到真实 WS 地址与平台标识；后续 SDK 刷新 token 也走宿主，
    // 这样 client_secret 只存在于宿主进程，渲染层拿到的永远是短期凭证。
    let endpoint = config.endpoint;
    let platformId = config.platformId;
    let agentId = config.agentId;
    let displayName = config.displayName || '桌面用户';
    let getToken: () => Promise<string>;
    // remote 模式的 HTTP 调用（附件上传、会话列表等）必须走宿主同源转发：
    // 渲染层直连 AI Base 会被后端 CORS 拒绝，也拿不到正确的 baseUrl。
    let baseUrl: string | undefined;
    if (config.mode === 'remote') {
      try {
        const initial = await issueAgentToken(window.location.origin);
        endpoint = initial.endpoint;
        platformId = initial.platformId;
        agentId = String(initial.agentId);
        displayName = initial.displayName || displayName;
        baseUrl = `${window.location.origin}/api/v1`;
      } catch (err) {
        console.warn(
          '[assistant] 换发 AI Base token 失败，请检查设置页的智能体后端配置',
          err,
        );
        return;
      }
      getToken = async () =>
        (await issueAgentToken(window.location.origin)).token;
    } else {
      if (!endpoint || !agentId || !platformId) {
        console.info('[assistant] 本地网关参数不完整，跳过挂载');
        return;
      }
      const devToken = config.token || '';
      getToken = async () => devToken;
    }
    // 等引擎注入完成再创建客户端，保证首条消息里的 mermaid / echarts 围栏能直接出图
    await diagramEngines;
    const agent: AgentClient = createAgentClient({
      endpoint: resolveEndpoint(String(endpoint)),
      ...(baseUrl ? { baseUrl } : {}),
      platformId: String(platformId),
      agentId: String(agentId),
      getToken,
      user: { id: 'desktop-user', displayName },
      ui: {
        mode: 'floating',
        position: 'right',
        theme: 'auto',
        layout: 'desktop',
        showAgentSteps: true,
      },
      thinking: true,
      systemPrompt: `你是我的桌面应用助手, 你有图表渲染能力，需要图形时优先输出代码块，不要用 ASCII 字符画。
- 流程图/时序图/状态图/类图/甘特图：用 \`\`\`mermaid 代码块
- 柱状图/折线图/饼图/散点图等数据图表：用 \`\`\`echarts 代码块

echarts 代码块内必须是**纯 JSON 对象**（可含 series/xAxis/yAxis/title/legend/tooltip），
不允许出现 JS 变量、函数、注释以外的任何表达式，例如：

\`\`\`echarts
{ "title": { "text": "月度销量" },
  "xAxis": { "type": "category", "data": ["1月","2月","3月"] },
  "yAxis": { "type": "value" },
  "series": [{ "type": "bar", "data": [120, 200, 150] }] }
\`\`\`

不要输出 <script>、不要用 html 画图，不要输出图片链接。`,
      pageTools: {
        enabled: true,
        confirmationKeywords: ['提交', '删除', '支付'],
        maxCalls: 500000,
        maxDurationMs: 600_000,
      },
    });
    client = agent;
    // 先同步已有方法，再订阅后续变化：子应用打开顺序不影响助手能看到的工具集合
    syncTools(agent);
    unsubscribeBridge = subscribeBridgeTools(() => syncTools(agent));
    agent.on('error', (err) => console.warn('[assistant] 连接错误', err));
    try {
      await agent.connect();
    } catch (err) {
      console.warn(
        '[assistant] 连接失败（本地网关请检查 DESKTOP_DEV_AGENT，AI Base 请检查配置与网络）',
        err,
      );
    }
  })();
  return mounting;
}

/** 取消方法集合订阅（宿主壳层卸载时调用；当前壳层常驻，一般不触发）。 */
export function detachAssistantBridge(): void {
  unsubscribeBridge?.();
  unsubscribeBridge = null;
}
