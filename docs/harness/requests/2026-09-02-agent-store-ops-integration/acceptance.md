# 验收记录：智能体接入店铺运营项目（查询我的店铺）

## 验收结论

- 实现已完成并通过本地验证（后端 146 passed、ruff 0 错误、前端构建成功），对照 `spec.md` 验收标准：
  - [x] 会话接口 `POST /api/v1/shop-agent/session` 已实现（路由注册、店铺 token 校验、Redis 写入、embed token 签发）
  - [x] `BusinessToolContext` 支持 `shop_token`/`shop_user_id`，embed 会话工具可读到注入值（`builtin_tool/services.py` 按 `platform_end_user_id` 读取 Redis）
  - [x] `store_ops_query` 已注册；未注入 token 返回 `store_ops_not_authenticated`
  - [x] mock 测试覆盖成功/401 透传/未登录/不可达（11 项）
  - [x] 既有测试无回归（`--import-mode=importlib` 下 146 passed）
  - [x] `apps/shop` 前端可构建
  - [ ] 人工联调（真实 hua8 + Embed 配置）未完成 —— 待用户配置后执行
- 结论：代码层面完成，**未达到最终验收**，待人工联调项完成后闭合。

## 剩余风险

- 真实 hua8 联调与 Embed Client 配置（`EMBED_CLIENT_ID/SECRET/AGENT_ID/ORIGIN`）未完成。
- 目标 Agent 需在管理后台启用 `store_ops_query` 工具绑定。
- 生产部署需反向代理 `/api`（含 WebSocket）与 `/hua8-api`，避免跨域与混合内容问题。
- 店铺 token 过期方案（重新授权引导/续期）为后续设计项，本次按错误原样透传处理。

## 人工验收记录

- 2026-09-02 用户确认：① `apps/shop/` 作为新前端项目目录；② Embed 配置先用现有、后续再配；③ hua8 用户信息接口（`/system/user/getInfo`）存在（记录于 `apps/shop/docs/login-shop.md`），已用于 `shopUserId` 防伪校验。
- 待人工回归：真实登录→提问「查询我的店铺」→返回店铺列表；token 过期后错误原样透传。
