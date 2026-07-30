# 角色管理前端接入规格

## 目标

- 将 `/system/roles` 接入 `/api/v1/roles`。
- 支持角色列表、按名称/编码搜索、分页、创建、编辑、启用/停用和删除。
- 使用后端真实字段 `code/name/description/is_active`，移除旧 `title/memo/menu_ids/enabled` 业务依赖。

## 范围

- 扩展 `apps/front/src/api/role.ts`：保留旧模板导出，同时新增真实角色类型及 CRUD API。
- 重写 `apps/front/src/features/system/roles.tsx`：使用真实列表、搜索、分页、表单、状态开关和删除确认。
- 更新 `apps/front/src/routes/_authenticated/system/roles.tsx`：将 search 参数改为 `name/code`。
- 不改变用户管理使用的 `getUserRoles` API。

## 非目标

- 不新增菜单权限、资源权限或角色继承配置；后端当前没有对应契约。
- 不修改后端角色模型、接口或删除约束。
- 不处理批量删除和角色绑定详情展示。

## 风险

- 删除绑定用户的角色会失败，需要展示后端错误。
- 全量前端构建仍可能受既有依赖基线问题影响。

## 停点判断

- 架构边界变化：否。
- 数据模型变化：否。
- API 契约变化：否。
- 鉴权或权限行为变化：否，仅消费已有登录保护接口。
- 结论：无需额外人工确认。

## 验收标准

- 列表使用 `/roles`，发送 `page/page_size/name/code`，正确处理后端分页字段。
- 创建发送 `code/name/description`。
- 编辑发送 `code/name/description/is_active`。
- 状态开关调用 `PATCH /roles/{id}` 并刷新列表。
- 删除调用 `DELETE /roles/{id}`，失败时保留页面并展示后端消息。
- 搜索和分页写入路由 search 参数。
- 变更文件级 ESLint 和 Prettier 通过。

## 变更记录

### 初始版本

- 时间：2026-07-29
- 变更原因：首次创建 request
- 变更内容：建立真实角色管理边界和验收标准
- 影响章节：全部
- 是否触发人工确认：否
