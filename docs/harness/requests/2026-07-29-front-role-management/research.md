# 角色管理前端接入调研

## 调研问题

将 `/system/roles` 从旧模板字段和旧接口切换到后端真实角色 API，支持角色列表、搜索、分页、创建、编辑、启用/停用和删除，并不影响用户管理对角色列表的依赖。

## 功能复杂度

- 级别：普通业务功能
- 选择理由：涉及一个 feature、一个 API 模块和 React Query CRUD 状态；后端契约已存在，不新增数据模型或权限规则。
- 最低调研要求：参考 TanStack Query mutation 官方实践、现有 shadcn-admin 页面结构和本仓库后端角色 schema。

## 参考依据

### 来源 1

- 类型：官方文档
- 名称：TanStack Query Mutations
- 链接：https://tanstack.com/query/latest/docs/framework/react/guides/mutations
- 版本或发布日期：TanStack Query React 文档，2026-07-29 调研
- 调研日期：2026-07-29
- 核心做法：服务端创建、更新、删除使用 mutation，成功后失效相关列表 query。
- 对本项目的启发：角色 CRUD 继续使用页面现有 `useMutation` 和 `invalidateQueries`。

### 来源 2

- 类型：本项目后端接口与测试
- 名称：FastAPI 角色模块
- 链接：`apps/backend/app/modules/role/router.py`、`apps/backend/app/modules/role/schemas.py`
- 版本或发布日期：当前仓库 HEAD，2026-07-29 调研
- 调研日期：2026-07-29
- 核心做法：接口前缀 `/api/v1/roles`；角色字段为 `code/name/description/is_active`；分页字段为 `page_no/page_size/items/total/pages`；删除有用户绑定冲突保护。
- 对本项目的启发：前端使用相对 `/roles` 路径，表单不再展示不存在的 `menu_ids`，删除错误直接展示后端消息。

### 来源 3

- 类型：成熟开源项目
- 名称：shadcn-admin
- 链接：https://github.com/satnaing/shadcn-admin
- 版本或发布日期：当前前端模板结构，2026-07-29 调研
- 调研日期：2026-07-29
- 核心做法：列表页、搜索、分页和对话框表单按 feature 组织，基础 UI 复用 shadcn/ui。
- 对本项目的启发：保留 `/system/roles` 页面布局，只替换数据源和业务字段。

## 方案比较

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| 改造现有 `/system/roles` 页面 | 复用布局和交互骨架，改动集中 | 需要清理旧菜单权限字段 | 高 |
| 新建角色 feature | 边界清晰 | 与现有页面重复，成本高 | 低 |
| 继续使用旧模板接口并做字段转换 | 短期改动少 | 请求路径和后端模型完全不一致，无法真实运行 | 低 |

## 最终决策

- 选择方案：改造现有 `/system/roles`，在 `api/role.ts` 中新增真实角色 CRUD，保留旧模板导出给暂未迁移的代码。
- 选择原因：能复用现有页面并避免破坏用户管理已经使用的真实角色查询。
- 不选择其他方案的原因：新建页面重复代码；旧接口不存在于当前后端。
- 对 spec、plan 或人工确认的影响：不修改后端契约、数据模型和权限行为，无额外人工停点。

## 剩余风险

- 删除被用户绑定的角色会被后端拒绝，前端只展示错误消息。
- 真实后端服务未运行时无法完成浏览器联调。
