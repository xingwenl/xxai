---
name: frontend-architecture
description: 前端架构与分层技能。用于处理新增前端页面、设计新 feature、判断组件放置位置、调整前端结构、梳理页面与路由关系等任务。触发后优先读取 `docs/frontend/README.md` 以及 `apps/front/src/routes`、`features`、`components`、`lib`、`stores`，确保前端目录边界、路由层、feature 分层和组件归属保持一致。
---

# 前端架构技能

## 目标

本 skill 用于约束当前项目的前端目录结构、路由层、feature 分层、组件归属与模块边界。

## 触发场景

当任务涉及以下问题时，优先触发本 skill：

- 新增前端页面
- 设计新 feature
- 判断组件应该放在哪
- 调整前端结构
- 梳理页面、路由、feature 关系

## 优先读取

- `docs/frontend/README.md`
- `apps/front/src/routes`
- `apps/front/src/features`
- `apps/front/src/components`
- `apps/front/src/lib`
- `apps/front/src/stores`

## 核心规则

- 路由层保持薄，只负责挂载和路由边界
- 业务实现优先收敛在 `features`
- 只服务单个 feature 的组件，不随意提升到全局层
- `components/ui` 是基础组件层，不承载业务实现
- 不因为一时方便打破模块边界

## 禁用项

- 禁止把复杂业务逻辑直接写进 `routes/*`
- 禁止跨 feature 引用内部实现细节
- 禁止把私有组件误放到全局复用层
