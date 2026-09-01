# 设计说明

## 目标

- 让 `xxai-agent` SDK 支持把聊天 UI 直接嵌入宿主页面指定容器（页面级聊天），而不是只能悬浮在视口上。
- 目标用户：需要在侧栏、内容区等固定区域展示聊天的接入方。
- 完成后的可验证结果：传入 `ui.container` 时，聊天窗口默认展开并填满该容器，无悬浮按钮、无拖拽/缩放手柄；不传时，现有 floating 悬浮行为完全不变。
- 依据 `research.md`：采用方案 A（实现 `embedded` 模式，`container` 驱动），与业界 Alhena inline / ago-sdk mountChatWidget / @opiniom/web inline 的做法一致。

## 范围

- 本 request 只改 `apps/ai-sdk`：
  - `src/ui/components/ChatWidget.vue`：新增 `embedded` 分支（默认展开、无悬浮按钮、无拖拽/缩放、无返回/关闭按钮）。
  - `src/ui/index.ts`：根据 `container` 是否传入决定 `embedded`，并设置挂载点填充容器。
  - `src/ui/styles/index.css`：新增 `--embedded` 变体样式，并保护现有移动端媒体查询不影响 embedded。
  - `src/core/types.ts`：仅补充 `container` / `mode: 'embedded'` 的 JSDoc 说明，不改字段契约。
  - `README.md`：新增 embedded 接入示例与容器高度要求。
- `UIOptions.mode: 'embedded'` 与 `container` 字段此前已声明，本次是把声明变成真实行为；`src/index.ts` 无需改动（已透传 `container`）。
- 与原闭环的关系：这是新 request，无历史闭环可复用。

## 非目标

- 不做 Shadow DOM 强隔离（用户已确认沿用 `.xxai-reset` + CSS 变量）。
- 不做「单文件 HTML 单体应用」或打包演示页（上一轮已全部回退，用户当前只要 embedded 能力）。
- 不新增后端接口、不改协议字段、不改鉴权。
- 不处理宿主容器尺寸为 0 / 动态出现等情况下的特殊降级（CSS 自动跟随容器，容器高度由宿主负责）。

## 风险

- 回归风险：`floating` 分支全部保留，改动集中在新增分支；`container` 未传入时 `embedded=false`，行为与现状一致。
- 兼容性风险：`mode: 'embedded'` 之前实际表现为悬浮，接入方若已在用（理论上无），行为会变为填满容器，属预期内的功能修正。
- 样式风险：embedded 依赖宿主容器有明确高度，否则高度塌陷；将通过 README 明确要求，并在验证阶段用真实浏览器确认。
- 数据风险：无（不涉及消息、会话、本地存储逻辑；embedded 下不读写窗口位置存储）。
- 当前未识别到高风险运行时变更。

## 停点判断

- 是否涉及架构边界变化：否（不改模块边界与依赖，只改 SDK UI 内部分支）。
- 是否涉及数据模型变化：否。
- 是否涉及 API 契约变化：否（`UIOptions.mode` / `container` 已存在，类型字段无增删改）。
- 是否涉及鉴权或权限行为变化：否。
- 结论：任一项均为“否”，不触发人工确认；且用户已明确确认方案（“传 container 优先填满容器页面级聊天，不传现状保持不变，样式隔离沿用现在的”）。

## 验收标准

- 传入 `ui.container` 时：聊天窗口默认展开、无悬浮按钮、无窗口拖拽/缩放手柄、头部无返回/关闭按钮；窗口宽高跟随容器（容器尺寸变化时自动填充）。
- 不传 `ui.container` 时：悬浮按钮、悬浮窗口、拖拽、缩放、移动端媒体查询等行为与改动前完全一致。
- `agent.open()/close()/toggle()` 在 embedded 模式下不产生窗口开关效果（默认恒展开）。
- `npm run type-check`、`npm run test -- --run`、`npm run build`、`npm run verify-package` 全部通过。
- `README.md` 增加 embedded 章节：示例代码 + 容器需有高度等约束说明。

## 变更记录

### 初始版本

- 时间：2026-09-01
- 变更原因：首次创建 request
- 变更内容：建立本次任务的初始设计说明（embedded 模式：container 驱动填满容器）
- 影响章节：全部
- 是否触发人工确认：否（方案已由用户确认）
