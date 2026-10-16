---
id: 2026-10-16-model-registry-unification
tier: A
risk: high
approval:
  required: true
  granted: true
  grantedAt: 2026-10-16
  grantedBy: 用户
  grantedNote: 用户确认「两个都开工」，本 spec 与 ADR 0008 定稿后进入实现。
  why: ["数据模型变化：agent_versions 需要去掉模型三要素或改语义", "API 契约变化：Agent 版本创建与读取的模型字段变化", "架构边界变化：对话主模型解析收口到 model_registry"]
---

## 目标与范围

- 目标：把「对话主模型」并入平台模型注册表，让模型名、服务地址、密钥、启用状态各只有一处定义；`agent_versions` 只保留随版本变化的采样与能力参数。
- 现状（逐条可核对）：对话轨把模型三要素内联在版本行 —— `apps/backend/app/modules/agent/models.py:103` `model_name`（`String(120)` NOT NULL）、`:106-108` `model_base_url`、`:109-111` `api_key_encrypted`；注册表轨是 `platform_models`（`apps/backend/app/modules/model_registry/models.py:36-41` 的 `model_type` comment 原文含 `chat/image_generate/image_read/embedding`）与 `agent_model_bindings`（`:98-103` `role` comment 原文「能力角色：image_generate/image_read/embedding」），且 `apps/backend/app/modules/model_registry/schemas.py:19-24` 的 `BindingRole` docstring 原文「Agent 可绑定的能力角色，主对话模型不在此列。」→ `ModelType.CHAT` 是**无消费者的死枚举值**（前端 `apps/front/src/api/model-registry.ts:3-8` 的 `MODEL_TYPES` 里也含 `'chat'`）。
- 注册表解析入口唯一：`apps/backend/app/modules/model_registry/resolver.py:29 resolve_agent_model(session, *, platform_id, agent_id, role) -> ResolvedModel | None`（`:19-27` `ResolvedModel{model_name,base_url,api_key,capabilities,options}`）；现有调用点 role 全为辅助角色 —— `image_generate`（`tools/business/image_generate.py:74-78`）、`image_read`（`tools/business/image_read.py:139-143`）、`embedding`（`tools/business/attachment_search.py:176-180`、`asset_processing/services.py:244-250`、`gateway/runtime.py:162-167`）。
- 对话模型构造入口唯一：`apps/backend/app/modules/agent/services.py:298-357 build_chat_model(version, *, session_id_provider=None, thinking=None) -> ChatOpenAI`，只读 `version` 的 `model_name/model_base_url/api_key_encrypted/model_options/temperature`，且 **`api_key` 没有 `settings.openai_api_key` 兜底**；调用点共 4 处：`conversation/router.py:107`、`conversation/router.py:187`、`conversation/services.py:1189`、`gateway/router.py:726`。
- 双轨是当时的显式决定，不是遗漏：`docs/harness/requests/2026-08-27-model-registry/spec.md`「不包含」原文「修改 `agent_versions` 主对话模型语义，发布版本模型保持现状。」
- 范围：chat 并入注册表 + 版本级参数归位 + 迁移 + 前端版本表单不再硬编码 + 把已有的任务级覆盖 `tasks.model_id`（`tasks/models.py:83` 指向 `platform_models.id`，`tasks/schemas.py:42` 描述原文「可选：覆盖智能体默认模型」，现由 `conversation/services.py:1220-1226` 读取）接到同一解析路径。
- 不做：不照搬 Pi 的静态 provider 目录；不做多 provider fallback；不改 `model_usage` 记账口径（`model_usage/services.py:60-63` 快照模型名）；不动 image/embedding 现有绑定语义。
- 分档说明：命中 `models.py` 与 `migrations/**` 且跨模块，A 档（ADR + 拷问）。

## 来源与方案比较

- 官方/成熟案例：本机 Pi `/Users/lixingwen/xw/git/pi`（调研日期 2026-10-16）。要点：**模型目录 credential-blind，凭据独立存放，请求时拼装**——`packages/ai/src/types.ts:834-868 Model<TApi>`（能力、`contextWindow`、`cost`、`input` 等元信息在目录里，不含密钥）、`packages/ai/src/providers/deepseek.ts:6-15` 用 `envApiKeyAuth(...)` 只声明凭据来源、`packages/ai/src/auth/types.ts:44-69 CredentialStore`（按 `provider.id` 一条凭据）、`packages/coding-agent/src/core/model-registry.ts:66-84 getApiKeyAndHeaders(model)` 在请求时组装 `{apiKey?,headers?,baseUrl?,env?}`、`core/model-resolver.ts:620-700 findInitialModel` 五级优先级、`core/model-config.ts:1` 注释原文「Immutable, credential-blind models.json snapshot.」。
- 内部证据：本仓库 `docs/harness/requests/2026-08-27-model-registry/`（spec/research/verify）记录了注册表模块的原始设计与其有意保留的边界，可作为「为何当初分开」的依据。
- 方案 A（选）：`platform_models(model_type='chat')` + `agent_model_bindings(role='chat')` 成为对话模型的唯一来源；`build_chat_model` 改为「解析结果 + 版本级参数」两段式输入；`agent_versions` 删除 `model_name`/`model_base_url`/`api_key_encrypted`，保留 `temperature`/`model_options`/`context_window_tokens`/`capabilities`；无绑定时显式回退 `.env`（`config.py:246-247` 的 `MODEL_DEFAULT_NAME`/`MODEL_DEFAULT_BASE_URL` + `OPENAI_API_KEY`）。
- 方案 B：只把 `api_key`/`base_url` 移入注册表，`agent_versions.model_name` 保留为「模型名覆盖」。
- 方案 C：反向收口 —— 删掉 `ModelType.CHAT` 与前端 `'chat'` 选项，明确保留双轨，只补文档。
- 方案 D：双读 —— 版本级字段优先，未填则回落注册表。
- 选择理由：A 与 Pi 的「目录/凭据分离」同构，且让 `is_active`、密钥轮换、用量归属、模型清单四处收敛为一处；开发阶段无真实数据可清库（用户 m00322「没有真实数据 可以随时清库」），迁移成本最低；B 留下两个模型名真相来源，D 会让注册表的「停用即不再参与能力路由」在 chat 上失效。

## 被否决的选项

- **方案 B（只移凭据）**：模型名仍有两处（版本行与 `platform_models`），`is_active=False` 拦不住存量版本，「一个模型」的语义仍是假的。
- **方案 C（明确保留双轨）**：`ModelType.CHAT` 与前端 `MODEL_TYPES` 里的 `'chat'` 会持续误导管理员；密钥轮换与用量归属继续各自为政。
- **方案 D（版本优先 + 注册表兜底）**：两个来源都要看才排得清故障；停用模型后存量版本仍可对话，与 `model_registry/models.py:63-69` 的 `is_active` comment 语义冲突。
- **照搬 Pi 的静态 provider 目录（`models.generated.ts` 式）**：40+ provider 工厂、`ModelCost` 分档、`CredentialStore` 是为 CLI 多 provider 与 OAuth 场景设计的；ai-base 是单平台多租户、模型由管理员在后台登记，静态目录会带来生成器与巨大表体量却无对应收益。
- **本轮引入多 provider fallback 或 provider 抽象层**：与「一处定义、一处凭据、一处停用」无关，属于第 2 步的模型错误退避课题。
- **保留 `agent_versions.api_key_encrypted` 作为版本级密钥覆盖**：会让「密钥只有一处」不成立，且版本回滚会连带切换密钥。
- **保留 `model_name` 作为「同 provider 内的模型名快捷方式」**：仍需要第二处真相来源与二次校验，收益不足以抵消。
- **绑定与版本耦合：把 chat 模型下拉放进 Agent 版本表单**：一次操作更省事，但模型会随版本回滚而切换，且「同一模型被多个 Agent 共用、轮换一次全部生效」无法表达；绑定改由模型管理页的 `replace_agent_bindings` 承担，版本表单只管提示词与采样参数。
- **新增平台级默认 chat 模型**：解析会变成「绑定 → 平台默认 → `.env`」三条分支，「这一轮到底用了哪个模型」要多跳一层才能回答；本轮只保留「绑定 → 回落 `.env`」两条。

## 停点判断

- 是否涉及架构边界变化：是（对话模型解析从 `agent` 模块内联字段改为 `model_registry` 统一解析，跨 `agent`/`model_registry`/`conversation`/`gateway`/`tasks`）
- 是否涉及数据模型变化：是（`agent_versions` 删除三列、`platform_models` 的 chat 语义生效、需迁移与种子调整）
- 是否涉及 API 契约变化：是（Agent 版本创建/读取的模型字段变化，`model_registry` 的 chat 类型由死枚举变为可用）
- 是否涉及鉴权或权限行为变化：否（沿用 `_require_platform_admin` / `_require_platform_agent`）
- 命中任一项即 `approval.required: true`，进入实现前必须获得人工确认。

## 变更点

- `apps/backend/app/modules/model_registry/schemas.py:19-24` 与 `models.py:36-41`/`:98-103`：`BindingRole` 纳入 `chat`，comment 与文案同步。
- `apps/backend/app/modules/model_registry/resolver.py:19-27`/`:29`：`ResolvedModel` 供 chat 复用（必要时新增 `resolve_chat_model`），未绑定仍返回 None。
- `apps/backend/app/modules/agent/services.py:298-357`：`build_chat_model` 改为接收解析结果 + 版本级参数，`api_key` 兜底 `settings.openai_api_key`。
- `apps/backend/app/modules/agent/models.py:103-111` 删除三列；新增迁移（含存量版本三要素提升为 `platform_models` + `agent_model_bindings(role='chat')` 的数据迁移，可 downgrade）。
- 4 个调用点（`conversation/router.py:107`/`:187`、`conversation/services.py:1189`、`gateway/router.py:726`）改传解析结果；`tasks.model_id` 覆盖路径（`conversation/services.py:1220-1226`）并入同一解析。
- `apps/backend/scripts/seed_dev_env.py`：种子建 chat 模型并绑定，`apps/backend/scripts/reset_dev_db.sh` 可复现。
- `apps/front/src/features/agents/agent-version-form.tsx:74`（现为硬编码 `model_name: 'gpt-4o-mini'` 纯文本输入）改为从注册表选 chat 模型；`apps/front/src/api/model-registry.ts:3-8` 与后端枚举对齐。
- 验证方式：backend pytest + 迁移 upgrade/downgrade + reset 重灌 + 真模型出词，见验收标准。

## 验收标准

1. 迁移后 `agent_versions` 不再有 `model_name`/`model_base_url`/`api_key_encrypted`，存量行被提升为 `platform_models(model_type='chat')` + `agent_model_bindings(role='chat')`，`downgrade` 可逆。
2. `grep -rn "api_key_encrypted" apps/backend/app/modules/agent/` 无命中；`decrypt_secret` 只出现在 `model_registry`（与技能/MCP 各自的密钥字段无关）。
3. 改绑定后同一 Agent 对话走新模型：以 `model_usage` 里落库的 `model_name` 快照与容器日志中的上游模型名为准（非「重新发布版本」）。
4. 绑定的 chat 模型 `is_active=False` 时，对话返回稳定错误码而非静默回落 `.env`。
5. `bash apps/backend/scripts/reset_dev_db.sh` 重灌后经 `:8080` 登录 + `POST /api/v1/agents/1/chat` 返回 `success: true`。
6. `apps/backend/.venv/bin/python -m pytest tests/model_registry tests/agent tests/conversation tests/gateway tests/tasks -q` 全绿。
7. `pnpm --dir apps/front build` 通过，Agent 版本表单不再出现 `gpt-4o-mini` 字面量（grep 为空）。
