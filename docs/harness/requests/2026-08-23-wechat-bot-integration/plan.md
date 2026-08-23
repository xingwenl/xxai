# 实施计划：集成微信 ClawBot（iLink）机器人服务（MVP）

## 变更文件

- 新增 `docs/harness/requests/2026-08-23-wechat-bot-integration/{research,spec,plan,verify,acceptance}.md` 与 `meta.json`：Harness 闭环文档。
- 修改 `apps/backend/app/core/config.py`：新增 `wechat_bot_enabled`、`wechat_bot_system_prompt`、`wechat_bot_max_reply_chars` 三个配置项。
- 新增 `apps/backend/app/modules/wechat_bot/__init__.py`、`agent_bridge.py`、`worker.py`：落实 `research.md` 方案 A 的核心实现。
- 新增 `apps/backend/tests/wechat_bot/__init__.py`、`test_agent_bridge.py`：单元测试。
- 新增 `apps/backend/Dockerfile.wechat-bot`：在现有后端依赖基础上内置 `wechatbot-sdk`。
- 修改根 `docker-compose.yml`：新增 `wechat-bot-worker` 服务（单实例）。

## 实施步骤

1. `research.md` 已完成（2026-08-23），`spec.md` 与 `plan.md` 本次补齐。
2. 修改 `config.py`，新增三个微信机器人配置项（默认关闭，保证不影响现有服务）。
3. 实现 `agent_bridge.py`：复用 `ProviderThinkingChatOpenAI` + `run_graph`，无工具、无落库，输出纯文本并做超长截断。
4. 实现 `worker.py`：懒加载 `wechatbot-sdk`，注册 `on_message` 处理器（`generate_reply` → `bot.reply`），异常时发送兜底回复。
5. 新增 `Dockerfile.wechat-bot` 与 `docker-compose.yml` 的 `wechat-bot-worker` 服务。
6. 新增单元测试（FakeModel 注入，不依赖真实模型与 SDK）。
7. 执行测试与配置校验，更新 `verify.md`、`acceptance.md`、`meta.json`。

## 测试步骤

- `cd apps/backend && poetry run pytest tests/wechat_bot -q`：预期全部通过。
- `cd apps/backend && poetry run pytest tests/conversation/test_runtime.py -q`：预期无回归。
- `cd apps/backend && python -m compileall -q app/modules/wechat_bot`：预期无语法错误。
- `cd /Users/lixingwen/xw/study/ai-base && docker compose config`：预期包含 `wechat-bot-worker` 且解析成功。
- 人工联调（需真实微信账号 + 模型密钥，AI 无法自动执行）：
  - 设置 `WECHAT_BOT_ENABLED=true`、`OPENAI_API_KEY`（或对应模型密钥）；
  - `docker compose up --build wechat-bot-worker`（或本地 `pip install wechatbot-sdk` 后 `python -m app.modules.wechat_bot.worker`）；
  - 控制台输出扫码链接，用手机微信扫码确认登录；
  - 向该微信发送文字消息，验证收到纯文本 AI 回复。
  - 登录状态持久化：首次扫码登录后重启容器（`docker compose restart wechat-bot-worker`），
    控制台不再要求扫码、直接进入长轮询；向该微信再发消息验证仍能收到回复（同时验证游标恢复后不重复回复旧消息）。
  - 后台智能体绑定：在 `.env` 设置 `WECHAT_BOT_AGENT_ID=<后台智能体 ID>` 后
    `docker compose up -d --build wechat-bot-worker`，向该微信发消息验证回复风格与智能体人设一致；
    故意设置一个不存在的 ID 验证回复「后台智能体未找到或未发布」提示。

## 回滚说明

- 删除 `docker-compose.yml` 中的 `wechat-bot-worker` 服务与 `apps/backend/Dockerfile.wechat-bot`。
- 删除 `apps/backend/app/modules/wechat_bot/` 目录与 `apps/backend/tests/wechat_bot/` 目录。
- 从 `apps/backend/app/core/config.py` 移除新增的三个配置字段（与旧 `Settings` 保持一致）。
- 删除 `apps/backend/data/wechat_bot/`（登录凭证与游标状态）、`docker-compose.yml` 中 `wechat-bot-worker`
  的 `WECHAT_BOT_STATE_DIR` 环境变量与数据卷挂载、`.gitignore` 中对应忽略项。
- 本 request 不涉及数据库迁移，无需数据回滚。

## 人工确认点

- 已确认（2026-08-23）：方案 A（wechatbot-sdk + 独立 worker）、单账号 MVP、不落库、docker-compose 单实例部署。
- 待用户执行：扫码联调（需真实微信账号，无法自动化验证）。

## 变更记录

### 2026-08-23 第 3 次变更

- 变更原因：用户要求通过智能体 ID 把微信机器人对话模型配置为后台已建好的智能体。
- 变更内容：
  - `AgentRepository.get_published_agent_by_id()`：服务端内部按 ID 加载已发布智能体（不限定平台）；
  - `agent_bridge.py`：配置 `WECHAT_BOT_AGENT_ID` 时用智能体发布版本的模型与人设对话，否则退回默认模型；
  - `docker-compose.yml`：透传 `WECHAT_BOT_AGENT_ID`，新增 `depends_on: db`。
- 影响实施方式：联调前需在 `.env` 配置 `WECHAT_BOT_AGENT_ID`；加载智能体需数据库可用。
- 影响测试步骤：自动校验新增智能体分支用例；人工联调新增「配置 ID 验证人设 / 配置不存在 ID 验证提示」两步。
- 影响回滚说明：回滚时移除 `WECHAT_BOT_AGENT_ID` 透传与 `agent_bridge.py` 的智能体分支即可恢复默认模型行为。

### 2026-08-23 第 2 次变更

- 变更原因：用户要求登录状态持久化，避免反复扫码测试。
- 变更内容：
  - `worker.py` 使用 `WeChatBot(cred_path=...)` 持久化 `bot_token`（SDK 原生支持），重启免扫码；
  - 新增 `session.py` 持久化长轮询游标 `get_updates_buf`，防止重启后重复拉取已消费消息；
  - `config.py` 新增 `WECHAT_BOT_STATE_DIR`（默认 `apps/backend/data/wechat_bot`）；
  - `docker-compose.yml` 将 `apps/backend/data/wechat_bot` 挂载为容器 `/app/data/wechat_bot`；
  - `.gitignore` 忽略该目录（含敏感 `bot_token` 凭证）。
- 影响实施方式：重启验证步骤改为「先 `docker compose up -d --build wechat-bot-worker` 重建，再
  `docker compose restart wechat-bot-worker` 验证免扫码」。
- 影响测试步骤：自动校验新增 `test_session.py`（游标读写与轮询包装），预期 `tests/wechat_bot` 全绿（6 个用例）。
- 影响回滚说明：回滚时同时删除状态目录、`WECHAT_BOT_STATE_DIR` 配置、数据卷挂载与 `.gitignore` 忽略项。

### 2026-08-23 第 1 次变更（fix）

- 变更原因：容器内 worker 无法访问宿主机模型网关（`127.0.0.1:8800` 在容器内指向容器自身），模型调用全部连接失败。
- 变更内容：
  - `docker-compose.yml` 的 `wechat-bot-worker` 增加 `extra_hosts: ["host.docker.internal:host-gateway"]`；
  - `OPENAI_BASE_URL` 默认改为 `http://host.docker.internal:8800/v1`，可用 `WECHAT_BOT_OPENAI_BASE_URL` 覆盖；
  - `worker.py` 启动时打印模型 `base_url` / `model`，模型连接失败时回复明确提示。
- 影响实施方式：重新联调需 `docker compose up --build wechat-bot-worker` 重建镜像（仅环境变量变化时也可 `docker compose up -d` 重建容器）。
- 影响测试步骤：自动校验不变（ruff / compileall / compose config）；端到端联调由用户重跑验证。
- 影响回滚说明：回滚时同时移除 `extra_hosts` 与 `OPENAI_BASE_URL` 覆盖即可恢复原默认行为。
