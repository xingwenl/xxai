# 对话模型并入平台模型注册表

## Status

accepted

关联 Harness request：`2026-10-16-model-registry-unification`（tier A，spec 与验证证据见 `docs/harness/requests/2026-10-16-model-registry-unification/`）。术语（平台模型、模型绑定、对话模型）见 `CONTEXT.md`。

## Decision

**对话模型成为 `platform_models` 的一条（`model_type='chat'`），经 `agent_model_bindings(role='chat')` 绑定到 Agent；`agent_versions` 删除 `model_name`/`model_base_url`/`api_key_encrypted`。** 现在模型三要素内联在版本行（`apps/backend/app/modules/agent/models.py:103-111`），而注册表轨的 `model_type` comment 里已经写着 `chat`、`BindingRole` 的 docstring 却写着「Agent 可绑定的能力角色，主对话模型不在此列。」（`model_registry/schemas.py:19-24`）——`ModelType.CHAT` 与前端 `MODEL_TYPES` 里的 `'chat'` 都是无消费者的死枚举。并入之后，密钥轮换、`is_active` 停用、用量归属、后台模型清单四处收敛为一处。版本级参数（`temperature`/`model_options`/`context_window_tokens`/`capabilities` 与 thinking 选项）留在版本行：它们随版本变化，而模型是平台资产。

**解析入口唯一：`resolve_agent_model(..., role="chat")`；`build_chat_model` 改成「解析结果 + 版本级参数」两段式输入。** 现在 `build_chat_model` 直接读 `version` 的模型三要素与 `temperature`（`agent/services.py:313-318`），并且 `api_key` 没有任何 `settings.openai_api_key` 兜底；改为解析结果后，凭据只经 `model_registry` 的 `decrypt_secret` 一处解密，`ResolvedModel`（`resolver.py:19-27`）成为 chat 与 image/embedding 共用的解析产物。

**无绑定时显式回落 `.env`（`MODEL_DEFAULT_NAME`/`MODEL_DEFAULT_BASE_URL` + `OPENAI_API_KEY`）；已绑定但 `is_active=False` 时报错而不回落。** 回落保住开发环境零配置可用；若停用也回落，`is_active` 的语义（`model_registry/models.py:63-69` comment「停用后不再参与能力路由」）在 chat 上失效，管理员会以为停用了而实际还在用。不新增「平台级默认 chat 模型」——那会是第三处回落分支，并让「到底用了哪个模型」更难回答。

**绑定与版本解耦：绑定在模型管理页（既有 `replace_agent_bindings`），版本表单只管提示词与模型参数。** 模型是平台资产、版本是 Agent 快照；把模型选择塞进版本表单，会让版本回滚连带切换模型，也会让「同一模型被多 Agent 共用、轮换一次全生效」无法表达。

**迁移带数据迁移：把存量 `agent_versions` 的（`model_name`, `model_base_url`, `api_key_encrypted`）按平台去重提升为 `platform_models(model_type='chat')` 行并建立绑定，可 downgrade。** 开发阶段确实可以清库（用户 m00322「没有真实数据 可以随时清库」），但迁移成本很低，收益是「不清库也能升、回滚不丢配置」。API key 密文用同一把 `AGENT_MASTER_KEY`（`config.py:288-290`）加密，可原样搬运，不必解密再加密。

**`tasks.model_id` 继续作为任务级覆盖，并接入同一解析。** 字段（`tasks/models.py:83`）与描述（`tasks/schemas.py:42`「可选：覆盖智能体默认模型」）已存在，统一后它指向另一个 `platform_models` 行，语义不变；前端接线留到需要时，本轮不扩大范围。

## Considered Options

- **只把 `api_key`/`base_url` 移入注册表，保留版本级 `model_name`**：模型名仍有两处真相来源，`is_active=False` 拦不住存量版本，「一个模型」的语义仍是假的。
- **明确保留双轨、只删掉 `chat` 死枚举**：`ModelType.CHAT` 与前端选项会继续误导管理员；密钥轮换与用量归属继续各自为政。
- **双读（版本级字段优先，未填回落注册表）**：排障要同时看两个来源；停用模型后存量版本仍可对话，与 `is_active` 的注释语义冲突。
- **照搬 Pi 的静态 provider 目录（`models.generated.ts` / `Model<TApi>` / `CredentialStore`）**：那是为 CLI 多 provider 与 OAuth 场景设计的；ai-base 是单平台多租户、模型由管理员在后台登记，静态目录会带来生成器与巨大表体量却无对应收益。取其「目录 credential-blind、凭据独立存放、请求时拼装」的分层思想即可。
- **本轮引入 provider 抽象层与多 provider fallback**：与「一处定义、一处凭据、一处停用」无关，属于模型错误退避课题。
- **保留 `agent_versions.api_key_encrypted` 作为版本级密钥覆盖**：会让「密钥只有一处」不成立，且版本回滚会连带切换密钥。
- **版本表单内嵌 chat 模型下拉**：一次操作更省事，但版本与绑定耦合，回滚语义变混。
- **新增平台级默认 chat 模型**：多一处配置与解析分支，排查「这一轮到底用了哪个模型」要多跳一层。
- **不写数据迁移、只依赖清库重灌**：迁移不可逆，且会把「环境重建」与「模型配置」绑在一起——清库后必须记得重新登记模型。

## Consequences

- **发布一个可用 Agent 的步骤变多**：先在后台模型管理登记 chat 模型 → 给 Agent 绑定 → 再发布版本。`apps/backend/scripts/seed_dev_env.py` 与 `apps/backend/scripts/reset_dev_db.sh` 已按这个顺序实现，新环境一条命令可复现。
- **版本回滚不再回滚模型**：回滚只换提示词与采样参数，模型跟随绑定。这是一次用户可见的语义变化，必须写进用户文档（`docs/runbooks/dev-environment.md` 与前端提示文案）。
- **`agent_versions` 的 API 契约直接删字段**，无兼容期（开发阶段、无外部使用方）。前端 `apps/front/src/features/agents/agent-version-form.tsx:74` 的硬编码 `model_name: 'gpt-4o-mini'` 必须一并删除，否则会出现「表单能填、后端不认」。
- **`model_usage` 的模型名快照仍取实际使用的模型名**（`model_usage/services.py:60-63`），因此「同一 Agent 换绑后用量按模型分开统计」自动成立。
- **迁移必须处理同名冲突**：同一平台内 (model_name, base_url, api_key 密文) 相同的版本行只造一条模型条目并各自绑定；若存量行的密文不同（同一模型两份密钥），`UniqueConstraint("platform_id","model_type","model_name")` 会拒绝插入，迁移应把行合并到已有条目而不是报错。
- **停用 chat 模型会让绑定了它的 Agent 立刻无法对话**（这是 `is_active` 的语义），定时任务也会在运行期失败。管理员停用前需要能看到「哪些 Agent 绑定了它」，这条提示属于模型管理页的后续改进。
- **`model_registry` 从「辅助角色模块」变成对话主链路的一部分**：它的 resolver 变成冷路径上的关键依赖，相关测试（`tests/model_registry/`）需要覆盖 chat 角色与「停用不回落」。
