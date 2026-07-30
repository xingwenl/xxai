# 用户管理前端接入实施计划

## 变更文件

- 修改 `apps/front/src/api/user.ts`：替换旧用户接口类型和路径，增加后端分页与状态字段。
- 修改 `apps/front/src/api/role.ts`：替换旧角色接口类型和路径，提供角色列表查询。
- 修改 `apps/front/src/features/system/users.tsx`：重写旧字段表格和表单，使其匹配后端用户/角色契约。
- 保留 `apps/front/src/routes/_authenticated/system/users.tsx`：不扩散业务逻辑到路由层。

## 实施步骤

1. 更新用户和角色 API 类型，先让请求路径、查询参数、请求体和响应分页结构与后端 schema 一致。
2. 将用户列表查询改为 `name/email` 搜索和 `page/page_size` 分页，映射 `is_active`、`account`、`roles`。
3. 将创建/编辑表单改为 `name/account/email/password/is_active/role_ids`，用 Checkbox 选择角色。
4. 增加状态切换 mutation，使用 `PATCH /users/{id}` 更新 `is_active`，并在成功后失效用户查询。
5. 保留删除确认，改为 `DELETE /users/{id}`，同步处理错误和加载状态。
6. 执行变更文件级 ESLint、Prettier 和路径静态核对；若环境可用，再进行后端联调。
7. 更新 `verify.md`、`acceptance.md` 和 `meta.json`。

## 测试步骤

- `pnpm exec eslint <本次修改的前端文件>`：预期退出码 0。
- `pnpm exec prettier --check <本次修改的前端文件>`：预期所有文件格式通过。
- `rg` 核对不存在 `/api/user`、旧 `username/nickname/enabled` API 映射，且存在 `/users`、`/roles`、`role_ids`、`is_active`。
- 可用时通过后端测试账号验证列表、创建、编辑、状态切换、删除和角色分配。

## 回滚说明

- 只回滚本 request 修改的 API、feature 和 Harness 文档文件。
- 不回滚上一 request 的认证接入、代理配置或工作区其他未相关改动。

## 人工确认点

- 无。后端契约已存在，本次不改变权限、数据模型或 API。
