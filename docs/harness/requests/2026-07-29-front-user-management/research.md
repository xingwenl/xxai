# 用户管理前端接入调研

## 调研问题

将 `apps/front` 的 `/system/users` 页面接入后端真实用户与角色接口，覆盖列表、搜索、分页、创建、编辑、启用/停用、删除和角色分配，同时保持现有后台模板的布局与数据流。

## 功能复杂度

- 级别：普通业务功能
- 选择理由：涉及一个 feature、两个 API 模块、React Query 查询/变更状态和表单字段映射；后端接口已经存在，不新增 API 契约或数据模型。
- 最低调研要求：官方 React Query 数据变更实践、成熟后台表格实践，以及本仓库后端契约核对。

## 参考依据

### 来源 1

- 类型：官方文档
- 名称：TanStack Query Mutations
- 链接：https://tanstack.com/query/latest/docs/framework/react/guides/mutations
- 版本或发布日期：TanStack Query React 文档，2026-07-29 调研
- 调研日期：2026-07-29
- 核心做法：使用 mutation 封装创建、更新、删除等服务端变更，在成功后使相关 query 失效并重新获取。
- 对本项目的启发：沿用页面现有 `useMutation`，在用户变更成功后失效 `['system', 'users']` 和必要的角色查询。

### 来源 2

- 类型：成熟开源项目
- 名称：shadcn-admin
- 链接：https://github.com/satnaing/shadcn-admin
- 版本或发布日期：当前仓库引入的模板结构，2026-07-29 调研
- 调研日期：2026-07-29
- 核心做法：表格、筛选、分页、表单对话框按 feature 组织，基础交互复用 shadcn/ui，路由只负责挂载。
- 对本项目的启发：保留 `/system/users` 路由和页面布局，替换页面内部的模拟/旧接口数据，不复用 `/users` 的假数据 provider。

### 来源 3

- 类型：本项目后端接口与测试
- 名称：FastAPI 用户模块与 OpenAPI 测试
- 链接：`apps/backend/app/modules/user/router.py`、`apps/backend/app/modules/user/schemas.py`、`apps/backend/tests/user/test_routes.py`
- 版本或发布日期：当前仓库 HEAD，2026-07-29 调研
- 调研日期：2026-07-29
- 核心做法：真实前缀为 `/api/v1/users`；用户字段为 `name/account/email/is_active/roles`；列表分页字段为 `page_no/page_size/items/total/pages`；角色通过 `role_ids` 维护。
- 对本项目的启发：前端 API 使用相对 `/users` 路径配合 `VITE_API_URL=/api/v1`，不能继续使用旧的 `/api/user`、`username`、`nickname`、`enabled` 等字段。

## 方案比较

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| 改造现有 `/system/users` 页面 | 保留路由、布局和交互骨架，改动集中；可快速接入真实 API | 需要清理旧字段和旧表单逻辑 | 高，符合用户确认的系统管理入口 |
| 使用模板 `/users` 页面并替换其 provider | UI 更完整，具备批量操作骨架 | 当前依赖假数据、旧字段和模板状态，替换范围大 | 中，容易混入无后端依据的状态和角色模型 |
| 新建独立用户管理 feature | 边界最干净 | 重复已有页面布局和大量基础交互 | 低，不符合 YAGNI |

## 最终决策

- 选择方案：改造现有 `/system/users` 页面，并新增真实 `role` API 封装；统一使用 React Query 管理列表/角色查询和 mutation。
- 选择原因：后端契约清晰，现有页面已经具备搜索、分页、对话框和删除确认结构，风险和改动面最小。
- 不选择其他方案的原因：模板 `/users` 仍是假数据；新建 feature 会产生重复页面和维护分叉。
- 对 spec、plan 或人工确认的影响：不修改后端接口、数据模型和权限规则，不触发额外人工停点。

## 剩余风险

- 后端当前所有用户和角色接口只要求当前用户已登录，细粒度管理员权限尚未由后端提供；本次不在前端伪造权限控制。
- 后端删除语义由服务实现决定，前端仅展示后端成功结果。
- 前端全量构建仍受上一 request 记录的基线问题影响，需要通过变更文件级检查和接口静态核对降低风险。
