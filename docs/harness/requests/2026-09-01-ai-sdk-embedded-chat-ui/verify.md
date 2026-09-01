# 验证记录

## 执行命令

- `cd apps/ai-sdk && npm run type-check`
- `cd apps/ai-sdk && npm run test -- --run`
- `cd apps/ai-sdk && npm run build && npm run verify-package`
- 浏览器验证：本地 `python3 -m http.server 8765 --directory apps/ai-sdk`，用浏览器自动化打开 `http://127.0.0.1:8765/demo/embedded.html`，读取布局与交互结果（首次尝试 headless Chrome CLI 因 dump 时机不稳定放弃，改用浏览器自动化工具验证，结果一致且更稳定）

## 预期结果

- type-check：0 类型错误
- 单测：全部用例通过（floating 布局纯函数不受影响）
- build + verify-package：构建成功，包入口文件与 CSS 均存在
- 浏览器验证（demo/embedded.html）：
  - embedded 实例默认展开并填满容器（宽高与容器一致）
  - 容器内无悬浮按钮、无拖拽/缩放手柄、头部无返回/关闭按钮
  - floating 对比实例保持悬浮按钮、窗口默认关闭
  - 切换容器高度后聊天窗口跟随变化
  - 切换主题后重建实例，dark 生效

## 实际结果

- type-check：通过（vue-tsc 无报错）
- 单测：15 个测试文件、97 个用例全部通过（含 1 个 WebSocket 关闭的预期 stderr 日志，非失败）
- build + verify-package：`dist/xxai-agent.es.js`、`dist/xxai-agent.umd.cjs`、`dist/index.d.ts`、`dist/style.css` 全部校验通过
- 浏览器验证：
  - embedded 窗口 class 为 `xxai-chat-window xxai-chat-window--embedded`，尺寸 834×600（容器 836×602 含 1px 边框），填满容器
  - `embeddedHasFloatButton=false`、`embeddedHasResizeHandle=false`、`embeddedHasBackBtn=false`、`embeddedHasCloseBtn=false`
  - `floatingButtonFound=true`，floating 窗口默认关闭
  - 容器切到 720px 后窗口高度 720px，跟随容器尺寸
  - 切 dark 后窗口 class 为 `xxai-chat-window dark xxai-chat-window--embedded`，dark 生效

## 失败项与例外

- 无（headless Chrome CLI 的 `--dump-dom` 输出时机不稳定属环境现象，已改用浏览器自动化工具完成同等验证）
