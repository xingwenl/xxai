# 前端认证接口接入调研

## 调研问题

本次需要将 `apps/front` 中后台模板已有的登录、注册和当前用户信息页面，接入 `apps/backend` 已提供的认证接口，同时保持现有路由、Axios、Zustand、React Hook Form 和 shadcn/ui 分层。

调研重点是：前端如何保存访问令牌、如何统一注入 Bearer 请求头、如何处理过期会话，以及注册接口不返回令牌时的跳转策略。

## 功能复杂度

- 级别：普通业务功能，包含鉴权行为变更
- 选择理由：涉及多个认证页面、HTTP 协议封装、全局认证状态和受保护路由；不新增后端接口或数据模型，但会影响所有受保护请求。
- 最低调研要求：一个官方路由/HTTP 状态管理来源、一个成熟前端案例，并比较至少两种令牌处理方案。

## 参考依据

### 来源 1

- 类型：官方文档
- 名称：TanStack Router Authentication
- 链接：https://tanstack.com/router/latest/docs/framework/react/guide/authenticated-routes
- 版本或发布日期：TanStack Router React 文档，2026-07-29 调研
- 调研日期：2026-07-29
- 核心做法：在路由 `beforeLoad` 边界判断认证状态，对未认证访问执行重定向；认证数据由应用上下文或客户端状态提供。
- 对本项目的启发：继续使用已有 `_authenticated` 路由守卫，并把登录后的当前用户加载放在认证布局中，不把接口调用写进路由文件。

### 来源 2

- 类型：官方文档
- 名称：Axios Interceptors
- 链接：https://axios-http.com/docs/interceptors
- 版本或发布日期：Axios 文档，2026-07-29 调研
- 调研日期：2026-07-29
- 核心做法：在请求拦截器统一附加认证信息，在响应拦截器集中处理协议错误和 HTTP 401。
- 对本项目的启发：修正现有拦截器，使用后端要求的 `Authorization: Bearer <access_token>`，并在 401 时清理本地令牌。

### 来源 3

- 类型：成熟开源项目
- 名称：shadcn-admin
- 链接：https://github.com/satnaing/shadcn-admin
- 版本或发布日期：当前前端模板结构，2026-07-29 调研
- 调研日期：2026-07-29
- 核心做法：使用 TanStack Router 文件路由、React Hook Form + Zod 表单、Zustand 保存认证状态、feature 目录承载认证页面。
- 对本项目的启发：沿用本仓库现有模板结构，仅替换模拟提交和不匹配的 API 类型，不引入第二套认证库。

## 方案比较

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| `localStorage` 保存 token + Axios 拦截器注入 Bearer | 改动小，匹配已有 Zustand store 和请求封装；刷新页面后仍可保持会话 | 令牌存在 XSS 暴露风险；没有 refresh token 自动续期 | 高，适合当前后端仅提供短期 access token 的契约 |
| 仅保存在内存中 | 令牌不落盘，降低持久化暴露面 | 刷新页面即退出，后台使用体验差；需要额外初始化流程 | 低，不符合现有模板已有持久化设计 |
| HttpOnly Cookie 会话 | 浏览器脚本无法直接读取令牌，安全性更高 | 需要后端改变鉴权契约、处理 CSRF 和跨域 Cookie | 低，本次不应修改后端 API 契约 |

## 最终决策

- 选择方案：保留 `localStorage` 持久化访问令牌，统一通过 Axios 请求拦截器写入 `Authorization: Bearer <token>`；登录后立即调用 `/auth/me` 写入 Zustand；注册成功后跳转登录页，不自动登录。
- 选择原因：完全匹配当前后端 JWT access token 契约、现有前端状态结构和 `.env.development` 的 `/api/v1` baseURL，实施范围可控。
- 不选择其他方案的原因：内存方案会破坏刷新后会话；Cookie 方案需要新增后端契约、跨域和 CSRF 设计，超出本次请求范围。
- 对后续 spec、plan 或人工确认的影响：本次仍属于鉴权行为变更，进入实现前需要人工确认；用户已于 2026-07-29 确认注册成功跳转登录页，且确认 baseURL 已由 `VITE_API_URL=/api/v1` 提供。

## 剩余风险

- 资料时效性：官方文档为通用实现建议，未绑定本项目具体版本；本地模板版本以 `apps/front/package.json` 为准。
- 与本项目上下文的差异：后端 API 使用统一 `{ success, message, data, code }` 包络，前端需继续由 Axios 响应拦截器解包。
- 尚未验证的假设：本地开发代理能够把 `/api/v1` 请求转发到后端；真实数据库和跨服务环境仍需联调。
