---
source: script
request: 2026-10-19-token-endpoint-hardening
ranAt: "2026-10-19 13:14:40 CST"
exitCode: 3
---

## 已执行的命令与结果

### 后端单测：tests/embed（AC6）

```bash
step_embed_tests
```

........................                                                 [100%]
24 passed in 3.96s
结果：通过

### 后端单测：tests/auth（AC6）

```bash
step_auth_tests
```

...........                                                              [100%]
11 passed in 2.74s
结果：通过

### 结构断言：/api/agent-token 已挂登录态依赖（变更点 1）

```bash
step_route_requires_auth
```

token_router.py 中 require_current_active_user 出现次数：2
结果：通过

### 结构断言：生产环境忽略 external_user_id 覆盖（变更点 1）

```bash
step_production_guard
```

32:    if external_user_id and settings.app_env != "production":
结果：通过

### 结构断言：示例页不再出现 client_secret（AC4）

```bash
step_no_client_secret
```

demo/ 与根 index.html 中 client_secret 命中数：0
结果：通过

### 结构断言：示例页一律走同源 /demo-api/agent-token（AC5）

```bash
step_no_direct_embed_tokens
```

直连 embed/tokens 命中数：0；直连 /api/agent-token 命中数：0；走同源代理的页面数：4
结果：通过

### 端到端：无登录态请求 /api/agent-token 返回 401（AC1）

```bash
step_401_without_auth
```

无登录态状态码：401
响应：{"success":false,"message":"not authenticated","data":null,"meta":null,"code":401,"error_code":null}
结果：通过

### 端到端：登录态 + 非生产覆盖生效，sub 指向该终端用户（AC2）

```bash
step_token_with_auth
```

带登录态 + external_user_id=probe-override 状态码：200
token sub=68；platform_end_users.id(external_user_id=probe-override)=68
结果：通过

### 回归：既有受鉴权端点 /api/v1/embed/agent-token 仍可用（变更点 2）

```bash
step_embed_agent_token_still_works
```

GET /api/v1/embed/agent-token 状态码：200
结果：通过

### 端到端：vite dev server 同源 token 代理（变更点 3-5，AC4/AC5 的运行期验证）

```bash
python3 tools/harness/verify/2026-10-19-token-endpoint-hardening.probe.py
```

启动 vite dev server：端口 52901，日志 /tmp/token-endpoint-hardening-vite.log
通过：dev server 就绪（/demo/index.html 返回 200）
通过：同源代理 POST /demo-api/agent-token 返回 200 且带 access_token —— status=200 body={"success":true,"message":"embed token issued","data":{"access_token":"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJhaS1iYXNlIiwiYXVkIjoiYWdlbnQtZW1iZWQiLCJzdWIiOiI2OSIsInBsYXRmb3JtX2lkIjoxLCJhZ2Vu
（已取回 token，长度 508，未打印内容）
通过：同源代理拒绝非 POST（405） —— status=405 body={"message":"只支持 POST"}
通过：缺少可用 agent_id 时返回 400 —— status=400 body={"message":"缺少可用的 agent_id（页面入参或 EMBED_AGENT_ID）"}
探针全部通过
结果：通过

### SDK 类型检查：vue-tsc --noEmit

```bash
step_type_check
```


> xxai-agent@0.2.0 type-check
> vue-tsc --noEmit

结果：通过

### SDK 单测：npx vitest run src（21 文件 / 172 用例，AC6）

```bash
step_sdk_unit
```


 Test Files  21 passed (21)
      Tests  172 passed (172)
   Start at  13:14:38
   Duration  1.87s (transform 1.07s, setup 0ms, collect 2.36s, tests 354ms, environment 739ms, prepare 2.26s)

结果：通过

### Harness 自检：audit.py（AC7）

```bash
step_audit
```


v2 requests: 15  存量跳过: 59  ERROR: 0  WARN: 0
除本 request 的「缺少 verify.md」（由 verify.sh 产出，属预期）外无 ERROR
结果：通过

## 未执行项与原因

- AC3（`APP_ENV=production` 时忽略 `external_user_id` 覆盖）：用单测覆盖（`apps/backend/tests/embed/test_token_routes.py` 直接 monkeypatch `app_env`），
  未起第二个生产模式进程做端到端；切换 `APP_ENV` 需要另起容器，收益低于单测。
- `pnpm --dir apps/ai-sdk test`（整包 vitest）会连带 `scripts/verify-package.test.mjs` 的**预存在环境性失败**：
  该用例用 `npm pack --dry-run --json` 取包清单后直接 `JSON.parse`，而 `prepare` 脚本的 vite build 日志
  与 JSON 同走 stdout，导致 `SyntaxError: Unexpected token 'v', "vite v5.4."...`。与本次改动无关，
  故本轮只跑 `npx vitest run src`（21 文件 / 172 用例）。
- 浏览器人工点检：dev 代理已由真进程探针覆盖（200 / 405 / 400 三条），未做浏览器点击。
- `alembic check`：本仓存在大量**预存在**漂移，且本轮无迁移，未执行。
- 生产环境的 nginx / 端口暴露面（`apps/front/nginx.conf:11`、`docker-compose.yml:129`）：属部署配置，未做渗透式验证。

## 验收结论

| 验收标准 | 结果 |
| --- | --- |
| 1. 无登录态 → 401 | 端到端 curl 通过（实测 401） |
| 2. 登录态 + 非生产覆盖：token sub 指向该终端用户 | 端到端 curl + DB 比对通过 |
| 3. 生产环境忽略覆盖 | 单测通过；端到端未执行（见上） |
| 4. demo/index.html 无 client_secret | 结构断言通过（0 命中） |
| 5. demo/index.html 不直连 /api/v1/embed/tokens | 结构断言 + dev 代理探针通过（4 个页面走同源） |
| 6. tests/embed、tests/auth 全绿；vitest 21/172 全绿 | 已执行，全部通过 |
| 7. audit.py ERROR 为 0 | 除本 request 缺 verify.md（预期）外无 ERROR |
