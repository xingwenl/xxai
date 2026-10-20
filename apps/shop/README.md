# 店铺运营智能助手（apps/shop）

独立 vite-vue 前端：用户先用店铺运营平台（hua8）账号登录，再在页面内嵌的 AI 智能体聊天窗口中提问「我的店铺」等，智能体通过服务器端工具查询店铺运营平台的数据。

## 运行链路

```text
hua8 登录（验证码 + auth/login）→ 浏览器持有 shopToken / shopUserId
  → 聊天页 ai-sdk（embedded）getToken 调 ai-base POST /api/v1/shop-agent/session
  → ai-base：用 shopToken 调 hua8 getInfo 校验用户 → 店铺 token 写 Redis（TTL=43200，跟随登录时效）
             → 签发短期 embed access_token（external_user_id=shopUserId）
  → 用户问「我的店铺」→ 后端业务工具 store_ops_query 用注入的 shopToken 调 hua8 shop/platform/list
  → 结果与错误原样透传，模型如实回答
```

- 店铺 token 只存浏览器会话（sessionStorage）与 ai-base Redis（不落库、不进消息审计）。
- token 过期时 hua8 接口返回错误，智能体原样透传（如提示重新登录店铺系统）。

## 本地开发

1. 后端准备（ai-base）：确保 `EMBED_CLIENT_ID` / `EMBED_CLIENT_SECRET` / `EMBED_AGENT_ID` / `EMBED_ORIGIN` 已配置，目标智能体已绑定 Embed Client。
2. 安装依赖并启动：

在**仓库根目录**安装 workspace 依赖（本包是根 `pnpm-workspace.yaml` 的成员）：

```bash
pnpm install
pnpm --dir apps/shop dev   # 或根目录 pnpm dev:shop
```

3. 打开 `http://localhost:5174`，用店铺运营平台账号登录。

开发环境代理（`vite.config.ts`）：

- `/hua8-api` → `http://hua8.bbtree.xyz`（店铺系统登录/验证码）
- `/api` → `http://127.0.0.1:8000`（ai-base，含 WebSocket）

## 环境变量

| 变量 | 说明 | 默认 |
|---|---|---|
| `VITE_AGENT_ID` | ai-base 目标智能体 ID（`/api/v1/ws/agents/{agentId}`） | 无 |
| `VITE_PLATFORM_ID` | ai-sdk 平台标识（本地会话隔离） | `shop-agent` |
| `VITE_HUA8_BASE` | 店铺系统接口地址；留空表示同源（开发由代理转发） | 空 |

## 生产部署

- 前端构建产物：`pnpm build`（输出 `dist/`）。
- 部署层（如 Nginx）需把 `/api` 反代到 ai-base（含 WebSocket Upgrade 头），`/hua8-api` 反代到店铺运营平台，避免浏览器跨域与混合内容问题。
- 页面与 ai-base 必须同源或使用 HTTPS，店铺 token 经 `/api/v1/shop-agent/session` 传给 ai-base。
