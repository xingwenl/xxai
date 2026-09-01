# 实施计划

## 变更文件

| 文件 | 职责 | 落实方案 |
|---|---|---|
| `apps/ai-sdk/src/ui/index.ts` | 挂载入口 | 依据 `Boolean(options?.container)` 计算 `embedded`，传给 ChatWidget；embedded 时给挂载点设置 `position: relative; width: 100%; height: 100%`，让窗口绝对定位填满容器 |
| `apps/ai-sdk/src/ui/components/ChatWidget.vue` | 核心布局分支 | 新增 `embedded?: boolean` prop；embedded 时恒展开、不渲染悬浮按钮/缩放手柄/返回/关闭按钮、头部禁拖拽、窗口样式仅注入颜色变量、跳过窗口位置持久化与 window resize 监听 |
| `apps/ai-sdk/src/ui/styles/index.css` | 样式变体 | 新增 `.xxai-chat-window--embedded`（`position: absolute; inset: 0`、去掉圆角/阴影/入场动画）；移动端媒体查询用 `:not(.xxai-chat-window--embedded)` 保护 |
| `apps/ai-sdk/src/core/types.ts` | 类型文档 | 仅补充 `mode: 'embedded'` / `container` 的 JSDoc，不改字段 |
| `apps/ai-sdk/README.md` | 用户文档 | 新增「嵌入式模式」章节：示例代码、容器需有高度、与 floating 的差异 |
| `docs/harness/requests/2026-09-01-ai-sdk-embedded-chat-ui/{research,spec,plan,verify,acceptance}.md` | Harness 记录 | 记录调研、设计、实施、验证、验收 |

## 实施步骤

1. 已补文档边界：`research.md` 完成（方案 A 已定）、本 `plan.md`、`spec.md`、`meta.json`。
2. 实现 `ChatWidget.vue` embedded 分支：
   - 新增 prop `embedded?: boolean`（默认 `false`）。
   - 模板：`FloatingButton`、resize handle、头部返回/关闭按钮均 `v-if="!embedded"` 控制。
   - 脚本：`isOpen` 在 embedded 下恒为 true（`open/close/ui_toggle` 事件忽略）；`startDrag` 在 embedded 下直接返回；`windowStyle` 在 embedded 下只返回颜色变量；`onMounted` 中 embedded 时不监听 `window.resize`、不 restore/persist 窗口位置。
3. 实现 `createChatUI`：计算 `embedded`，embedded 时设置挂载点 `position: relative; width: 100%; height: 100%`。
4. 实现 CSS 变体：`.xxai-chat-window--embedded` 覆盖定位与外观；媒体查询排除 embedded。
5. 更新 `types.ts` JSDoc 与 `README.md`。
6. 验证（见测试步骤），回填 `verify.md` / `acceptance.md`，更新 `meta.json` 阶段。

## 测试步骤

1. `cd apps/ai-sdk && npm run type-check`：预期 0 错误。
2. `cd apps/ai-sdk && npm run test -- --run`：预期全部用例通过（floating 布局纯函数不受影响）。
3. `cd apps/ai-sdk && npm run build && npm run verify-package`：预期构建成功、包入口校验通过。
4. 浏览器冒烟（沙箱外 headless Chrome）：构造一个带固定高度容器的临时 HTML，加载构建产物，验证 embedded 填满容器、无悬浮按钮；再验证不传 container 时悬浮按钮仍出现。预期符合 spec 验收标准。

## 回滚说明

- 本次改动集中在 `apps/ai-sdk/src/ui/`、`apps/ai-sdk/src/core/types.ts`（仅注释）、`apps/ai-sdk/README.md` 与 Harness 文档，无数据迁移。
- 回滚方式：`git restore apps/ai-sdk/src apps/ai-sdk/README.md docs/harness/requests/2026-09-01-ai-sdk-embedded-chat-ui`（保留或删除 request 记录视需要而定）。
- 特别关注：`ChatWidget.vue` 中 `isOpen`、窗口样式与事件监听的条件分支；若回滚后 floating 异常，先确认 `embedded` 默认值是否为 `false`。

## 人工确认点

- 无（不涉及架构/数据模型/API 契约/鉴权变化；方案已由用户确认）。
