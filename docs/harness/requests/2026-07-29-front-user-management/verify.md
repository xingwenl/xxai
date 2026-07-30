# 用户管理前端接入验证记录

## 验证状态

- 当前阶段：verify
- 实现已完成，以下记录为本次实际执行结果。

## 已执行验证

- 命令：`pnpm exec prettier --write src/api/user.ts src/api/role.ts src/lib/http.ts src/features/system/users.tsx src/routes/_authenticated/system/users.tsx`
  - 结果：通过，文件已按项目规范格式化。
- 命令：`pnpm exec eslint src/api/user.ts src/api/role.ts src/lib/http.ts src/features/system/users.tsx src/routes/_authenticated/system/users.tsx`
  - 结果：无错误，退出码 0；路由文件保留 1 个已有 fast-refresh 警告。
- 命令：`pnpm build`
  - 结果：失败，退出码 2；已有基线问题包括 `react-hook-form` 类型导出缺失、`@/features/knowledge/utils` 缺失、认证布局未使用导入。本次引入的旧角色 API 导出冲突已修复，未再出现角色页面 API 类型错误。
- 静态核对：用户请求使用 `/users`、`page_size`、`role_ids`、`is_active`；角色数据使用 `/roles`；旧系统用户页面不再使用旧 `/api/user` 字段。
- 静态核对：统一 HTTP 包络同时接受成功码 `0` 和后端分页响应成功码 `200`。

## 未解决问题

- 后端服务未运行，尚未用真实账号完成列表、创建、编辑、状态切换、删除和角色分配联调。
- 前端全量构建需要先修复已有依赖和模块基线问题。
