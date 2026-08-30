# 实施计划：AI SDK 自定义组件（Generative UI）端到端打通

## 变更文件

### 后端 `apps/backend`

- `apps/backend/app/modules/conversation/schemas.py`：不改动（协议字段统一 `component_name`，后端不兼容前端）。
- `apps/backend/app/modules/conversation/runtime.py`：新增 `custom_content_blocks(tool_events)` 转换器；在 `_finish_tool_loop` 的 `GraphResult.content_blocks` 中并入。
- `apps/backend/app/modules/gateway/runtime.py`：`_finish_embed_chat` 的内容块拼接中并入 `custom_content_blocks(result.tool_events)`。
- `apps/backend/app/modules/tools/business/custom_component.py`：新增 `show_user_card` 业务工具，返回 `{"kind": "custom", "component_name": "UserInfoCard", "props": {...}, "fallback": "..."}`。
- `apps/backend/app/modules/tools/business/registry.py`：导入注册 `custom_component`。
- `apps/backend/tests/conversation/test_custom_content.py`：新增转换器与 sanitize 兼容用例。

### SDK `apps/ai-sdk`

- `apps/ai-sdk/src/core/types.ts`：`MessageContentBlock` 增加 `component_name?: string`（协议字段以 `component_name` 为准）。
- `apps/ai-sdk/src/ui/components/CustomContent.vue`：`getCustomComponent(block.component_name ?? block.componentName)`。
- `apps/ai-sdk/README.md`：新增“自定义组件”开发指南。

## 实施步骤

1. 新增转换器：`conversation/runtime.py` 增加 `custom_content_blocks()`，从 `tool_events` 的 `outcome.result.kind == "custom"` 提取块，输出统一 `component_name`。
2. 接入收尾链路：REST（`_finish_tool_loop`）与 Embed WebSocket（`_finish_embed_chat`）两处并入转换器。
3. 新增示例业务工具：`custom_component.py` + `registry.py` 注册，沉淀“新增自定义组件标准范式”注释。
4. 后端测试：覆盖转换器输出与 sanitize 的 `component_name` 行为。
5. SDK 兼容：`types.ts` + `CustomContent.vue`（以 `component_name` 为准，`componentName` 兜底）。
6. 文档：`apps/ai-sdk/README.md` 编写自定义组件指南与新增组件 checklist。
7. 验证与验收记录：执行测试、类型检查，填写 `verify.md` / `acceptance.md`，更新 `meta.json`。

## 测试步骤

- 后端：`cd apps/backend && poetry run pytest tests/conversation/test_custom_content.py -q`，预期全部通过。
- 后端静态检查：`cd apps/backend && poetry run ruff check app/modules/conversation app/modules/gateway app/modules/tools tests/conversation`，预期无错误。
- SDK 类型检查：`cd apps/ai-sdk && npm run type-check`，预期通过。
- SDK 测试：`cd apps/ai-sdk && npm run test`（如涉及组件兼容用例）。
- 端到端（可选，需要本地环境）：本地起后端与 demo，Agent 启用 `show_user_card` 后验证卡片渲染与 fallback。

## 回滚说明

- 后端：移除 `custom_content_blocks` 的两处并入点与工具注册，删除 `custom_component.py`；`schemas.py` 未改动，无需回滚。
- SDK：撤销 `types.ts` 字段与 `CustomContent.vue` 兼容读取（回滚后旧行为为只读 `componentName`）。
- 文档：撤销 README 指南段落。
- 特别关注：`custom` 块在 sanitize 中的校验（`component_name` 合法且 `fallback` 非空）是安全底线，回滚时不得移除该校验。

## 人工确认点

- `custom` 块协议字段统一为 `component_name`（前端兼容后端）属 API 契约变化，**已获用户确认（2026-08-30）**。
- 新增示例业务工具 `show_user_card` 属于功能新增，随确认一并获准。
