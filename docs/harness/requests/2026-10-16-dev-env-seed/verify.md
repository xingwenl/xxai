---
source: script
request: 2026-10-16-dev-env-seed
ranAt: "2026-10-16 14:27:46 CST"
exitCode: 3
---

## 已执行的命令与结果

### 重置前 conversations 行数（脏状态证据，用于佐证下面确实清了库）

```bash
printf %s\n 1
```

1
结果：通过

### 一条命令重建开发环境：bash apps/backend/scripts/reset_dev_db.sh

```bash
bash apps/backend/scripts/reset_dev_db.sh
```


==> 清空数据库数据（保留 alembic_version，自增序号复位）
DO

==> 清空磁盘派生态 /Users/lixingwen/xw/study/ai-base/apps/backend/storage
/Users/lixingwen/xw/study/ai-base/apps/backend/storage/skill-packages

==> 清空 Redis DB 0（配额计数与事件回放流）
OK

==> 灌入开发环境种子
开发环境种子完成：
  · 平台：开发平台（id=1，code=dev-platform）
  · 管理员：admin / 见 SEED_ADMIN_PASSWORD 或开发默认密码
  · Agent：开发助手（id=1，slug=dev-assistant）
  · 内置工具：ask_user, get_runtime_info, http_get
  · 技能包：dev-sample-skill（slug=dev-sample-skill，2 个文件）
    绑定技能：开发示例技能（slug=skill）
  · MCP 配置：开发样例 MCP（slug=dev-sample-mcp，未同步工具）
  · 工作流：开发助手单步流程（id=1，status=active）
  · Embed Client：client_3-obQ0Bnv4YxM5m3xu7RRaOS

==> 重置完成
结果：通过

### 重置后 conversations 行数为 0（TRUNCATE 生效）

```bash
test 0 = 0
```

结果：通过

### 重置后的种子对象指纹 F1（13 张表计数）

```bash
printf %s\n 1|1|1|1|1|1|2|1|1|1|1|3|1
```

1|1|1|1|1|1|2|1|1|1|1|3|1
结果：通过

### 再跑一次种子脚本（不重置库）：seed 自身幂等

```bash
docker compose run --rm --no-deps -v /Users/lixingwen/xw/study/ai-base/apps/backend/scripts:/app/scripts:ro api python -m scripts.seed_dev_env
```

开发环境种子完成：
  · 平台：开发平台（id=1，code=dev-platform）
  · 管理员：admin / 见 SEED_ADMIN_PASSWORD 或开发默认密码
  · Agent：开发助手（id=1，slug=dev-assistant）
  · 内置工具：ask_user, get_runtime_info, http_get
  · 技能包：dev-sample-skill（slug=dev-sample-skill，2 个文件）
    绑定技能：开发示例技能（slug=skill）
  · MCP 配置：开发样例 MCP（slug=dev-sample-mcp，未同步工具）
  · 工作流：开发助手单步流程（id=1，status=active）
  · Embed Client：client_3-obQ0Bnv4YxM5m3xu7RRaOS
结果：通过

### 单独重跑 seed 后指纹不变：F2 等于 F1

```bash
test 1|1|1|1|1|1|2|1|1|1|1|3|1 = 1|1|1|1|1|1|2|1|1|1|1|3|1
```

结果：通过

### 第二次完整重置：bash apps/backend/scripts/reset_dev_db.sh（输出略，仅比对指纹）

```bash
bash -c bash apps/backend/scripts/reset_dev_db.sh >/dev/null 2>&1
```

结果：通过

### 第二次完整重置后指纹不变：F3 等于 F1（纯仓库可重建，无数据库唯一副本）

```bash
test 1|1|1|1|1|1|2|1|1|1|1|3|1 = 1|1|1|1|1|1|2|1|1|1|1|3|1
```

结果：通过

### 重置后 storage/skill-packages 下的解压目录重新生成

```bash
bash -c ls apps/backend/storage/skill-packages/1/*/ >/dev/null
```

结果：通过

### Redis DB 0 当前键数（reset 已在清库阶段 FLUSHDB；此处仅记录，之后可能有调度锁等新键）

```bash
printf %s\n 0
```

0
结果：通过

### 技能包文件行数 2 等于仓库内技能源文件数 2

```bash
test 2 = 2
```

结果：通过

### Agent 1 绑定的内置工具

```bash
printf %s\n ask_user,get_runtime_info,http_get
```

ask_user,get_runtime_info,http_get
结果：通过

### Agent 1 绑定的是 ask_user / get_runtime_info / http_get 三个

```bash
test ask_user,get_runtime_info,http_get = ask_user,get_runtime_info,http_get
```

结果：通过

### 控制台登录返回 access_token

```bash
test -n eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwiZXhwIjoxNzkyMjE4NDU1fQ.yaKljhJf0_UKM57jgokQBhgO7P-7lj7FH9LQyfE0i3o
```

结果：通过

### GET /api/v1/auth/me 返回种子管理员 admin

```bash
bash -c curl -s http://127.0.0.1:8000/api/v1/auth/me -H 'Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwiZXhwIjoxNzkyMjE4NDU1fQ.yaKljhJf0_UKM57jgokQBhgO7P-7lj7FH9LQyfE0i3o' | grep -q '"account":"admin"'
```

结果：通过

### GET /api/v1/platforms/1/agents 能看到已发布的开发助手

```bash
bash -c curl -s 'http://127.0.0.1:8000/api/v1/platforms/1/agents' -H 'Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwiZXhwIjoxNzkyMjE4NDU1fQ.yaKljhJf0_UKM57jgokQBhgO7P-7lj7FH9LQyfE0i3o' | grep -q 'dev-assistant'
```

结果：通过

### GET /api/v1/platforms/1/skill-packages 能看到种子技能包

```bash
bash -c curl -s 'http://127.0.0.1:8000/api/v1/platforms/1/skill-packages' -H 'Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwiZXhwIjoxNzkyMjE4NDU1fQ.yaKljhJf0_UKM57jgokQBhgO7P-7lj7FH9LQyfE0i3o' | grep -q 'dev-sample-skill'
```

结果：通过

### GET /api/v1/platforms/1/skills 能看到种子技能

```bash
bash -c curl -s 'http://127.0.0.1:8000/api/v1/platforms/1/skills' -H 'Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwiZXhwIjoxNzkyMjE4NDU1fQ.yaKljhJf0_UKM57jgokQBhgO7P-7lj7FH9LQyfE0i3o' | grep -q '开发示例技能'
```

结果：通过

### GET /api/v1/platforms/1/workflows 能看到 active 工作流且带 definition

```bash
bash -c curl -s 'http://127.0.0.1:8000/api/v1/platforms/1/workflows' -H 'Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwiZXhwIjoxNzkyMjE4NDU1fQ.yaKljhJf0_UKM57jgokQBhgO7P-7lj7FH9LQyfE0i3o' | grep -q '"status":"active"' && curl -s 'http://127.0.0.1:8000/api/v1/platforms/1/workflows' -H 'Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwiZXhwIjoxNzkyMjE4NDU1fQ.yaKljhJf0_UKM57jgokQBhgO7P-7lj7FH9LQyfE0i3o' | grep -q '"definition"'
```

结果：通过

### GET /api/v1/platforms/1/mcp-servers 能看到种子 MCP 配置

```bash
bash -c curl -s 'http://127.0.0.1:8000/api/v1/platforms/1/mcp-servers' -H 'Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIiwiZXhwIjoxNzkyMjE4NDU1fQ.yaKljhJf0_UKM57jgokQBhgO7P-7lj7FH9LQyfE0i3o' | grep -q 'dev-sample-mcp'
```

结果：通过

### 启动本地假模型服务（端口 18801）

```bash
bash -c python3 tools/harness/verify/2026-10-16-dev-env-seed.stub-model.py 18801 >/tmp/dev-env-seed-verify/stub.log 2>&1 & echo $! >/tmp/dev-env-seed-verify/stub.pid; sleep 2; curl -s -m 5 -X POST http://127.0.0.1:18801/v1/chat/completions -H 'content-type: application/json' -d '{}' | grep -q chatcmpl-local-stub
```

结果：通过

### 启动指向假模型的临时 API 容器（端口 18001，跳过默认 command 里的 alembic）

```bash
bash -c docker compose run -d --rm --no-deps --name seed-verify-api -p 18001:8000 -e OPENAI_BASE_URL=http://host.docker.internal:18801/v1 -e OPENAI_API_KEY=stub api uvicorn main:app --host 0.0.0.0 --port 8000
```

f1b493144686698689cbaa4e9a79f7dfa25c70fe284c93797f4afaa0e72ac660
结果：通过

### 轮询等临时容器就绪（首次启动约 10 秒）

```bash
bash -c code=000; for _ in $(seq 1 30); do code=$(curl -s -o /dev/null -m 3 -w '%{http_code}' -X POST http://127.0.0.1:18001/api/v1/auth/login -H 'Content-Type: application/json' -d '{"account":"admin","password":"admin123456"}'); [ "$code" = '200' ] && break; sleep 2; done; echo "login=http:$code"; [ "$code" = '200' ]
```

login=http:200
结果：通过

### 种子 Agent 走完一轮对话（POST /api/v1/agents/1/chat，非流式）

```bash
bash -c TOKEN=$(curl -s -X POST http://127.0.0.1:18001/api/v1/auth/login -H 'Content-Type: application/json' -d '{"account":"admin","password":"admin123456"}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["data"]["access_token"])'); RESP=$(curl -s -m 120 -X POST http://127.0.0.1:18001/api/v1/agents/1/chat -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"message":"你好，你是谁？","stream":false}'); echo "$RESP" | head -c 300; echo; echo "$RESP" | grep -q '"success":true' && echo "$RESP" | grep -q '本地假模型应答'
```

{"success":true,"message":"ok","data":{"conversation_id":1,"message_id":2,"content":"本地假模型应答：已收到你的消息。","citations":[],"knowledge_grounded":false,"pending_confirmation_id":null,"content_blocks":[{"id":"answer_markdown","type":"markdown","text":"本地假模型应答：
结果：通过

### 该轮对话里出现了种子技能的注入步骤 skill_instruction（计数 1）

```bash
test 1 -gt 0
```

结果：通过

### python3 tools/harness/audit.py

```bash
python3 tools/harness/audit.py
```


v2 requests: 10  存量跳过: 59  ERROR: 0  WARN: 0
结果：通过

## 未执行项与原因

- 真实模型端点出词：仓库根 .env 指向的 relay（0029.zhongzhuan.wang）账号返回 403 INSUFFICIENT_BALANCE，
  恒失败且不可重复。改用 tools/harness/verify/2026-10-16-dev-env-seed.stub-model.py 本地假模型替代验证，
  业务链路（uvicorn → conversation → agent_runtime → ModelUsageRecord）全部真实，只有最外一跳换成固定应答。
- 浏览器 / 前端页面：本次只验证后端 API 与数据库，未打开 http://localhost:8080 做人工点击；前端是既有代码，本次未改。
- 无人值守任务调度（tasks/cron）与工作流实际执行：种子只创建定义，未触发跑批。

## 验收结论

- 可重建性（验收标准①⑦）：reset 一条命令后 fingerprint 稳定；单独重跑 seed 与第二次完整 reset 后 fingerprint 都不变，
  说明开发环境的状态完全由仓库内的种子脚本 + 技能包源文件决定，数据库里没有唯一副本。
- 登录与鉴权（②）：种子管理员可登录，/auth/me 返回同账号。
- 可对话 Agent（③）：列表可见、default_version_id 指向已发布版本；端到端对话在本地假模型下跑通并落库。
- 技能包（④）：包 / 技能 / 绑定 / 文件清单四者齐全，文件行数与仓库源文件数一致。
- 工作流（⑤）：可见且 status=active，definition 由既有静态校验器生成（见 docs/runbooks/dev-environment.md）。
- Harness 合规（⑥）：audit.py 退出码 0。
- 剩余风险：本脚本会不可逆清空开发库与 storage，仅限开发环境；生产阻断靠 seed_dev_env.py 内的 APP_ENV 检查。
- 待人工确认：仓库根 .env.example 内仍留有真实 EMBED_CLIENT_ID / EMBED_CLIENT_SECRET 与数据库口令，
  这超出本 request 已批准的变更点，需单独排期处理。
