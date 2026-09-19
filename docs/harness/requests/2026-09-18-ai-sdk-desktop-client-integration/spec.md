# 设计说明

## 目标

- 让接入方桌面应用「智能运营工作台」（`/Users/lixingwen/xw/zhoudan/client`）接入 `xxai-agent`，并用它操控店铺运营平台（hua8）的数据；同时保留「桌面端未来执行操作类工具」的演进空间。
- 路线（2026-09-18 与用户确认）：
  - 接入方按标准 `http` origin 承载渲染层（主进程内建本地静态服务，固定 `http://127.0.0.1:<端口>`），不再保留 `file://`；
  - 复用本仓库既有的 shop 链路（`apps/shop` + `apps/backend/app/modules/shop_agent/`）：接入方主进程用自有 hua8 token 调 ai-base 换取 Embed token，**不向接入方下发 `client_secret`**，也不新建 token 代理服务；
  - `external_user_id` 取 hua8 `userId`；首版包含 4 个只读桌面工具（当前店铺、店铺列表、登录态健康、本地任务状态）。
- 目标用户与受影响对象：
  - 接入方桌面端（Electron 主进程 + 渲染层）
  - AI Base 管理后台使用者（配置 Embed Client 与 Agent 绑定的平台管理员）
- 完成后应产生的可验证结果：
  - `POST /api/v1/shop-agent/session` 支持按调用方指定 `agent_id` 与 `host_tool_names`（均为向后兼容的可选参数），使桌面端可使用独立 Agent 并启用页面宿主工具；
  - AI Base 的 CORS 允许来源可配置，默认值与现状逐条一致，并可登记接入方桌面来源；
  - 接入方以固定 `http://127.0.0.1:<端口>` 加载后，可完成 Embed token 签发、WebSocket 建连与一轮真实问答，通过店铺工具读取 hua8 数据，并至少成功注册一个桌面只读工具；
  - `apps/ai-sdk/README.md` 新增桌面客户端章节，`docs/CHANGELOG.md` 记录变更。
- 调研结论引用：依据 `research.md` 来源 8，`apps/shop` 已存在「接入方自有登录态 → 服务端校验 → 签发 Embed token」的完整链路且 `client_secret` 不下发；依据来源 2、7，改用 http origin 后浏览器来源会触发 CORS 校验，当前 CORS 白名单硬编码且不含桌面来源。方案比较与不选原因见 `research.md` 的「方案比较」与「最终决策」（最终采用方案 F = http origin 加载 + 复用 shop 链路）。

## 范围

1. AI Base 会话接口（`apps/backend/app/modules/shop_agent/{schemas.py,router.py}`、`apps/backend/app/modules/embed/services.py`）：`POST /api/v1/shop-agent/session` 增加两个可选参数：
   - `agent_id`：缺省时沿用 `settings.embed_agent_id`，传入时复用既有的 Embed Client–Agent 绑定校验（`is_agent_allowed`）；
   - `host_tool_names`：与 `/embed/tokens` 语义一致，只作为候选集合，实际 claim 取「请求 ∩ Embed Client 绑定工具」（`issue_embed_token` 内既有交集逻辑），网关侧还会再与 Agent 绑定工具求交集。
   - 失败时沿用现有错误语义，不新增错误码。
   - 背景：`issue_configured_agent_token` 目前不传递 `host_tool_names`，导致该链路签发的 token `host_tools` 恒为空，页面注册的宿主工具会被网关静默拒绝；桌面端要带只读工具就必须补齐这个参数。
2. AI Base CORS 配置化（`apps/backend/app/core/config.py`、`apps/backend/app/__init__.py`）：新增 CORS 允许来源设置项（环境变量），默认值与当前硬编码列表逐条一致。
3. AI Base 文档（`apps/ai-sdk/README.md`）：新增「桌面客户端（Electron）接入」章节，说明：
   - 渲染层必须以 `http` origin 承载（主进程内建静态服务或等价方式），`file://` 不受支持及原因（Electron 官方安全清单与实测结论）；
   - 桌面来源需要登记到 Embed Client 的 `allowed_origins`，并会被 CORS 校验；
   - 推荐链路：接入方主进程持自有登录态调用 `POST /api/v1/shop-agent/session`，只把短期 Embed token 交给渲染层，登录态 token 不下发到渲染层；`client_secret` 始终留在 AI Base；
   - 桌面端可按调用方指定 `agent_id`，以便与网页端使用不同 Agent。
4. `docs/CHANGELOG.md`：记录本次变更。
5. 接入侧实施（跨仓，跟随同一 request 执行，代码提交在接入方仓库）：
   - Electron 主进程：内建本地静态服务承载 `dist/renderer`，窗口从固定 `http://127.0.0.1:<端口>` 加载；同步更新可信来源判定与导航守卫；dev 环境 `http://127.0.0.1:5190` 保持不变。
   - 新增 IPC（如 `agent:session`）：主进程用系统安全存储中的 hua8 token 调 AI Base `POST /api/v1/shop-agent/session?origin=<桌面来源>`，携带 `{shopToken, shopUserId, agent_id}`，只把返回的短期 `access_token` 交给渲染层。
   - 渲染层：引入 `xxai-agent`，以 `ui.mode: 'embedded'` 挂载到现有右侧助手区，`getToken` 走上述 IPC；并通过 preload IPC 注册 4 个只读桌面工具（`get_current_shop`、`list_shops`、`get_session_health`、`list_local_tasks`，`sideEffect: 'none'`）。
   - 工具注册的前置条件（需在 AI Base 后台完成）：把 4 个工具的策略绑定到目标 Agent（`agent_host_tools`）与 Embed Client（`embed_client_host_tools`），且策略的 `input_schema` 必须与前端注册的定义指纹完全一致，否则注册会被网关按策略不匹配丢弃。
   - 配置项：AI Base 基址、`agent_id`、桌面来源常量；不再需要接入方后端参与本功能。

## 非目标

- 不向接入方下发 `client_secret`，不新建 token 代理服务，不修改接入方 FastAPI 后端（原方案 A/E 的 broker 设计作废）。
- 不新增 `allow_desktop_client` 字段，不做数据模型迁移，不修改 `allowed_origins` 校验语义与网关 origin 比对逻辑。
- 不实现公共客户端 / PKCE 授权码 / 设备授权（`research.md` 方案 D）。
- 不实现托管聊天页与 iframe 承载（`research.md` 方案 C）。
- 不改动 `xxai-agent` 运行时代码；若联调发现 `http` origin 下存在真实缺陷，另开 `/fix` 处理。
- 不做带副作用的桌面端工具（打开店铺、触发 Cookie 同步等）与其确认流。

## 风险

- 权限相关：CORS 允许来源配置化后，若把来源填得过宽会扩大可读取接口响应的页面范围；默认值必须与现状逐条一致，新增来源逐项登记。
- 契约相关：`shop-agent/session` 新增可选 `agent_id` 属于向后兼容扩展，但需要确认既有调用方（`apps/shop`）不受影响，且未绑定该 Agent 的 Client 必须被拒绝。
- 依赖相关：该链路要求 AI Base 能访问 hua8（`STORE_OPS_BASE_URL`）；店铺 token 会写入 AI Base Redis（TTL 跟随 hua8 登录时效），属既有机制，需在接入说明中如实告知。
- 联调相关：接入方改造加载链路会触及应用启动关键路径（窗口加载、导航守卫），需要真机回归；跨仓改动需两仓库协同提交与分阶段验证。
- 数据风险：无数据模型改动，无数据迁移风险。

## 停点判断

- 是否涉及架构边界变化：否。
- 是否涉及数据模型变化：否。
- 是否涉及 API 契约变化：**是**（`POST /api/v1/shop-agent/session` 新增可选 `agent_id`，向后兼容）。
- 是否涉及鉴权或权限行为变化：**是**（CORS 允许来源改为可配置并新增桌面来源；会话接口可为目标 Agent 签发 token，受 Client–Agent 绑定校验约束）。
- 结论：**进入实现前需人工确认**。本 spec 已提交人工确认，确认通过后方可进入 `plan` 与实现。

## 验收标准

- 会话接口兼容性：不传 `agent_id` 时，`shop-agent/session` 的行为与变更前完全一致（同一 Agent、同一错误语义）；传入已绑定 Agent 时签发对应 Agent 的 token；传入未绑定 Agent 时被拒绝。
- CORS 配置化：默认配置下既有来源（如 `http://127.0.0.1:5173`）的 `Access-Control-Allow-Origin` 行为与变更前一致；通过配置新增桌面来源后，该来源的跨域请求可通过；未登记的来源不返回允许头。
- 来源校验不变：`allowed_origins` 仍只接受无路径的 `http(s)` origin，`file://` 延续被拒；Embed token 签发与网关 origin 比对逻辑无改动。
- 接入侧加载改造：打包后的应用窗口以固定 `http://127.0.0.1:<端口>` 加载成功，内部导航与新窗口拦截行为与改造前一致，dev 环境 `5190` 不受影响。
- 会话接口的项目固定 Client：`PROJECT_EMBED_*` 常量配齐时，请求不需要携带任何凭证即可按该项目 Client/Agent/来源签发；只配了 Client 而未配 Agent 或来源时返回 400；常量留空时行为与变更前一致。
- 会话接口的 `client_id` / `client_secret`：不传时沿用服务端 Embed 配置（与变更前一致）；只传其一、或携带凭证但未传 `agent_id` / `origin` 时被拒绝；成对传入时按该 Client 的 `allowed_origins`、Agent 绑定、工具绑定与配额校验，且这些凭证只允许出现在服务端调用链中。
- 会话接口的 `host_tool_names`：未传时 token 的 `host_tools` 为空（与变更前一致）；传入与 Client 绑定工具匹配的名称时，token claim 仅包含交集内的名称；传入未绑定名称时被忽略而非报错。
- 接入侧端到端：本机 Electron 中完成一轮真实问答并触发店铺数据工具（如 `store_ops_query`）返回 hua8 数据；至少一个桌面只读工具注册成功并可被模型调用；浏览器与渲染层的请求中不出现 `client_secret`，hua8 token 不下发到渲染层。
- 文档与测试：`apps/ai-sdk/README.md` 含桌面客户端章节，`docs/CHANGELOG.md` 已更新；新增/更新单测覆盖会话接口的 `agent_id` 分支与 CORS 配置读取，既有后端测试保持通过。

## 变更记录

### 2026-09-18 第 4 次变更

- 变更原因：用户确认凭证直接固定留在 AI Base 后端即可（「我就在这个方法里固定在我的后端里」），未来新项目在 AI Base 里新增一个后端签发方法
- 变更内容：`shop_agent/router.py` 顶部新增 `PROJECT_EMBED_CLIENT_ID` / `PROJECT_EMBED_CLIENT_SECRET` / `PROJECT_EMBED_AGENT_ID` / `PROJECT_EMBED_ORIGIN` 常量；接口层取值优先级变为「请求携带的凭证 > 项目常量 > 环境变量」；固定 Client 时必须同时给出 Agent 与来源，否则直接 400，避免退回默认 Agent / 默认来源后报出难以定位的错误
- 影响章节：范围、停点判断、验收标准
- 是否触发人工确认：是（API 契约扩展 + 凭证校验行为），方向由用户直接给出
- 关联计划更新：本次为验收后的增量实现，`plan.md` 不新增阶段，仅同步 `verify.md` 与 `acceptance.md`

### 2026-09-18 第 3 次变更

- 变更原因：用户明确「不要动 zhoudan/hua8」，改为让 `shop-agent/session` 直接接受调用方带来的 Embed Client 凭证并透传给 `issue_configured_agent_token`，以支持一个部署接入多个 Embed Client
- 变更内容：`ShopAgentSessionRequest` 新增可选 `client_id` / `client_secret`（别名 `clientId` / `clientSecret`）；`issue_configured_agent_token` 新增同名可选入参，缺省回退 `settings.embed_client_id` / `settings.embed_client_secret`；两者必须成对提供，且携带凭证时必须显式给出 `agent_id` 与 `origin`，避免默认 Agent / 默认来源与目标 Client 不匹配；不传凭证时行为与变更前完全一致
- 影响章节：目标、范围、停点判断、验收标准
- 是否触发人工确认：是（API 契约扩展 + 凭证校验行为），方向由用户直接给出
- 关联计划更新：本次为验收后的增量实现，`plan.md` 不新增阶段，仅同步 `verify.md`

### 2026-09-18 第 2 次变更

- 变更原因：用户指出接入方可直接使用 hua8 token，并指向既有 `apps/shop`（`apps/shop/src/pages/ChatPage.vue`），明确「不需要对接接入方后端」「主要是操控 hua8 的数据」
- 变更内容：在 http origin 加载的基础上（第 1 次变更）复用 shop 链路——接入方主进程用 hua8 token 调 `POST /api/v1/shop-agent/session` 换取 Embed token，`client_secret` 不再下发到接入方；范围中删除接入方后端 token broker 与「后端监听收敛 127.0.0.1」，新增会话接口的可选 `agent_id` 支持；风险中「secret 随包分发」降级为已消除，改为记录 CORS 放宽、契约扩展与 hua8 可达性依赖
- 变更内容补充（同日，经用户确认「首版要带只读工具」后细化）：会话接口同时新增 `host_tool_names` 参数（否则该链路签发的 token `host_tools` 恒为空，宿主工具会被网关静默拒绝）；接入范围明确为 4 个只读桌面工具，并列出后台绑定与 schema 指纹一致性要求
- 影响章节：目标、范围、非目标、风险、停点判断、验收标准
- 是否触发人工确认：是（API 契约扩展 + CORS 来源与 Agent 签发范围调整）
- 关联计划更新：`plan.md` 待编写

### 2026-09-18 第 1 次变更

- 变更原因：用户追加约束「如果 `file://` 麻烦，就改成 http origin 加载」，允许接入方改造渲染层加载方式
- 变更内容：来源路线由方案 A（保留 `file://` + AI Base 新增 `allow_desktop_client` 开关）改为「接入方以固定 `http://127.0.0.1:<端口>` 承载渲染层 + AI Base 侧 CORS 来源可配置」；删除数据模型迁移、`allow_desktop_client` 字段、签发分支与网关归一化改动
- 影响章节：目标、范围、非目标、风险、停点判断、验收标准
- 是否触发人工确认：是（CORS 允许来源属于权限行为调整）
- 关联计划更新：`plan.md` 待编写

### 初始版本

- 时间：2026-09-18
- 变更原因：首次创建 request，为 Electron 桌面客户端接入 `xxai-agent` 提供来源支持并落地接入方实施
- 变更内容：建立本次任务的初始设计说明（当时选择方案 A：保留 `file://`，AI Base 侧新增显式桌面客户端能力开关）
- 影响章节：全部
- 是否触发人工确认：是（原方案 A 触发数据模型、API 契约、鉴权三项停点）
- 对话中已确认的接入前提（2026-09-18）：`external_user_id` 取花伴 `userId`；首版工具范围限定为只读工具
