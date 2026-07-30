# 前端认证接口接入规格

## 目标

- 将后台模板的登录页、注册页接入后端认证接口。
- 登录成功后保存后端返回的 `access_token`，加载当前用户，并进入原始目标页面。
- 应用启动或进入受保护布局时，通过 `/auth/me` 恢复当前用户信息。
- 接入后端真实用户字段：`name`、`account`、`email`、`is_active`、`roles`。
- 关键依据见本 request 的 `research.md`：沿用 TanStack Router 路由守卫、Axios 拦截器和现有 Zustand 持久化方案。

## 范围

- 修改 `apps/front/src/api/auth.ts`：补齐注册接口和后端 token 响应类型。
- 修改 `apps/front/src/api/user.ts`：将当前用户类型调整为后端 `/auth/me` 契约，保留系统用户接口待后续独立适配。
- 修改 `apps/front/src/lib/http.ts`：使用 `Bearer` 认证头，并保持统一响应包络解包及 401 清理。
- 修改 `apps/front/src/stores/auth-store.ts`：保存和清理后端 access token，统一当前用户字段。
- 修改登录表单：提交 `account/password`，登录后调用 `/auth/me`，成功后按 `redirect` 安全跳转。
- 修改注册表单：补齐 `name/account/email/password/confirmPassword`，调用注册接口，成功后跳转登录页。
- 修改认证布局和侧边栏用户展示，使其使用后端 `name/account/email`。
- 更新 `apps/front/.env.example` 的说明，保持 `.env.development` 的 `/api/v1` 配置不变。

## 非目标

- 不修改后端认证接口、数据库模型、JWT 策略或权限规则。
- 不新增 refresh token、OAuth、邮箱验证、找回密码或个人资料更新接口。
- 不把现有系统用户管理接口 `/api/user` 改造成后端当前 `/api/v1/users` 契约；该接口适合另一个独立 request 处理。
- 不重做后台模板的整体视觉设计。

## 风险

- 当前 token 以 `localStorage` 保存，存在脚本注入后的读取风险；本次沿用现有设计，后续可单独评估 Cookie 会话。
- 后端错误消息目前为英文，前端先展示接口返回消息，不在本次任务扩展错误码映射。
- 后端注册不返回 token，注册成功后必须重新登录。
- 若开发代理未正确转发 `/api/v1`，需要联调环境修正代理配置，但不改变 API 封装路径。

## 停点判断

- 是否涉及架构边界变化：否，沿用现有前端分层。
- 是否涉及数据模型变化：否。
- 是否涉及 API 契约变化：否，前端适配既有后端契约。
- 是否涉及鉴权或权限行为变化：是，登录、token 注入、当前用户恢复和 401 清理都会生效。
- 结论：进入实现前需人工确认。用户已于 2026-07-29 确认本规格：注册成功跳转登录页；`VITE_API_URL=/api/v1` 已配置，业务接口不重复添加前缀。

## 验收标准

- 登录请求路径为 `/auth/login`，请求字段为 `account/password`，并正确读取 `data.access_token`。
- 登录成功后请求 `/auth/me`，侧边栏和用户下拉菜单展示后端当前用户信息。
- 所有带 token 的请求均发送 `Authorization: Bearer <token>`。
- 注册页可以提交后端要求的四个业务字段和确认密码；成功后跳转 `/sign-in`，不写入伪造 token。
- 刷新受保护页面时，已有 token 可以加载 `/auth/me`；token 无效时清理状态并跳转登录页。
- `pnpm build`、`pnpm lint` 在 `apps/front` 执行成功。

## 变更记录

### 初始版本

- 时间：2026-07-29
- 变更原因：首次创建 request
- 变更内容：建立前端认证 API 接入边界和验收标准
- 影响章节：全部
- 是否触发人工确认：是，已确认
