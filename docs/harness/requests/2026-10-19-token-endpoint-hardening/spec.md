---
id: 2026-10-19-token-endpoint-hardening
tier: B
risk: high
approval:
  required: true
  granted: true
  grantedAt: 2026-10-19
  grantedBy: 用户
  grantedNote: "停点确认：按 spec 范围实现；/api/agent-token 加后台登录态 + 生产禁覆盖 external_user_id；demo 改为 vite dev server 同源代理，不再由浏览器直连 /api/v1/embed/tokens。"
  why: ["鉴权或权限行为变化：GET /api/agent-token 由「无鉴权、可为任意 external_user_id 签发 token」改为「必须后台登录态；生产环境禁止覆盖 external_user_id」", "API 契约变化：该端点在无登录态时从 200 变为 401；`demo/` 示例页的取 token 方式由「浏览器直连 /api/v1/embed/tokens 并携带 client_secret」改为同源 dev 代理"]
---

# 无鉴权 token 端点与 demo 凭据泄漏收口

## 目标与范围

目标：把「任何人可签发他人身份 token」和「示例代码教人把 `client_secret` 放进浏览器」这两处凭据风险收口——`apps/backend/app/modules/embed/token_router.py:12` 的 `GET /api/agent-token` 目前**没有任何鉴权依赖**（无 `Depends`），直接用服务端 `EMBED_CLIENT_ID`/`EMBED_CLIENT_SECRET`（`apps/backend/app/core/config.py:242-243`）为目标 agent 签发 embed token，`external_user_id` 完全由查询参决定；`apps/backend/app/__init__.py:101` 把它挂在 `/api`（不在 `/api/v1`），但 `apps/front/nginx.conf:11` 的 `location /api/` 会照常反代，`docker-compose.yml:129` 的 api 端口默认对外暴露。

范围外：不改 embed token 的签发逻辑与 TTL；不改 MCP/工具审批；不改配额；不引入新的登录方式；不动 `POST /api/v1/embed/tokens`（服务端对服务端的正规入口，仍按 `client_id + client_secret` 鉴权）；不做 ⑤ 之前的 ③b。

受影响面：`apps/backend/app/modules/embed/{token_router.py,router.py}`、`apps/backend/tests/embed/**`、`apps/ai-sdk/demo/*.html`、`apps/ai-sdk/index.html`、`apps/ai-sdk/vite.config.ts`、`apps/ai-sdk/README.md`。

## 来源与方案比较

- **本仓既有的正解**（第一手）：`apps/ai-sdk/README.md:16` 明确「`client_secret` 是长期服务端凭据，只能保存在接入项目的服务端……不能写入前端代码、前端环境变量、SDK 配置、浏览器 Local Storage 或 URL」，`:123` 进一步写「当前版本没有『浏览器直接使用 `client_secret` 换 token』的安全用法」——但 `apps/ai-sdk/demo/index.html:106` 与 `apps/ai-sdk/demo/custom-component.html:94` 正是被否决的那种写法（`client_secret: 'client_secret'` 占位符直连 `/api/v1/embed/tokens`）。文档与示例互相矛盾，示例会被复制粘贴，因此示例本身是要修的对象。
- **OAuth 2.0 for Browser-Based Apps（draft-ietf-oauth-browser-based-apps）**：公共客户端**不得**持有客户端密钥；需要「后端代持密钥、浏览器只拿短期凭据」的 BFF 形态。调研日期 2026-10-19（本机离线，依据既有认知，未联网核实版本号）。
- **RFC 8252 §8.5（OAuth 2.0 for Native Apps）**：原生/桌面客户端内嵌密钥是反模式，与 README.md:811 对桌面端的表述一致。
- 候选方案（针对端点的处置）：
  1. **加登录态 + 生产禁覆盖**（选定）：保留路径与 query 语义，加 `Depends(require_current_active_user)`（`apps/backend/app/core/security.py`，`apps/backend/app/modules/embed/router.py:186` 已有同款用法）；`external_user_id` 覆盖仅在 `settings.app_env != "production"`（`apps/backend/app/core/config.py:213`）时生效，生产强制等于当前登录用户 id。收益：本地 demo 的多身份联调不消失，生产不再有越权面；成本：端点多一个分支。
  2. **直接删除路由**：本地 demo 一律改用 `/api/v1/embed/agent-token`（已存在且要求登录态）。收益：最少代码；限制：该端点把 `external_user_id` 强制绑成 `current_user.id`（`apps/backend/app/modules/embed/router.py:197`），无法再模拟不同终端用户，demo 的「多 end_user」场景被砍掉。
  3. **加 `DEV_AGENT_TOKEN_ENABLED` 显式开关**：默认关闭、`APP_ENV=production` 时硬拒。收益：语义最直白；限制：多一个配置项，且「开发时忘记开」与「生产时误开」两种失败模式都真实存在。
- 候选方案（针对 demo 的取 token 方式）：
  1. **同源 dev 代理**（选定）：在 `apps/ai-sdk/vite.config.ts` 加 dev-only middleware，页面只请求同源 `/demo-api/agent-token`，由 dev server 用**开发者 shell 的环境变量**转发到 `/api/v1/embed/tokens`。收益：secret 不出现在 HTML/仓库/浏览器网络面板以外的任何地方，且示例与 README 描述一致；限制：仅在 `npm run demo`/dev server 下可用（本来也只是本地演示）。
  2. **手工粘贴短期 token**：删掉页面里的取 token 代码，改成一个输入框。收益：零后端改动；限制：10 分钟过期，每次重连都要重贴，示例变成了负担。

## 被否决的选项

- **保留无鉴权的 `GET /api/agent-token`（原样不动）**：否决。它等于把「用服务端长期凭据为任意 `external_user_id` 签发 token」的能力开放给任何能访问 api 端口的人；`apps/front/nginx.conf:11` 与 `docker-compose.yml:129` 都让它可达，风险与「本地 demo 方便」不成比例。
- **删除路由 + 同时给 `/api/v1/embed/agent-token` 放开 `external_user_id`**：否决。为了让 demo 保留多身份，把原来只在无鉴权端点上的越权能力搬到**受鉴权**端点上，等于把洞从一个门挪到另一个门，只是门槛变高。
- **给 demo 页面注入 `client_secret` 的构建期占位替换**：否决。仍然是「密钥进浏览器」，只是从硬编码字面量变成构建产物的字面量，`apps/ai-sdk/scripts/verify-package.mjs:24` 已经把 `client_secret=` 列为发布包禁词，说明这条线不能碰。
- **只在 README 里加强警告、不改 demo 代码**：否决。缺陷是「文档否决了示例正在做的事」，只改文档等于把矛盾留在示例里，下一个接入方照样复制。
- **给 `/api/agent-token` 加限流代替鉴权**：否决。限流降低滥用速率但不改变「无需登录即可冒充任意终端用户」的性质；本仓也还没有通用限流（此前已记为缺口）。
- **把端点整个挪到 `/api/v1` 并靠「不在文档里」当安全**：否决。安全不能依赖未文档化，端点已存在于对外可达路径（`apps/backend/tests/embed/test_token_routes.py:25` 就在断言它在 `/api/agent-token`）。
- **本轮顺带补全平台通用限流 / API key 模式**：否决。两者都是独立能力（各自的鉴权、配额、审计面），塞进凭据收口会让本轮无法收敛。

## 停点判断

- 是否涉及架构边界变化：否。
- 是否涉及数据模型变化：否（不碰 `**/models.py`、不写迁移）。
- 是否涉及 API 契约变化：**是**——无登录态时 `GET /api/agent-token` 由 200 改为 401；生产环境下 `external_user_id` 覆盖失效。
- 是否涉及鉴权或权限行为变化：**是**。
- 命中 → `approval.required: true`，实现前须用户确认。

## 变更点

1. `apps/backend/app/modules/embed/token_router.py`：加 `current_user=Depends(require_current_active_user)`；`external_user_id` 改为 `str | None` 查询参，仅当 `settings.app_env != "production"` 时采用调用方传入值，否则 `str(current_user.id)`；`display_name` 缺省回落 `current_user.name`；docstring 明说「生产环境不接受覆盖」。
2. `apps/backend/app/modules/embed/router.py`：`/embed/agent-token` 与新行为去重（两者共用同一个 service）；确认无需改 `issue_configured_agent_token` 本身（`apps/backend/app/modules/embed/services.py:112`）。
3. `apps/ai-sdk/vite.config.ts`：新增 dev-only middleware（`apply: 'serve'`），把同源 `POST /demo-api/agent-token` 用环境变量 `EMBED_CLIENT_ID`/`EMBED_CLIENT_SECRET`/`EMBED_AGENT_ID`/`EMBED_ORIGIN` 转发到 `${AGENT_API_BASE:-http://127.0.0.1:8000}/api/v1/embed/tokens`，缺失环境变量时返回 400 并说明如何设置。
4. `apps/ai-sdk/demo/index.html`、`apps/ai-sdk/demo/custom-component.html`：`getToken` 改为请求同源 `/demo-api/agent-token`，删除页面里的一切 `client_id`/`client_secret` 字面量。
5. `apps/ai-sdk/demo/h5.html`、`apps/ai-sdk/index.html`：改用同一个 dev 代理（不再直连 `/api/agent-token`）。
6. `apps/ai-sdk/README.md`：本地 Demo 一节改写（dev 代理需要哪些环境变量、为什么 secret 不进页面）；`:25`/`:116` 与 `/api/agent-token` 有关的说明同步。
7. `apps/backend/tests/embed/test_token_routes.py`：新增「无登录态 → 401」「有登录态且非生产 → 采用传入 external_user_id」「登录态 + `APP_ENV=production` → 强制为 current_user.id」三例；既有两条路由断言保留。
8. `apps/ai-sdk/scripts/verify-package.mjs`：确认禁词表已覆盖 demo 场景（无需放宽）。
9. 验证脚本 `tools/harness/verify/2026-10-19-token-endpoint-hardening.sh`：结构断言（demo 里无 `client_secret`/`embed/tokens` 直连、后端路由签名含登录依赖）+ 真进程探针（未登录 401；登录取 token 后能用该 token 建 WS 连接）。

## 验收标准

1. `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/api/agent-token?external_user_id=x` 返回 401（当前返回 200）。
2. 带后台登录态请求同一端点（`APP_ENV=development`）返回 200，且 token 的 `sub` 等于 `platform_end_users.external_user_id = <传入值>` 那一行的 id（该端点签发的 `sub` 是终端用户主键，不是传入的原始字符串）。
3. 以 `APP_ENV=production` 起进程时，即使传入 `external_user_id=999`，token 的 `sub` 仍等于当前登录用户对应的终端用户行（由单测覆盖，verify 脚本记为未执行项）。
4. `grep -rn "client_secret" apps/ai-sdk/demo apps/ai-sdk/index.html` 零命中（README 与 `scripts/verify-package.mjs` 的禁词表除外）。
5. `grep -rn "api/v1/embed/tokens" apps/ai-sdk/demo apps/ai-sdk/index.html` 零命中（改为同源 `/demo-api/agent-token`）。
6. `apps/backend/tests/embed`、`apps/backend/tests/auth` 全绿；`npx vitest run src`（`apps/ai-sdk`）保持 21 文件 / 172 用例全绿。
7. `python3 tools/harness/audit.py` 的 ERROR 为 0（本 request 的「缺少 verify.md」属预期，由 `tools/harness/verify.sh` 产出后消失）。
