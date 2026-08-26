# 验证记录

## 2026-08-26 Word/Excel 解析依赖补齐

新增 `docx2txt`、`openpyxl` 运行时依赖，`SimpleDirectoryReader` 对 PDF/DOCX/XLSX 统一解析并抽取文本；新增真实样例测试覆盖三种格式与 Excel 多 sheet 场景。

| 项目 | 命令 | 结果 |
| --- | --- | --- |
| 新增解析测试 | `cd apps/backend && poetry run pytest tests/asset/test_load_file_text.py -q` | 通过，6/6 |
| 附件模块测试 | `cd apps/backend && poetry run pytest tests/asset -q` | 通过，29/29 |
| 同 Phase 1 范围全量 | `cd apps/backend && poetry run pytest tests/asset tests/gateway tests/conversation -q` | 通过，138 个通过、1 个条件跳过 |
| 静态检查 | `cd apps/backend && poetry run ruff check app tests` | 通过 |
| 差异格式检查 | `git diff --check` | 通过 |

验证说明：

- 样例文件为真实二进制格式：PDF 为 xref 偏移准确的单页文档，DOCX 为最小合法 Office Open XML 包，XLSX 由 openpyxl 生成；测试断言能抽取到具体文本内容。
- 确认 Excel 多 sheet 行为：`load_file_text` 将每个 sheet 的解析结果按空行拼接；仅含表头、无数据行的 sheet 不产生文本（`PandasExcelReader` 的既有行为）。
- 已知限制：PPTX 虽在允许 MIME 白名单内，但运行环境尚未安装 `python-pptx`，演示文稿解析留待后续；`xlrd` 缺失时旧版 `.xls` 也不在解析范围。

## 2026-08-26 Phase 1 全量验证与提交前修复

本次为 Phase 1 提交前的完整验证，实际执行命令与结果如下：

| 项目 | 命令 | 结果 |
| --- | --- | --- |
| 后端附件/网关/会话测试 | `poetry run pytest tests/asset tests/gateway tests/conversation -q` | 通过，132 个通过、1 个条件跳过 |
| 后端静态检查 | `poetry run ruff check app tests` | 通过，修复后 0 错误 |
| SDK 全量测试 | `pnpm --dir apps/ai-sdk test -- --run` | 通过，15 个测试文件、96/96 |
| SDK 类型检查 | `pnpm --dir apps/ai-sdk type-check` | 通过 |
| SDK 生产构建 | `pnpm --dir apps/ai-sdk build` | 通过，生成 ESM、UMD、CSS 和声明文件 |
| Alembic 迁移 | `poetry run alembic current` / `alembic upgrade head` | 数据库已处于 `20260825_0025 (head)`，迁移链完整、脚本 `py_compile` 通过 |
| 路由注册启动检查 | TestClient 读取 OpenAPI schema | `/api/v1/agents/{agent_id}/chat` 与 6 条 embed 路由正常注册，无重复路径 |
| 差异格式检查 | `git diff --check` | 通过 |

### 提交前修复的两个 bug

1. **F811 路由遮蔽（后端）**：`app/__init__.py` 中 `from app.modules.asset.conversation_asset_router import conversation_router` 遮蔽了 conversation 模块同名路由，导致原 `/agents` 聊天 REST 路由未注册、asset 路由被注册两次。已改用 `asset_conversation_router` / `asset_upload_router` 别名，启动级 OpenAPI 检查确认 `/api/v1/agents/{agent_id}/chat` 恢复注册且无重复路径。
2. **SDK baseUrl 双前缀**：`_httpBaseUrl` 在显式 `baseUrl` 后再次追加 `/api/v1`，导致上传地址变成 `.../api/v1/api/v1/embed/assets`（`client.test.ts` 2 个用例失败）。已改为直接使用完整根路径，并移除 `loadAsset` 中的调试输出；修复后 SDK 96/96 通过。

### 已知限制

- 数据库已存在真实附件处理数据（24 条 processing、14 条 chunks），未执行破坏性的 downgrade/upgrade 往返验证；迁移此前已真实执行成功且处于 head。
- 仍未执行真实供应商视觉模型联调；该事项属于 Phase 2/验收范围。

## 2026-08-26 已发送图片即时展示 bugfix

- SDK 用户消息保留本地 Blob 预览地址，WebSocket 附件 payload 仍只包含 `assetId`、文件名、MIME 和大小。
- 本地预览加载失败时，图片组件回退到受保护资源下载。
- `pnpm --dir apps/ai-sdk test -- --run`：通过，15 个测试文件、96/96。
- `pnpm --dir apps/ai-sdk type-check`：通过。
- `pnpm --dir apps/ai-sdk build`：通过。

## 2026-08-26 当前会话上传与非视觉模型降级 bugfix

- 新增 SDK 回归测试，确认已有 `conversationId=232` 时上传请求使用 `/embed/conversations/232/assets`，首次无会话时继续使用 `/embed/assets`。
- 新增后端回归测试，模拟上游返回 `messages.content.type 参数非法，取值范围 ['text']`，确认运行时自动以纯文字消息重试并完成回答。
- 聚焦测试：SDK `client.test.ts` 25/25 通过；后端 `test_runtime.py` 42/42 通过；相关 Ruff 检查通过。

完整验证结果见本节后续补充。

## 2026-08-26 图片展示与视觉模型输入 bugfix

SDK 新增回归测试，确认发送带图片附件时，本地用户消息包含可由 Embed token 加载的相对资源引用。后端新增回归测试，确认图片以 `text + image_url(data URL)` 的多模态内容传入模型；网关同时保存不含 Base64 的图片引用内容块。

聚焦验证：

- `pnpm --dir apps/ai-sdk test -- --run src/core/__tests__/client.test.ts`：通过，24/24。
- `pnpm --dir apps/ai-sdk type-check`：通过。
- `cd apps/backend && poetry run pytest tests/conversation/test_runtime.py tests/gateway/test_chat_flow.py -q`：通过，47/47。
- `cd apps/backend && poetry run ruff check app/modules/gateway/runtime.py app/modules/gateway/router.py app/modules/conversation/runtime.py tests/conversation/test_runtime.py`：通过。

完整验证：

- `pnpm --dir apps/ai-sdk test -- --run`：通过，15 个测试文件、94/94。
- `pnpm --dir apps/ai-sdk build`：通过，生成 ESM、UMD、CSS 和声明文件。
- `cd apps/backend && poetry run pytest tests/asset tests/gateway tests/conversation -q`：通过，131 个通过、1 个跳过；跳过项为测试套件原有条件跳过。
- `git diff --check`：通过。

未执行真实供应商视觉模型联调；自动化测试已验证 LangChain 收到正确的多模态消息结构，但最终识图能力仍取决于当前 Agent 配置的具体模型是否支持视觉输入。

## 2026-08-26 baseUrl 增量

| 项目 | 命令 | 结果 |
| --- | --- | --- |
| SDK 全量测试 | `pnpm --dir apps/ai-sdk test -- --run` | 通过，15 个测试文件、93 个测试全部通过 |
| SDK 类型检查 | `pnpm --dir apps/ai-sdk type-check` | 通过 |
| SDK 生产构建 | `pnpm --dir apps/ai-sdk build` | 通过，生成 ESM、UMD、CSS 和声明文件 |
| 差异格式检查 | `git diff --check` | 通过 |

新增回归测试覆盖：显式 `baseUrl` 优先用于附件上传，以及未配置时从 `endpoint` 推导 `/api/v1` 的兼容行为。首次执行的 `pnpm --dir apps/ai-sdk typecheck` 因项目无该脚本失败，改用实际脚本 `type-check` 后通过。

未执行项：本次未进行真实后端上传联调，也未验证供应商模型能力；这些属于原附件 request 的后续阶段。

## 2026-08-26 跨设备上传 bugfix

| 项目 | 命令 | 结果 |
| --- | --- | --- |
| 附件服务测试 | `cd apps/backend && poetry run pytest tests/asset -q` | 通过，22 个测试全部通过 |
| 静态检查 | `cd apps/backend && poetry run ruff check app/modules/asset/services.py tests/asset/test_asset_services.py` | 通过 |

新增回归测试模拟 `os.replace` 返回 `errno.EXDEV`，确认文件复制到 storage 后临时文件被删除。

## 2026-08-26 上传响应序列化 bugfix

| 项目 | 命令 | 结果 |
| --- | --- | --- |
| 附件模块测试 | `cd apps/backend && poetry run pytest tests/asset -q` | 通过，23 个测试全部通过 |
| 本次涉及文件静态检查 | `cd apps/backend && poetry run ruff check app/modules/asset/conversation_asset_router.py app/modules/asset/services.py tests/asset/test_asset_services.py` | 通过 |
| 差异格式检查 | `git diff --check` | 通过 |

新增测试确认 `createdAt` 通过 `model_dump(mode="json")` 序列化为 ISO 8601 字符串。全目录 `tests/asset` Ruff 仍有原有 `test_asset_processing.py` 的 3 个未使用导入，未纳入本次改动。
