# 用户管理前端接入规格

## 目标

- 将 `/system/users` 接入后端 `/api/v1/users` 和 `/api/v1/roles`。
- 支持用户列表、按名称/邮箱搜索、分页、创建、编辑、启用/停用、删除和角色分配。
- 使用后端真实字段和分页结构，删除旧 `/api/user` 路径以及 `username/nickname/enabled` 等旧接口模型依赖。

## 范围

- 修改 `apps/front/src/api/user.ts`：定义后端用户、角色摘要、分页数据和用户 CRUD API。
- 修改 `apps/front/src/api/role.ts`：定义角色列表 API，使用 `/roles` 相对路径。
- 修改 `apps/front/src/features/system/users.tsx`：接入真实列表、筛选、分页、用户表单、角色多选、状态切换和删除确认。
- 保留 `apps/front/src/routes/_authenticated/system/users.tsx` 作为薄路由入口。
- 保留 `apps/front/src/routes/_authenticated/users/index.tsx` 模板页不变，避免把假数据页面与系统管理入口混合。

## 非目标

- 不修改后端用户、角色 API 或数据库模型。
- 不新增批量删除、批量导入、密码重置、邮箱验证、部门管理或细粒度前端权限判断。
- 不实现角色管理页面本身；角色列表只作为用户分配角色的数据源。

## 风险

- 用户删除和停用可能影响当前登录账号，前端不阻止后端允许的操作；真实权限策略由后端负责。
- 前端当前全量构建存在基线错误，本次会执行变更文件级 lint/format 和静态 API 核对。
- 角色列表查询失败时，用户表单仍应可打开，但角色分配不可用并显示错误提示。

## 停点判断

- 是否涉及架构边界变化：否。
- 是否涉及数据模型变化：否。
- 是否涉及 API 契约变化：否，前端仅适配已存在契约。
- 是否涉及鉴权或权限行为变化：否，不新增或修改权限判定。
- 结论：无需额外人工确认，可在计划完成后实现。

## 验收标准

- 列表请求使用 `/users`，发送 `page/page_size/name/email`，并正确归一化后端 `page_no/page_size/items/total/pages`。
- 创建请求发送 `name/email/account/password/role_ids`。
- 编辑请求可修改 `name/email/account/is_active/role_ids`。
- 页面可以切换启用/停用，状态更新后列表自动刷新。
- 角色选择展示后端角色名称，提交 role id 数组。
- 删除操作有确认弹窗，成功后刷新列表。
- 搜索和分页状态写入现有 TanStack Router search 参数。
- 变更文件级 ESLint 和 Prettier 检查通过。

## 变更记录

### 初始版本

- 时间：2026-07-29
- 变更原因：首次创建 request
- 变更内容：建立真实用户管理页面的 API、交互和验收边界
- 影响章节：全部
- 是否触发人工确认：否
