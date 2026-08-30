# 验收记录：AI SDK 自定义组件（Generative UI）端到端打通

## 验收结论

对照 `spec.md` 验收标准逐项核对：

1. 后端 `pytest` 新增用例覆盖转换器与 sanitize `component_name` 行为：**通过**（7 个用例）。
2. 后端 `ruff check`：**通过**。
3. SDK `npm run type-check` 通过，`CustomContent.vue` 以 `component_name` 为准渲染、`componentName` 兜底：**通过**。
4. `apps/ai-sdk/README.md` 新增第 9 章“自定义组件（Generative UI）”，含注册方式、标准流程、示例：**通过**。
5. 端到端（Embed 对话触发 `show_user_card` → 渲染卡片 / fallback）：**未执行**，列为剩余风险与人工回归项。

## 剩余风险

- 端到端联调未在本机执行：需要本地后端 + 管理后台启用 `show_user_card` + 宿主 Demo 注册 `UserInfoCard` 后真实触发，建议作为人工回归步骤。
- `custom` 块协议字段统一为 `component_name` 属行为修复：存量若存在按 `componentName` 渲染的历史数据，SDK 已做兜底读取，无破坏性。

## 变更文件

- 后端：`apps/backend/app/modules/conversation/runtime.py`、`apps/backend/app/modules/gateway/runtime.py`、`apps/backend/app/modules/tools/business/custom_component.py`（新增）、`apps/backend/app/modules/tools/business/registry.py`、`apps/backend/tests/conversation/test_custom_content.py`（新增）
- SDK：`apps/ai-sdk/src/core/types.ts`、`apps/ai-sdk/src/ui/components/CustomContent.vue`、`apps/ai-sdk/README.md`
- 测试资产：`apps/ai-sdk/demo/custom-component.html`（新增端到端测试页）
- Harness：`docs/harness/requests/2026-08-30-ai-sdk-custom-component/` 下 research/spec/plan/verify/acceptance/meta

## 未解决问题

- 端到端人工回归尚未执行（见剩余风险）。
