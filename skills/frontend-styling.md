---
name: frontend-styling
description: 前端样式与视觉一致性技能。用于处理页面样式调整、新增页面 UI、统一视觉风格、调整主题布局、表单卡片样式以及后台与聊天区域视觉一致性等任务。触发后优先读取 `docs/frontend/README.md`、`components.json`、样式文件和基础 UI 组件目录，确保遵循 shadcn/ui、Tailwind v4、主题 token 和现有设计语言。
---

# 前端样式技能

## 目标

本 skill 用于约束当前项目的样式风格、组件视觉一致性、Tailwind 使用方式与 shadcn/ui 组合方式。

## 触发场景

当任务涉及以下问题时，优先触发本 skill：

- 调整页面样式
- 新增页面 UI
- 统一视觉风格
- 调整主题、布局、卡片、表单样式
- 优化后台与聊天区域的视觉一致性

## 优先读取

- `docs/frontend/README.md`
- `apps/front/components.json`
- `apps/front/src/styles/index.css`
- `apps/front/src/styles/theme.css`
- `apps/front/src/components/ui`
- `apps/front/src/components/layout`

## 核心规则

- 优先复用现有 `shadcn/ui` 基础组件
- 优先使用语义化 token，不乱写原始颜色
- 优先使用 `cn()` 组合类名
- 优先使用 `gap-*`
- 宽高相等优先使用 `size-*`
- 新样式优先在业务组件层收敛，不轻易改基础 UI 层
- 聊天页面可优化体验，但不能切断后台整体设计语言

## 禁用项

- 禁止在业务组件中大量使用原始颜色值
- 禁止随意覆盖全局主题变量
- 禁止复制基础 UI 组件长期分叉
- 禁止把页面级布局样式塞进 `components/ui`
