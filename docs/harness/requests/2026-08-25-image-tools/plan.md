# 图片生成与读取工具实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在后端提供持久化的图片生成/读取内置工具，并让 AI SDK 安全展示和恢复缓存图片。

**Architecture:** 复用现有 `builtin_tool` 注册、执行循环和 `ConversationAsset` 存储。图片工具返回资产描述，运行时把资产描述转换为 `image` 内容块；SDK 通过 AgentClient 的 token 获取受保护资源并创建 Blob URL。

**Tech Stack:** FastAPI、SQLAlchemy async、OpenAI Python SDK、LangChain tool calling、Vue 3、TypeScript、Vitest、Pytest。

---

### Task 1: 后端配置和工具契约

**Files:**
- Modify: `apps/backend/app/core/config.py`
- Modify: `apps/backend/app/modules/builtin_tool/registry.py`
- Modify: `apps/backend/app/modules/builtin_tool/services.py`
- Test: `apps/backend/tests/builtin_tool/test_image_tools.py`

- [ ] 增加 OpenAI 图片配置字段和默认值，保持密钥不进入日志。
- [ ] 在 registry 中注册 `image_generate`、`image_read`，为参数定义 JSON Schema 和描述。
- [ ] 先写工具可发现、参数校验和未配置错误测试，再实现最小执行分支。

### Task 2: 图片生成服务与 asset 持久化

**Files:**
- Create: `apps/backend/app/modules/builtin_tool/image_generate.py`
- Modify: `apps/backend/app/modules/builtin_tool/services.py`
- Test: `apps/backend/tests/builtin_tool/test_image_tools.py`

- [ ] 用可注入的异步 OpenAI 客户端调用 `images.generate`，请求 `b64_json`。
- [ ] 将 base64 解码到受控临时目录，校验图片媒体类型和字节上限后调用 `persist_asset`。
- [ ] 对数量、尺寸、模型、质量做白名单/范围校验；对 SDK 异常统一映射稳定错误码。
- [ ] 用 fake client 覆盖成功、未配置、响应无图片、超限和上游失败。

### Task 3: 图片读取服务与权限边界

**Files:**
- Create: `apps/backend/app/modules/builtin_tool/image_read.py`
- Modify: `apps/backend/app/modules/builtin_tool/services.py`
- Test: `apps/backend/tests/builtin_tool/test_image_tools.py`

- [ ] URL 输入复用 `fetch_http_get` 的公开目标校验和限制，仅接受图片结果。
- [ ] asset_id 输入通过 `AssetRepository` 按当前 platform/agent/conversation/principal 查询，拒绝越权和非图片资源。
- [ ] 将读取内容持久化或复用已有资产，返回统一资产描述，并清理失败时的临时文件。

### Task 4: 运行时图片内容块

**Files:**
- Modify: `apps/backend/app/modules/conversation/runtime.py`
- Modify: `apps/backend/app/modules/conversation/services.py`
- Modify: `apps/backend/app/modules/gateway/runtime.py`
- Modify: `apps/backend/app/modules/gateway/router.py`
- Test: `apps/backend/tests/conversation/test_runtime.py`
- Test: `apps/backend/tests/builtin_tool/test_runtime_integration.py`

- [ ] 在 `GraphResult` 增加图片资产列表/内容块字段，工具循环从 builtin outcome 提取图片资产。
- [ ] 统一 REST、SSE、WebSocket 收尾逻辑，保存和发送 Markdown + image 内容块。
- [ ] 保留既有工具事件、文本响应和循环状态行为。
- [ ] 增加多图、无图和失败结果测试。

### Task 5: AI SDK 受保护图片加载

**Files:**
- Modify: `apps/ai-sdk/src/core/types.ts`
- Modify: `apps/ai-sdk/src/core/client.ts`
- Modify: `apps/ai-sdk/src/ui/components/ImageContent.vue`
- Modify: `apps/ai-sdk/src/ui/components/MessageContent.vue`
- Modify: `apps/ai-sdk/src/ui/components/ChatMessage.vue`
- Test: `apps/ai-sdk/src/ui/__tests__/message-presentation.test.ts`
- Test: `apps/ai-sdk/src/core/__tests__/client.test.ts`

- [ ] 在 AgentClient 提供受控图片 fetch 方法，使用现有 `getToken` 并支持 token 刷新后的再次调用。
- [ ] ImageContent 对 assetId 使用 Blob URL，组件卸载或地址变化时 revoke；对公开 URL 保持直连。
- [ ] 增加加载中、失败 fallback、非图片响应和缓存消息重载场景测试。

### Task 6: 配置示例、静态检查和回归验证

**Files:**
- Modify: `.env.example`
- Modify: `apps/backend/pyproject.toml`
- Modify: `apps/ai-sdk/src/ui/styles/index.css`（仅在需要补充加载态样式时）
- Modify: `docs/harness/requests/2026-08-25-image-tools/verify.md`

- [ ] 将 `openai` 作为后端直接依赖声明，避免依赖传递安装。
- [ ] 更新环境变量示例和中文使用说明。
- [ ] 执行后端目标测试、SDK 测试、ruff、black、type-check 和 build。
- [ ] 记录真实命令、结果、失败项和例外，不以摘要代替证据。

### 回滚方案

回滚本次代码和配置改动即可；不涉及数据库迁移。若已产生图片文件，可按现有 asset 清理任务删除，不影响历史文本消息。

### 人工确认点

- 已确认：使用 OpenAI Images API。
- 已确认：使用 `b64_json` 并持久化 assetId，而不是依赖临时 URL。
- 已确认：AI SDK 通过带 token 的请求展示受保护资源。
