# 前端认证接口接入实施计划

## 变更文件

- 修改 `apps/front/src/api/auth.ts`：定义登录、注册、token 响应类型及请求函数。
- 修改 `apps/front/src/api/user.ts`：定义后端当前用户类型并实现 `/auth/me` 调用。
- 修改 `apps/front/src/lib/http.ts`：修正 Bearer 头注入，处理统一包络和 401。
- 修改 `apps/front/src/stores/auth-store.ts`：同步后端字段与 token 生命周期。
- 修改 `apps/front/src/features/auth/sign-in/components/user-auth-form.tsx`：接入真实登录和当前用户加载。
- 修改 `apps/front/src/features/auth/sign-up/components/sign-up-form.tsx`：接入真实注册和成功跳转。
- 修改 `apps/front/src/components/layout/app-sidebar.tsx`、`apps/front/src/components/profile-dropdown.tsx`：适配后端用户字段。
- 修改 `apps/front/vite.config.ts`：让开发代理原样转发 `/api/v1` 到后端根地址。
- 修改 `apps/front/.env.example`：说明 API baseURL 已包含 `/api/v1`。
- 新增 `apps/front` 下认证单元测试（若现有工具链无测试运行器，则以类型检查、lint、build 和接口代码核对替代，并在 `verify.md` 记录）。

## 实施步骤

1. 先确认现有工作区状态，避免覆盖用户已存在的 `apps/front` 或其他无关改动。
2. 按后端 OpenAPI 与 schema 更新认证 API 类型，保持业务路径相对 `VITE_API_URL`。
3. 修正 Axios 请求拦截器，将 token 转为标准 Bearer Authorization；保留 401 清理并避免把登录请求误处理成已登录状态。
4. 更新 Zustand 用户类型和认证表单：登录成功保存 token，再请求 `/auth/me`；注册成功只提示并跳转登录页。
5. 调整展示组件和认证布局的字段映射，清理旧模板中的 `username/nickname/avatar` 假字段依赖。
6. 校正开发代理，确保 `/api/v1` 原样到达后端，再执行 `pnpm lint`、`pnpm build`；必要时启动开发服务检查登录、注册路由和 API 请求路径。
7. 将真实命令、结果、失败项和联调限制写入 `verify.md`，再写入 `acceptance.md`。

## 测试步骤

- `pnpm --dir apps/front lint`：预期无 ESLint 错误。
- `pnpm --dir apps/front build`：预期 TypeScript 与 Vite 构建成功。
- `rg` 核对请求路径、Authorization 头、token 字段和注册跳转逻辑。
- 后端联调时验证：登录 200、注册 201、`/auth/me` 200，以及无效 token 返回 401。

## 回滚说明

- 代码回滚范围限于本 request 列出的前端文件和 Harness 文档。
- 不回滚用户工作区中与本 request 无关的前端页面或后端改动。
- 若联调失败，可先恢复旧的登录/注册页面，但不能保留错误的非 Bearer Authorization 头。

## 人工确认点

- 已确认：鉴权行为变更允许实施。
- 已确认：注册成功跳转登录页，由用户再次登录。
- 已确认：`VITE_API_URL=/api/v1` 已配置，代码中不重复添加 `/api/v1`。
