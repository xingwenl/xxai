# 验收记录

## 验收结论

- 达到 `spec.md` 全部验收标准：
  1. 传入 `ui.container` 时聊天窗口默认展开并填满容器，无悬浮按钮、无拖拽/缩放手柄、头部无返回/关闭按钮，容器尺寸变化时自动跟随 —— 已通过浏览器实测确认。
  2. 不传 `container` 时 floating 行为与改动前一致（悬浮按钮存在、窗口默认关闭、拖拽/缩放/移动端媒体查询代码未改动）—— 已通过浏览器实测确认。
  3. `open()/close()/toggle()` 在 embedded 下不产生开关效果（`ChatWidget.vue` 中已对 embedded 分支短路）—— 代码核对 + 浏览器实测（窗口恒展开）。
  4. type-check、单测（97 通过）、build、verify-package 全部通过。
  5. `README.md` 已新增「嵌入式模式（Embedded）」章节，含示例代码与容器需有确定高度的约束说明。
- 本 request 可以视为完成，等待用户确认后提交。

## 剩余风险

- 未连接真实后端联调（demo 使用 mock token）；embedded 模式下消息流、附件上传依赖既有 floating 同款组件与事件链路，改动未触碰该链路。
- 宿主页面极端样式冲突仍依赖 `.xxai-reset` + CSS 变量兜底，未逐一测试宿主全局样式污染场景（沿用现有方案，属已知边界）。
- 容器为 `display: none` 或高度为 0 时聊天窗口会塌陷，README 已注明容器需有确定高度。

## 人工验收记录

- 用户已确认方案（传 container 填满容器、不传保持现状、样式隔离沿用现有方案）。
- demo 测试页 `apps/ai-sdk/demo/embedded.html` 已提供，可人工打开验证两种模式。
- 本次未要求额外人工验收。
