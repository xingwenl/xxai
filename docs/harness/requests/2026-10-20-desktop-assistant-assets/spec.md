---
id: 2026-10-20-desktop-assistant-assets
tier: B
risk: medium
approval:
  required: true
  granted: true
  why: ["跨 apps/ 改动：apps/ai-sdk 公共 UI 组件 + apps/desktop 宿主", "宿主新增 /api/v1/* 同源转发接口（对外契约变化）", "附件上传涉及 embed token 经宿主转发的鉴权边界"]
---

## 目标与范围

一句话：让桌面宿主里的全局助手能正常上传附件——文件选择器能选 xlsx/docx/pptx/pdf/csv 等文档、上传不再被 CORS 拦、文件 MIME 缺失时不再被后端拒。

用户报告（原话）：「上传文件 选不了xlsx 文件，而且上传失败，为啥会到http://127.0.0.1:8000 / Fetch API cannot load http://127.0.0.1:8000/api/v1/embed/conversations?page=1&page_size=20 due to access control checks.」

三条独立根因（均已实测，见下节）：
1. **选不了文档**：ai-sdk 的 `accept` 混写 MIME 与扩展名，桌面端 pywebview 只把 MIME 映射成 macOS UTI，扩展名 token 全被丢弃 ⇒ 选择器实际只允许图片。
2. **为什么到 :8000**：宿主前端没传 `baseUrl`，ai-sdk 从 WS endpoint 推导出 `http://127.0.0.1:8000/api/v1`，渲染层直接跨域请求后端，而后端 CORS 不允许桌面来源。
3. **上传失败**：即使跨域放过，`file.type` 为空时以 `application/octet-stream` 上传，后端 MIME 白名单直接 400。

本批范围：`apps/ai-sdk` 的 accept 与 MIME 兜底；`apps/desktop` 宿主新增 `/api/v1/*` 同源转发 + 助手传 `baseUrl`。
非目标：不改后端 MIME 白名单与 25MiB 上限、不新增文件类型（.xls/.doc 仍不支持）、不改会话与知识库处理逻辑、不做附件预览新 UI、不改 WS 链路（WS 不受 CORS 约束，继续直连）。

## 来源与方案比较

实测证据（本机，2026-10-20）：
- pywebview `webview/platforms/cocoa.py:239-256`：`file_filter = param._acceptedMIMETypes()` 原样交给 `create_file_dialog`；`:979-989` 逐个 `UTType.typeWithMIMEType_(mime_str)`，`None` 或 `dyn.*` 直接丢弃。实测 `typeWithMIMEType_(".xlsx")` → `None`，`("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")` → `org.openxmlformats.spreadsheetml.sheet`。⇒ 当前 accept 里 `.txt/.md/.csv/.pdf/.docx/.xlsx/.pptx` 全部失效，只剩 4 个 `image/*`。
- CORS：`curl -X OPTIONS 'http://127.0.0.1:8000/api/v1/embed/conversations?...' -H 'Origin: http://127.0.0.1:8765'` → `400 Disallowed CORS origin`；后端 `cors_origins` 来自 `CORS_ORIGINS` 环境变量（`app/core/config.py:31,76,233`），根 `.env` 只有 `http://127.0.0.1:5390` 与 `http://localhost:8080`。
- 上传：同一张 token，正确 MIME 的 xlsx → `201`；`application/octet-stream` → `400 {"message":"不支持的文件类型: application/octet-stream"}`（`app/modules/asset_processing/services.py:41-46`）。
- SDK：`apps/ai-sdk/src/core/client.ts:159-168` 未传 `baseUrl` 时从 WS endpoint 推导；`apps/desktop/front/src/lib/assistant.ts:96-117` 确实没传。

方案比较（HTTP 传输）：

| 方案 | 做法 | 结论 |
|---|---|---|
| 宿主同源转发（采纳） | 渲染层 `baseUrl = ${location.origin}/api/v1`，宿主把 `/api/v1/*` 转发到 agent.json 里的 AI Base 地址 | 与后端 CORS 配置解耦；桌面端口可变也不影响；token 仍短期、secret 仍在宿主 |
| 扩后端 `CORS_ORIGINS`（否决） | 把 8765/8443 加进后端环境变量 | 要改后端 env 并重启；`DESKTOP_API_PORT` 可变；打包用户装完还要手改后端 |
| 渲染层直连 + 后端放宽 octet-stream（否决） | 后端 MIME 白名单接受 `application/octet-stream` | 削弱上传校验，任意文件都能进处理管线 |
| 给 pywebview 打补丁（否决） | monkeypatch `runOpenPanel` 或改 site-packages | 依赖私有 API，不能随仓库交付 |

方案比较（文件选择器）：

| 方案 | 做法 | 结论 |
|---|---|---|
| accept 只写 MIME（采纳） | 与后端 `ALLOWED_MIME_TYPES` 一一对应，客户端再按扩展名兜底 | WebKit 能映射为 UTI，Chrome/Firefox 同样认 |
| 保留扩展名写法（否决） | 现状 `.xlsx` 等 | 桌面端被 WebKit 丢弃，用户永远选不到文档 |

## 被否决的选项

- 仅扩后端 CORS：改动小，但把「桌面能不能用」变成后端环境配置问题，与桌面端口可配置冲突。
- 后端接受 octet-stream：等于放弃服务端类型校验，图片/文档处理链路会收到未知类型。
- patch pywebview：不可交付、升级即失效。
- 前端自行拦截并改写上传请求：SDK 内部固定拼 `${baseUrl}/embed/...`，宿主无法逐请求改写，只能换根路径（转发）。
- 让宿主直接读后端存储、绕过 HTTP：附件要走后端处理管线（切块、配额、审计），绕过即失去这些能力。

## 停点判断

B 档：跨 `apps/`、宿主新增 `/api/v1/*` 转发接口，`approval.required: true`。本文件写完后先确认方案要点，再写实现代码。

## 变更点

- `apps/ai-sdk/src/ui/components/ChatInput.vue`：`accept` 改为 MIME 列表（png/jpeg/gif/webp + text/plain、text/markdown、text/csv、pdf、docx、xlsx、pptx）；`addFile` 先规范化文件 MIME 再 emit。
- `apps/ai-sdk/src/core/upload-mime.ts`（新建）：`MIME_BY_EXTENSION` 表 + `resolveFileMimeType(file)`（`file.type` 为空时按扩展名推断，未知返回 `application/octet-stream`）。
- `apps/ai-sdk/src/core/__tests__/upload-mime.test.ts`（新建）：覆盖 xlsx/docx/pdf/csv/md/txt 推断、已有 `file.type` 不被覆盖、未知扩展名 fallback。
- `apps/desktop/desktop_app/server.py`：新增 `/api/v1/{path:path}` 的 GET/POST/PUT/PATCH/DELETE/HEAD 转发（目标 = agent.json 的 `baseUrl` + 原路径 + 查询串），透传 `Authorization`/`Content-Type`/`Accept` 与原始请求体，回传状态码与 content-type；未配置 remote 时返回 503 并给出中文原因；沿用现有 `_urlopen` 线程内调用。
- `apps/desktop/front/src/lib/assistant.ts`：remote 模式给 `createAgentClient` 传 `baseUrl: \`${window.location.origin}/api/v1\``；dev 模式不传（本地网关无 REST）。
- `apps/desktop/tests/test_agent_proxy.py`（新建）：桩转发目标验证方法/路径/查询串/Authorization/body/状态码透传、404 透传、未配置 503。
- `apps/desktop/README.md`：说明附件走宿主同源转发、需重启桌面应用。
- `docs/CHANGELOG.md`：2026-10-20 段首补修复条目。
- `tools/harness/verify/2026-10-20-desktop-assistant-assets.sh`（新建）：ai-sdk vitest、desktop pytest、front build、转发桩、未配置 503、构建产物 accept 断言。

## 验收标准

1. `apps/ai-sdk` 单测通过，新增 MIME 推断用例全绿。
2. `apps/desktop` pytest 通过（含 `/api/v1/*` 转发与 503 用例），不 regress 既有 189 例。
3. `apps/desktop/front` `tsc --noEmit` 与 `pnpm build` 通过。
4. 构建产物里的 `accept` 只含 MIME、不再含 `.xlsx` 之类扩展名 token。
5. verify 脚本全步骤实跑通过（真实模型/浏览器目视项显式列为未执行）。
6. 本机桌面上传 xlsx 成功（需要用户重启应用后目视确认，脚本无法覆盖）。
7. 无新增第三方依赖。
