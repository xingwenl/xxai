# 前端认证接口接入验证记录

## 验证状态

- 当前阶段：verify
- 实现已完成，以下记录均为本次实际执行结果。

## 已执行验证

- 命令：`pnpm exec eslint src/api/auth.ts src/api/user.ts src/lib/http.ts src/stores/auth-store.ts src/features/auth/sign-in/components/user-auth-form.tsx src/features/auth/sign-up/components/sign-up-form.tsx src/components/layout/app-sidebar.tsx src/components/profile-dropdown.tsx`
  - 结果：通过，退出码 0。
- 命令：`pnpm exec prettier --check ...`（本 request 修改的前端文件）
  - 结果：通过，所有文件符合项目格式。
- 命令：`pnpm lint`
  - 结果：失败，退出码 1；包含已有的 `authenticated-layout.tsx` 未使用导入、`sign-out-dialog.tsx` 控制台输出、`mcp-servers.tsx` 表达式问题和 4 个 fast-refresh 警告。本次认证改动文件级 lint 未复现错误。
- 命令：`pnpm build`
  - 结果：失败，退出码 2；前端基线存在 `react-hook-form` 类型导出缺失、`@/features/knowledge/utils` 缺失和系统用户旧类型不匹配等错误，未发现新增的认证 API 路径或 token 字段错误。
- 命令：`curl -s -o /dev/null -w '%{http_code}\\n' http://localhost:8000/api/v1/auth/me`
  - 结果：`000`，后端进程未运行，无法进行真实接口联调。
- 命令：`pnpm dev --host 127.0.0.1 --port 4174`
  - 结果：失败，沙箱禁止监听本地端口，返回 `listen EPERM`；申请受限启动权限被运行环境拒绝，未通过替代方式绕过。
- 静态核对：认证请求为 `/auth/login`、`/auth/register`、`/auth/me`；token 字段为 `access_token`；请求头为 `Authorization: Bearer <token>`；baseURL 为 `VITE_API_URL=/api/v1`。

## 验证结论

- 本 request 的认证接口适配代码已完成，变更文件级 lint 和格式检查通过。
- 全量 lint/build 和浏览器/后端联调仍受前端既有基线错误、后端未启动及运行环境端口限制影响。

## 未解决问题

- 需要修复前端基线依赖和类型问题后重新执行全量 `lint/build`。
- 需要启动后端并使用真实账号验证登录、注册、`/auth/me` 和失效 token。
