# 业界调研记录：ai-sdk 支持将聊天 UI 挂载到指定 DOM 元素（embedded 模式）

## 调研问题

- 宿主页面希望把聊天 UI 直接「嵌进」页面里的某个容器（如侧栏、内容区），而不是悬浮在视口上，业界聊天 SDK 如何提供这种能力？
- 如何在不破坏现有 `floating` 悬浮窗行为的前提下，让 `container` / `mode: 'embedded'` 真正生效？

## 功能复杂度

- 级别：普通业务功能
- 选择理由：修改 SDK UI 层（ChatWidget 布局与参考区域），影响公开 API 行为（`embedded` 模式从“等同 floating”变为“填满容器”），但不涉及协议、数据模型与鉴权。
- 最低调研要求：至少一个成熟聊天 SDK 的 inline/embedded 用法来源，完成方案比较并记录决策。

## 参考依据

### 来源 1：Alhena Chat Widget Inline Embed

- 类型：成熟开源项目/官方文档
- 名称：Alhena Chat Widget — Inline Embed
- 链接：https://alhena.gitbook.io/docs/features/chat-widget/inline-embed
- 版本或发布日期：长期维护
- 调研日期：2026-09-01
- 核心做法：同一套 JS SDK 同时提供 `floating`（悬浮 launcher）与 `inline` 两种模式；inline 模式把聊天窗口直接渲染到宿主页面指定的容器元素内，与悬浮模式共用全部事件与 API。
- 对本项目的启发：本项目 `UIOptions` 已声明 `mode: 'embedded'` 与 `container`，方向与业界一致，只需把声明变成真实行为；两种模式共用 `createAgentClient` 是正确形态。

### 来源 2：ago-sdk mountChatWidget

- 类型：成熟开源项目
- 名称：ago-sdk — mountChatWidget
- 链接：https://github.com/useago/ago-sdk/blob/912f1b7d8c93c243ca3760f9890dc7cd3a795283/docs/general/widget.md
- 版本或发布日期：2026 年文档
- 调研日期：2026-09-01
- 核心做法：`mountChatWidget("#ago-chat", config)` 把面板 inline 渲染进宿主容器，面板完全由宿主布局决定尺寸；样式通过 CSS 自定义属性提供可覆盖入口；小屏时可全屏。
- 对本项目的启发：embedded 布局应「跟随容器尺寸」而非视口；SDK 用 CSS 变量（`--xxai-*`）暴露样式可覆盖点即可，无需 Shadow DOM。

### 来源 3：@opiniom/web（inline mode with container）

- 类型：npm 包/生产实践
- 名称：@opiniom/web — floating | inline + container
- 链接：https://www.npmjs.com/package/@opiniom/web
- 版本或发布日期：2026 年
- 调研日期：2026-09-01
- 核心做法：配置 `mode: "inline"` + `container: "#chat-container"`，聊天直接嵌入容器元素，容器需有高度（如 `height: 100%`）。
- 对本项目的启发：容器必须由宿主给定尺寸（高度），SDK 负责填满；文档需注明容器需有高度。

## 方案比较

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| 方案 A：实现 `embedded` 模式，container 驱动 | API 与业界一致（同一 SDK、`mode`+`container`）；floating 分支不动，回归面小；填满容器由 CSS + 参考区域切换完成 | 需要改 ChatWidget 布局分支与 CSS 变体；容器高度由宿主负责 | 最高 |
| 方案 B：只透传 container，不改布局 | 改动最小 | 现状就是如此——窗口仍是 fixed 悬浮，`container` 无效，不满足需求 | 低（现状即此） |
| 方案 C：Shadow DOM 强隔离 | 宿主样式完全隔离 | 改动大，事件冒泡、表单、字体继承都要处理；本项目已有 `.xxai-reset` + CSS 变量方案 | 中，用户已确认沿用现状 |

## 最终决策

- 选择方案：方案 A（实现 `embedded` 模式，`container` 驱动）
- 选择原因：
  1. 用户已确认：传了 `container` 就填满容器做页面级聊天；不传保持现状。
  2. 与业界一致（Alhena inline / ago-sdk mountChatWidget / opiniom inline），后续宿主接入心智成本低。
  3. floating 布局代码保留，改动集中在 embedded 分支，回归风险可控。
- 不选择方案 B/C 的原因：B 不满足需求；C 超出本次范围（用户已确认沿用 `.xxai-reset` + CSS 变量）。
- 对后续 spec、plan 的影响：`ChatWidget.vue` 增加 `embedded` 分支；`createChatUI` 依据 `container` 是否传入决定 embedded；`src/index.ts` 无需改动（container 已透传）；CSS 增加 embedded 变体并覆盖移动端媒体查询。

## 剩余风险

- 资料时效性：低，聊天 SDK inline 模式是成熟稳定形态。
- 与本项目上下文的差异：本项目窗口为 Vue 组件直接渲染（非 iframe），inline 时宿主样式可能影响内部元素；`.xxai-reset` + CSS 变量可覆盖大部分场景，极端宿主样式冲突留待后续评估。
- 尚未验证的假设：embedded 下消息列表/输入框的 flex 布局能随容器高度正确伸缩（将用 headless Chrome 运行时验证）。
