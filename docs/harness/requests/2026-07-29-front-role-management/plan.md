# 角色管理前端接入实施计划

## 变更文件

- 修改 `apps/front/src/api/role.ts`：新增真实角色 API，保留旧模板 API 导出。
- 修改 `apps/front/src/features/system/roles.tsx`：替换旧字段、路径和菜单权限表单。
- 修改 `apps/front/src/routes/_authenticated/system/roles.tsx`：更新路由 search 类型。

## 实施步骤

1. 在角色 API 模块中新增真实角色类型、分页归一化和 `/roles` CRUD 函数。
2. 将页面列表改为展示编码、名称、描述和状态。
3. 将搜索改为名称/编码，分页改为后端 `page_no/pages`。
4. 将表单改为 `code/name/description/is_active`，创建和编辑共用。
5. 增加状态开关 mutation，保留删除确认和后端错误处理。
6. 执行变更文件级 lint、format 和静态路径核对，更新验证/验收文档。

## 测试步骤

- `pnpm exec eslint <本次修改文件>`：预期无错误。
- `pnpm exec prettier --check <本次修改文件>`：预期通过。
- `rg` 核对 `/roles`、`page_size`、`is_active`，且页面不再使用旧菜单权限字段。
- 后端可用时联调角色 CRUD 和绑定用户角色的删除失败场景。

## 回滚说明

- 只回滚本 request 的角色 API、角色 feature、路由和 Harness 文档。
- 保留用户管理已经使用的真实 `getUserRoles` 接口。

## 人工确认点

- 无。
