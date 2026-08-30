# 验证记录：AI SDK 自定义组件（Generative UI）端到端打通

## 验证范围

- 后端：`custom_content_blocks` 转换器、两条收尾链路接入、`show_user_card` 业务工具注册、sanitize 协议行为。
- SDK：`CustomContent.vue` 以 `component_name` 为准渲染并兼容 `componentName` 兜底、类型字段。

## 验证命令与结果

| 命令 | 预期 | 实际 |
|---|---|---|
| `cd apps/backend && poetry run pytest tests/conversation/test_custom_content.py -q` | 新增用例全部通过 | 通过（9 passed in 1.99s） |
| `cd apps/backend && poetry run ruff check app/modules/conversation/runtime.py app/modules/gateway/runtime.py app/modules/tools/business/custom_component.py app/modules/tools/business/registry.py tests/conversation/test_custom_content.py` | 无 lint 错误 | All checks passed! |
| `cd apps/ai-sdk && npm run type-check` | `vue-tsc --noEmit` 通过 | 通过 |
| `cd apps/ai-sdk && npm run test -- --run` | 无回归 | 通过（15 files / 97 tests passed，含 timeline 分支渲染 custom 块回归用例） |
| `cd apps/ai-sdk && npm run build` | SDK 产物构建成功 | 通过（umd 288.28 kB / es 424.38 kB） |

## 失败项与例外

- 端到端联调未执行：未在本机启动后端 + 管理后台为 Agent 启用 `show_user_card` 并真实触发模型调用。原因是需要本地服务与人工配置，属于人工回归项。
- `builtin_tool` 目录已确认自动从业务注册表派生（`apps/backend/app/modules/builtin_tool/registry.py:106`），`show_user_card` 无需新增代码即可在管理端出现，仅需在 Agent 绑定中启用。
- 已准备端到端测试页 `apps/ai-sdk/demo/custom-component.html`（注册 `UserInfoCard` 示例组件），供人工回归使用。
- 发现 `ChatWidget.vue` 内实例方法 `registerCustomComponent` 写入的 `customComponents` 未被 `CustomContent.vue` 使用（渲染走全局注册表），宿主须使用包导出的 `registerCustomComponent`；本次未修复该死代码，README 已按全局注册写法给出示例。
- 联调反馈修复：`show_user_card` 的 `fallback` 原为必填且 `additionalProperties: false`，模型漏传/多传字段会导致工具 `invalid_arguments` 失败（表现为“调用了工具但无卡片”）。已改为 `fallback` 可选、由 handler 根据 props 自动生成兜底文本，并补充对应用例。
- 联调反馈修复：`ChatMessage.vue` 的 assistant 分支在 `timelineEntries` 非空（消息含工具调用步骤）时只渲染 timeline 文本/步骤，`contentBlocks`（含 `custom` 块）被整体丢弃，导致后端已下发 custom 块但前端不渲染。已新增 `richBlocks`（过滤 text/markdown 后的内容块）在 timeline 分支末尾补渲染，并新增 SSR 回归用例；同时清理联调遗留的 console 调试输出。
- 补充第二个示例组件：新增 `show_shop_list` 业务工具（`ShopList` 组件）与测试用例（props 白名单清洗、fallback 自动生成），验证标准流程可复制；SDK 导出 `h` 供注册组件使用，测试页注册 `UserInfoCard`/`ShopList` 两个组件。
