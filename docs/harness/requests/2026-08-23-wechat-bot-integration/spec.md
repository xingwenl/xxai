# 设计说明：集成微信 ClawBot（iLink）机器人服务（MVP）

## 目标

- 在 `ai-base` 后端新增微信机器人接入能力：微信用户向已绑定的个人微信号发送文字消息，独立的 worker 进程把消息送入后端默认模型对话链路，生成纯文本回复并回传到微信会话。
- 目标用户：单个微信个人号（单账号 MVP）；调用方为本项目后端内部 worker，不新增外部 HTTP API。
- 完成后应产生的可验证结果：启动 `wechat-bot-worker` 后控制台输出扫码登录链接；扫码登录后向该微信发送文字消息可收到纯文本 AI 回复。
- 引用 `research.md` 的关键结论：
  - 运行环节不依赖 OpenClaw，仅开通（扫码获取 `bot_token`）走官方入口；
  - 选定方案 A：社区 Python SDK `wechatbot-sdk` + 后端独立 asyncio worker；
  - 协议硬约束：单账号单实例轮询、回复必须回传 `context_token`（SDK 处理）、只能被动回复、纯文本输出。

## 范围

- 新增模块 `apps/backend/app/modules/wechat_bot/`：
  - `agent_bridge.py`：对话桥接——优先按 `WECHAT_BOT_AGENT_ID` 加载后台智能体发布版本
    （模型、密钥、人设提示词），未配置时退回默认模型；负责生成纯文本回复与超长截断；
  - `worker.py`：worker 入口，注册 `on_message` 处理器并启动长轮询。
  - `session.py`：登录状态持久化辅助（长轮询游标写盘；`bot_token` 由 SDK 原生写入 `credentials.json`）。
- 修改 `apps/backend/app/core/config.py`，新增配置项（环境变量）：
  - `WECHAT_BOT_ENABLED`（默认 `false`，关闭时 worker 直接退出）；
  - `WECHAT_BOT_SYSTEM_PROMPT`（默认微信助手提示词，要求纯文本输出）；
  - `WECHAT_BOT_MAX_REPLY_CHARS`（默认 4000，超长截断并提示）。
  - `WECHAT_BOT_STATE_DIR`（默认 `apps/backend/data/wechat_bot`，登录凭据与游标状态目录）。
  - `WECHAT_BOT_AGENT_ID`（默认空，配置后台智能体 ID 后按该智能体对话）。
- 新增部署单元：
  - `apps/backend/Dockerfile.wechat-bot`：基于现有后端依赖镜像，额外 `pip install wechatbot-sdk`；
  - 根 `docker-compose.yml` 新增 `wechat-bot-worker` 服务（单实例），并将 `apps/backend/data/wechat_bot` 挂载为容器内 `/app/data/wechat_bot`，实现重启免扫码。
- 新增测试：`apps/backend/tests/wechat_bot/test_agent_bridge.py`。
- 文档：本 request 的 `research.md`、`spec.md`、`plan.md`、`verify.md`、`acceptance.md`、`meta.json`。

## 非目标

- 不落库：不新增微信消息、会话数据表，不接入现有 `conversation` 持久化链路；登录状态以本地 JSON 文件持久化（非数据库）。
- 不接智能体完整运行时：绑定后台智能体仅复用其发布版本的模型与系统提示词，不读取知识库、技能、MCP/内置工具绑定（`load_runtime_context()` 完整链路留待后续）。
- 未配置 `WECHAT_BOT_AGENT_ID` 时使用项目默认模型配置（`MODEL_DEFAULT_NAME` 等）完成单轮对话。
- 不支持媒体消息（图片/语音/文件）、群消息、主动推送、Markdown 渲染与流式输出。
- 不实现多账号、不部署 OpenClaw 网关、不新增对外 HTTP 接口。
- 不修改 `poetry.lock`（wechatbot-sdk 仅在 worker 镜像内单独安装，避免影响现有镜像构建）。

## 风险

- 依赖社区 SDK：`wechatbot-sdk` 的 API 以文档为准，若与真实包有出入，需在人工扫码联调时修正（SDK 安装仅在 `Dockerfile.wechat-bot` 内进行，不影响主镜像）。
- 平台侧限制：微信 ClawBot 只能被动回复（对方 24 小时内主动发过消息）；腾讯保留限速、拦截与终止权利，长期可用性存在平台侧风险。
- 凭证安全：`bot_token` 属于账号级敏感凭证，MVP 由 SDK 管理，写入 `WECHAT_BOT_STATE_DIR/credentials.json`（权限 0600），该目录已加入 `.gitignore` 禁止提交；不落库、不入日志。
- 消息链路：`get_updates_buf` 游标互相覆盖会丢消息，worker 必须单实例运行（compose 只部署一个副本）。

## 停点判断

- 是否涉及架构边界变化：是（新增外部集成模块与独立 worker 进程）→ 已获用户确认（2026-08-23）
- 是否涉及数据模型变化：否（MVP 不落库）
- 是否涉及 API 契约变化：否（不新增 HTTP API，仅新增 worker 与配置项）
- 是否涉及鉴权或权限行为变化：是（引入 `bot_token` / `context_token` / 登录状态管理，由 SDK 封装）→ 已获用户确认（2026-08-23）
- 结论：进入实现前需人工确认 —— 已完成，用户按推荐方案确认（方案 A、单账号、不落库、docker-compose 单实例）。

## 验收标准

- [ ] `docker compose config` 可正常解析，包含 `wechat-bot-worker` 服务；`WECHAT_BOT_ENABLED=false` 时不影响现有服务启动。
- [ ] 新增单元测试通过：`poetry run pytest tests/wechat_bot -q` 全绿。
- [ ] 相关既有测试无回归：`poetry run pytest tests/conversation/test_runtime.py -q` 全绿。
- [ ] 模块语法检查通过：`python -m compileall -q app/modules/wechat_bot`。
- [ ] 人工联调（需真实微信账号，记录在 `verify.md`）：设置 `WECHAT_BOT_ENABLED=true` 与模型密钥后运行 worker，控制台输出扫码链接；扫码登录后发送文字消息能收到纯文本回复。
- [ ] 登录状态持久化：首次扫码登录后重启 `wechat-bot-worker` 容器，控制台不再要求扫码，直接复用本地 `bot_token` 进入长轮询。
- [ ] 后台智能体绑定：设置 `WECHAT_BOT_AGENT_ID` 为已发布智能体 ID 后，微信回复使用该智能体的模型与系统提示词；未发布/不存在时回复明确提示。

## 变更记录

### 2026-08-23 第 3 次变更

- 变更原因：用户要求微信机器人对话模型可配置为后台已建好的智能体（通过智能体 ID 获取）
- 变更内容：
  - `config.py` 新增 `WECHAT_BOT_AGENT_ID`（可选整数，默认空）；
  - `AgentRepository` 新增 `get_published_agent_by_id()`（服务端内部按 ID 加载已发布智能体，不限定平台）；
  - `agent_bridge.py` 优先用智能体发布版本的模型（`build_chat_model`，含解密 API Key）与人设提示词对话，
    智能体不存在/未发布时回复明确提示；未配置时退回默认模型；
  - `docker-compose.yml` 的 `wechat-bot-worker` 透传 `WECHAT_BOT_AGENT_ID` 并新增 `depends_on: db`（加载智能体需访问数据库）。
- 影响章节：范围（`agent_bridge.py` 职责与新增配置）、非目标（不接完整运行时）、验收标准（新增智能体绑定验收项）
- 是否触发人工确认：否（用户明确要求绑定后台智能体；未新增表结构、HTTP API 或鉴权逻辑，读取智能体密钥复用现有 `AGENT_MASTER_KEY` 解密链路）
- 关联计划更新：已同步更新 `verify.md` 验证记录与 `plan.md` 测试步骤

### 2026-08-23 第 2 次变更

- 变更原因：补充需求（用户要求登录状态持久化，方便反复测试时免扫码）
- 变更内容：
  - `worker.py` 通过 `WeChatBot(cred_path=...)` 让 SDK 将 `bot_token` 持久化到状态目录，
    重启后自动复用本地凭证，无需重新扫码；
  - 新增 `session.py`：持久化 `get_updates_buf` 长轮询游标，避免重启后重复拉取已消费消息；
  - `config.py` 新增 `WECHAT_BOT_STATE_DIR`；`docker-compose.yml` 的 `wechat-bot-worker`
    挂载 `apps/backend/data/wechat_bot` 数据卷；`.gitignore` 忽略该目录（含敏感凭证）。
- 影响章节：范围（新增 `session.py`、状态目录配置与数据卷）、非目标（不落库说明）、风险（凭证存储安全）、验收标准（新增重启免扫码验收项）
- 是否触发人工确认：否（用户已明确指示持久化；属原批准范围内「登录状态管理」的落地，未新增架构/API/数据库边界）
- 关联计划更新：已同步更新 `verify.md` 验证记录

### 2026-08-23 第 1 次变更（fix）

- 变更原因：人工联调发现容器内模型调用失败（`openai.APIConnectionError`，所有连接尝试失败）
- 变更内容：
  - `docker-compose.yml` 的 `wechat-bot-worker` 增加 `extra_hosts`（`host.docker.internal:host-gateway`），
    并将 `OPENAI_BASE_URL` 默认改为 `http://host.docker.internal:8800/v1`（可用 `WECHAT_BOT_OPENAI_BASE_URL` 覆盖），
    解决容器内访问宿主机模型网关（原 `127.0.0.1:8800` 指向容器自身）不可达的问题；
  - `worker.py` 启动日志输出实际模型 `base_url` 与 `model`，便于诊断；
  - 模型连接失败时回复明确提示，替代笼统兜底文案。
- 影响章节：范围（部署配置）、风险、验收标准
- 是否触发人工确认：否（仅为部署环境变量与提示优化，未改变架构、数据模型、API 契约或鉴权逻辑）

### 初始版本

- 时间：2026-08-23
- 变更原因：首次创建 request（`/new` 集成微信 ClawBot 服务）
- 变更内容：建立 MVP 设计说明（方案 A、单账号、不落库、独立 worker）
- 影响章节：全部
- 是否触发人工确认：是（架构边界 + 鉴权行为变化），用户于 2026-08-23 按推荐确认
