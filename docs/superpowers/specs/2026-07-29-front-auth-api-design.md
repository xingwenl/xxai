# 前端认证接口接入设计

采用现有 `apps/front` 的 Axios + Zustand + TanStack Router 认证链路，使用 `.env.development` 提供的 `/api/v1` 作为 baseURL。登录调用 `/auth/login`，保存 `data.access_token` 后调用 `/auth/me`；请求拦截器统一发送 `Authorization: Bearer <token>`。注册调用 `/auth/register`，成功后提示并跳转登录页，因为后端当前不返回 token。

认证页面继续放在 `features/auth`，API 只放在 `src/api`，token 和当前用户只放在 `src/stores/auth-store.ts`。当前用户字段以后端 `name/account/email/is_active/roles` 为准，旧模板字段仅在展示层做兼容映射。无效 token 由响应拦截器清理，受保护路由继续由 `_authenticated` 守卫拦截。

本设计不修改后端契约、数据模型、权限规则或整体视觉系统。已获得用户对鉴权行为、注册后跳转和 baseURL 约定的确认。
