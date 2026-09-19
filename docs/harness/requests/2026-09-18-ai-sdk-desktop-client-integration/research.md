# 业界调研记录

## 调研问题

- 本次要解决什么问题：第三方 Electron 桌面应用「智能运营工作台」（仓库 `/Users/lixingwen/xw/zhoudan/client`）要接入 `xxai-agent`。该应用是本地优先形态：渲染层生产环境由 `loadFile` 加载（来源为 `file://`），没有可供浏览器直接调用的中心登录服务端，`client_secret` 只能随安装包分发。现有 Embed 通道要求接入方网页提供 `http(s)` origin，并在 WebSocket 建连时用请求头 `Origin` 与 token 中的 origin claim 比对，因此桌面端当前无法直接接入。
- 2026-09-18 追加约束一：用户明确「如果 `file://` 麻烦，就改成 http origin 加载」，即允许接入方改造渲染层加载方式，换取更小的服务端改动与更标准的来源语义。
- 2026-09-18 追加约束二：用户指出接入方可直接使用 hua8 token，并指向本仓库既有的 `apps/shop`（`apps/shop/src/pages/ChatPage.vue`），且明确「不需要对接接入方后端」「主要是操控 hua8 的数据」。据此确认存在一条不需要向客户端下发 `client_secret` 的既有链路，方案再次调整，最终决策见文末。
- 调研结果将影响哪些范围、架构、接口或实现决策：
  - 接入方的来源形态选择：保留 `file://` 并由 AI Base 放开来源语义，还是接入方改造成 `http` origin 后沿用现有来源白名单
  - 若改用 `http` origin：AI Base 的 CORS 允许来源是否需要调整（浏览器 origin 会触发 CORS 校验）
  - 是否已有「用接入方自有登录态换取 Embed token」的现成链路，能否避免向客户端分发 `client_secret`
  - Embed token 签发与网关 origin 校验的实现位置与比较规则
  - 管理后台 Embed Client 配置项与校验规则
  - `xxai-agent` 接入文档中桌面客户端章节的边界声明（哪些约束是安全保证、哪些只是记录性约束）
  - 接入侧 token 代理的落点（桌面本地后端 vs 中心服务端）与后续演进方向

## 功能复杂度

- 级别：核心功能（涉及鉴权/权限边界变更，且接入方是随安装包分发的桌面客户端，凭据保守能力与传统 Web 接入不同）
- 选择理由：改动的是 Embed token 的「来源约束」这一安全边界；同时需要判断浏览器侧 CORS、SDK 运行时代码是否需要同步调整
- 最低调研要求：官方文档 + 可复现的真实实验 + 标准/成熟实践比较，并记录被否决方案的原因
- 调研方式说明：官方站点可访问；桌面端行为不依赖二手资料，直接在本机用接入方实际使用的 Electron 版本做了一次性探针实验（见来源 2）

## 参考依据

### 来源 1

- 类型：官方文档
- 名称：Electron Security 官方安全清单，第 18 条「Avoid usage of the `file://` protocol and prefer usage of custom protocols」
- 链接：https://www.electronjs.org/docs/latest/tutorial/security
- 版本或发布日期：抓取于 2026-09-18（文档页无版本号，对应 Electron 最新稳定版文档）
- 调研日期：2026-09-18
- 核心做法：官方明确建议不要用 `file://` 承载本地页面，理由是「The `file://` protocol gets more privileges in Electron than in a web browser」，且「Pages running on `file://` have unilateral access to every file on your machine meaning that XSS issues can be used to load arbitrary files from the users machine」；同时指出 `file://` 页面无法通过 HTTP 头下发 CSP，只能使用 `<meta>` 标签。官方推荐改用 `protocol.handle` 提供的自定义协议。
- 对本项目的启发：接入方当前渲染层是 `file://`，属于 Electron 官方已标注的既有技术债。本期接入不应要求接入方先改造页面加载方式（改动过大且与本仓库无关），但必须在文档与 spec 中把该前提写明，并把「改用自定义协议 + 自定义 origin」列为接入方后续可选的加固路径。

### 来源 2

- 类型：一次性探针实验（本机可复现，非二手资料）
- 名称：`file://` 渲染层的 WebSocket `Origin` 与 CORS 行为实测
- 链接：本机脚本 `/private/tmp/origin-probe/{server.cjs,server-nocors.cjs,main.cjs,page.html,page2.html,page3.html}`（一次性产出，未入库）
- 版本或发布日期：`electron@37.10.3`（取自 `zhoudan/client/operations-desktop/node_modules/.pnpm/electron@37.10.3`），UA 显示 `Chrome/138.0.7204.251 Electron/37.10.3`
- 调研日期：2026-09-18
- 核心做法：用一个 Node HTTP 服务同时实现 `upgrade` 与普通请求日志；用 Electron 以 `file://` 与 `http://127.0.0.1:<port>` 两种来源加载探针页面，页面分别发起 `new WebSocket(url, 'xxai-agent.v1')`、无自定义头的 GET、带 `Authorization` 头的 POST。
- 实测结果：
  - `file://` 页面建立 WebSocket：请求头 `Origin: file://`（字面值 `file://`）。
  - `file://` 页面发起 `fetch`（GET 与带 `Authorization` 的 POST）：**完全不携带 `Origin` 头**，也没有发出 `OPTIONS` 预检；服务端不返回任何 `Access-Control-Allow-Origin` 时跨域 POST 仍然成功，即 Chromium 对不透明来源不执行 CORS 校验。
  - `http://127.0.0.1:<port>` 页面：WS 与 fetch 均携带该 http origin，并正常受 CORS 约束。
- 对本项目的启发：
  - 桌面接入只需要处理 WebSocket 的 `Origin: file://`；SDK 的 HTTP 调用（附件上传/状态查询/资源下载）不需要新增 CORS 白名单，因此不必放宽后端的 CORS 配置。
  - 反向说明：桌面端无法用 CORS 做来源约束，origin 校验对桌面端只能是记录性约束。

### 来源 3

- 类型：标准规范（IETF BCP）
- 名称：RFC 8252 — OAuth 2.0 for Native Apps
- 链接：https://www.rfc-editor.org/rfc/rfc8252.txt
- 版本或发布日期：2017-10（RFC 8252）
- 调研日期：2026-09-18
- 核心做法：
  - §6 要求公共原生客户端必须实现 PKCE（「Public native app clients MUST implement the Proof Key for Code Exchange (PKCE [RFC7636]) extension to OAuth, and authorization servers MUST support PKCE for such clients」）。
  - §7.3 给出 loopback 重定向（`http` + 回环地址 + 客户端监听端口）等原生应用可用的重定向方式。
  - §8.5 明确「Secrets that are statically included as part of an app distributed to multiple users should not be treated as confidential secrets」，并指出不推荐服务端要求公共原生客户端用共享密钥做认证；若仍要求，必须把该客户端当公共客户端处理，不能把密钥当作身份证明。
- 对本项目的启发：桌面端把 `client_secret` 打包进安装包，属于标准里点名的反模式。本期可以为了尽快接入接受这一现状，但不能把它描述成安全方案；spec 必须把「短 TTL + 配额 + 轮换/撤销」列为配套缓解措施，并把「公共客户端 + PKCE / 设备授权」列为后续演进方向。

### 来源 4

- 类型：标准规范（IETF BCP）
- 名称：RFC 9700 — Best Current Practice for OAuth 2.0 Security
- 链接：https://www.rfc-editor.org/rfc/rfc9700.txt
- 版本或发布日期：2025-01（RFC 9700）
- 调研日期：2026-09-18
- 核心做法：对公共客户端的授权码、refresh token、重定向校验提出强制要求（如公共客户端 refresh token 必须 sender-constrained 或轮换），并说明公共客户端的授权码可被直接兑换，不能依赖客户端身份校验来防注入。
- 对本项目的启发：与本仓库的场景（服务端签发短期 Embed token、浏览器侧只持短期 token）方向一致；主要差别在 `client_secret` 的保密性假设，与来源 3 的结论互相印证。

### 来源 5

- 类型：成熟开源项目（生产实现，本机源码）
- 名称：Dify Web 嵌入式聊天机器人（embedded-chatbot）的接入方式
- 链接：`/Users/lixingwen/xw/git/dify/web/app/components/base/chat/embedded-chatbot/header/index.tsx`（本地 checkout 快照）
- 版本或发布日期：本地快照，调研日期 2026-09-18
- 核心做法：嵌入式聊天以 iframe 承载，页面由 Dify 自己的域名提供，通过 `window.parent.postMessage({ type: 'dify-chatbot-iframe-ready' }, targetOrigin)` 与宿主通信，宿主侧必须显式提供 origin。
- 对本项目的启发：这是「托管聊天页」路线的典型实现——把聊天页面放在平台自己的 https 域名下，宿主用 iframe/webview 承载，从而保持正常的浏览器 origin 语义。本次未采用该路线（原因见方案比较），但它验证了 `file://` 之外确实存在可行的替代方案，可作为接入方后续改造参考。

### 来源 8

- 类型：本项目现有实现（成熟链路，一手代码）
- 名称：店铺运营（shop）项目的 hua8 身份链路与 shop-agent 会话接口
- 链接：`apps/shop/README.md`、`apps/shop/src/pages/ChatPage.vue`、`apps/backend/app/modules/shop_agent/router.py`、`apps/backend/app/modules/shop_agent/services.py`、`apps/backend/app/modules/tools/shop/registry.py`
- 版本或发布日期：当前工作区分支
- 调研日期：2026-09-18
- 核心做法：
  - 浏览器先用 hua8 账号登录，仅在会话存储中持有 hua8 的 `shopToken` 与 `shopUserId`（`apps/shop/src/lib/session.ts`）。
  - `getToken` 调 ai-base `POST /api/v1/shop-agent/session?origin=<location.origin>`，请求体只带 `{shopToken, shopUserId}`。
  - ai-base 侧 `verify_shop_token` 用该 token 调 hua8 `/hua8-api/system/user/getInfo`，校验 `user.userId == shopUserId` 后才签发 Embed token（`shop_agent/services.py`），`external_user_id` 即 hua8 `userId`。
  - 签发复用服务端 Embed 配置（`issue_configured_agent_token` 读 `EMBED_CLIENT_ID/SECRET/AGENT_ID/ORIGIN`），`origin` 参与 `allowed_origins` 校验，`client_secret` 始终留在 ai-base。
  - 店铺 token 写入 Redis（`shop-agent:end-user:<end_user_id>`，TTL 跟随 hua8 登录时效），供服务端业务工具（`tools/shop/data/store_ops_query`、`order_query`、`ui/show_shop_list`）调用 hua8 数据。
- 对本项目的启发：这是「接入方自有登录态 → Embed token」的现成实现，且**不需要接入方持有 `client_secret`**。桌面端主进程已经持有 hua8 token 并调用同一个 `getUserInfo` 接口（`operations-desktop/electron/core/huaban-auth-client.ts`），因此桌面端只需复用这条链路即可，`client_secret` 分发风险（此前方案 A/E 的最大风险项）可以直接消除。

### 来源 7

- 类型：本项目现有实现（CORS 策略）
- 名称：FastAPI CORS 中间件配置
- 链接：`apps/backend/app/__init__.py:74-84`
- 版本或发布日期：当前工作区分支
- 调研日期：2026-09-18
- 核心做法：`CORSMiddleware` 的 `allow_origins` 是硬编码列表，仅包含 `http://127.0.0.1:5500`、`http://127.0.0.1:5173`、`http://localhost:5173`、`http://localhost:5174`，`allow_credentials=True`；`Settings` 中没有 CORS 相关配置项。
- 对本项目的启发：若接入方改用 `http` origin，SDK 的 HTTP 调用（附件上传/状态查询/资源下载）会被浏览器按 CORS 校验，而当前白名单不可能包含接入方桌面端口。因此需要把 CORS 来源改为可配置，并保持默认值不变以免影响现有部署。

### 来源 6

- 类型：本项目现有实现
- 名称：Embed Client 来源校验与网关连接校验链路
- 链接：`apps/backend/app/modules/embed/schemas.py`、`apps/backend/app/modules/embed/services.py`、`apps/backend/app/modules/gateway/auth.py`、`apps/backend/app/__init__.py`、`apps/front/src/features/embed-clients/index.tsx`
- 版本或发布日期：当前工作区分支
- 调研日期：2026-09-18
- 核心做法与现状：
  - `normalize_origins` 只接受无路径的 `http(s)` origin，`file://` 会直接被拒（`apps/backend/app/modules/embed/schemas.py:6`）。
  - `issue_embed_token` 用 `request.origin.rstrip("/") in client.allowed_origins` 判定来源（`apps/backend/app/modules/embed/services.py:61`）。
  - 网关用 `payload.get("origin") != origin.rstrip("/")` 比对 token claim 与 WebSocket 请求头（`apps/backend/app/modules/gateway/auth.py`），`Origin` 缺失时以空串参与比较。
  - 数据模型上已有同类的「显式能力开关」先例：`PlatformEmbedClient.allow_temporary_tools`（`apps/backend/app/modules/embed/models.py`）。
  - CORS 当前是硬编码的 localhost 白名单（`apps/backend/app/__init__.py:74-84`），仅服务本地演示。
  - 管理后台 `apps/front/src/features/embed-clients/index.tsx` 用 `new URL(origin)` 校验输入并禁止路径/查询/片段。
- 对本项目的启发：新增设备形态支持时，沿用「显式开关字段」比在 origin 列表里塞魔法字符串更符合现有设计；`rstrip("/")` 会把 `file://` 归一化成 `file:`，因此 `file://` 不能走现有的 origin 归一化路径，需要单独的判定分支。

## 方案比较

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| A. 保留 `file://`，AI Base 新增显式的桌面客户端能力开关（`allow_desktop_client`），token claim 记为 `file://`，网关按字面值比对 | 接入方零改造渲染层；改动集中在本仓库；与现有 `allow_temporary_tools` 模式一致；`file://` 来源在后台配置中可见可审计 | 属于鉴权边界放宽：origin 校验对桌面端退化为记录性约束；`client_secret` 随包分发的风险仍需接受 | 高：满足「未来要操作桌面端功能」的目标，且能最快打通端到端联调 |
| B. 保持 `file://`，由 Electron 主进程用 `webRequest` 改写 WS 握手 `Origin` 头 | 两侧几乎零改动 | 属于客户端伪造服务端安全校验，服务端无法审计；违反「origin 校验」的既有语义；出问题时不可解释 | 低：技术上可行但不推荐作为默认方案 |
| C. 托管聊天页：接入方在自己的 https 域名上部署聊天页，桌面端用独立窗口/webview 承载 | 保持标准浏览器 origin 语义；AI Base 零改动；与 Dify 嵌入式方案一致 | 桌面端工具需要跨进程桥接，会削弱接入方现有「远程页面不注入 preload/IPC」的安全边界（参考 `electron/merchant-authorization-window.ts`）；需要额外前端部署与域名维护；离线不可用 | 中：安全姿态最好，但成本与体验代价高于本期目标 |
| D. 公共客户端：桌面端走 PKCE 授权码 / 设备授权换取 token，不再持有 `client_secret` | 符合 RFC 8252/9700 的标准做法，长期最稳 | 需要 AI Base 新增授权端点、PKCE 校验与客户端注册模型，属于新的 API 与鉴权契约；接入方的身份来源也需要重新设计 | 低（本期）：周期长，超出本次「先接上」的范围，列为后续方向 |
| E. 接入方改造渲染层加载方式：主进程内建本地静态服务，窗口从 `http://127.0.0.1:<固定端口>` 加载，沿用现有 `allowed_origins` 白名单；AI Base 侧只把 CORS 来源改为可配置 | 来源语义回归标准 `http` origin，`allowed_origins` 与网关 origin 比对逻辑完全不需要改动（无数据模型/接口/鉴权变更）；顺带消除 Electron 官方指出的 `file://` 技术债；localStorage 等 Web 能力行为更接近普通浏览器 | 需要接入方改造加载链路；浏览器 origin 会触发 CORS；`client_secret` 若放在接入方仍无法保密（需靠 F 消除） | 中：作为 F 的加载前提保留 |
| F. 在 E 的基础上复用 `apps/shop` 既有链路：接入方主进程用自有 hua8 token 调 `POST /api/v1/shop-agent/session`，由 ai-base 服务端校验身份并签发 Embed token | **`client_secret` 完全不下发到接入方**，此前最大的安全风险项被消除；身份校验由服务端调用 hua8 `getUserInfo` 完成，接入方无法伪造他人身份；店铺 token 注入 Redis 后，服务端店铺工具可直接查询 hua8 数据（正是接入方的主要诉求）；改动集中在已存在的接口与配置 | 需要 ai-base 能访问 hua8；桌面端与 shop web 若使用不同 Agent，需要让会话接口支持指定 `agent_id`；接入方主进程需要新增一个出站调用与 IPC 通道 | 最高：安全模型与既有 shop 链路一致，且满足「操控 hua8 数据」的主诉求 |

## 最终决策

- 选择方案：**F = E（http origin 加载）+ 复用 `apps/shop` 的 shop-agent 会话链路**。方案 A 降级为备选。
- 选择原因：
  - 用户在 2026-09-18 明确允许接入方改造加载方式（「如果 `file://` 麻烦，就改成 http origin 加载」），来源语义回到标准 `http` origin 后，`platform_embed_clients.allowed_origins`、Embed token 签发、网关 origin 比对**全部无需改动**，本仓库不再触碰数据模型与来源校验逻辑。
  - 用户指出接入方可以直接使用 hua8 token。核对现网实现后确认：`apps/shop` 已存在「接入方自有登录态 → 服务端校验 → 签发 Embed token」的完整链路，且 `client_secret` 始终留在 ai-base。采用该链路后，此前方案 A/E 中「`client_secret` 随安装包分发、无法保密」的核心风险直接消失。
  - 该链路附带把 hua8 token 注入 Redis，服务端店铺工具（`store_ops_query` 等）即可查询接入方真正关心的 hua8 数据，与用户「主要是操控 hua8 的数据」的目标一致。
  - 桌面端主进程已经持有 hua8 token，并且调用的是与 `verify_shop_token` 完全相同的 `getUserInfo` 接口，接入改造成本低。
  - 方案 E 顺带解决 Electron 官方安全清单第 18 条指出的问题（`file://` 页面权限过大、无法用响应头下发 CSP），属于对现有技术债的正向修复，而不是新增妥协。
  - 代价可控：接入方的改造集中在主进程加载链路（静态服务 + 可信来源判定 + 导航守卫），不涉及业务逻辑。
  - 唯一新增的服务端改动是 CORS 来源配置化，原因是实测证明浏览器 origin 会触发 CORS 校验（来源 2、来源 7）。
- 不选择其他方案的原因：
  - A（`file://` 白名单）：需要新增字段、迁移、签发分支与网关归一化改动，触碰数据模型/接口/鉴权三项停点；在用户允许改造加载方式后，其「改动小」的优势不再成立，且无法消除 `client_secret` 分发风险。
  - E 单独使用（不带 F）：加载方式虽然标准化，但 token 仍需要由某处持有 `client_secret` 的组件签发，风险项依旧存在，故 E 只作为 F 的加载前提保留。
  - B（客户端伪造 `Origin` 头）：客户端绕过服务端安全校验，服务端不可审计。
  - C（托管聊天页）：需要跨进程工具桥接，削弱接入方「远程页面不注入 preload/IPC」的既有边界，且增加部署面。
  - D（公共客户端 PKCE/设备授权）：标准且正确，但需要新增授权端点与客户端注册模型，超出本期范围，记入后续演进。
- 对后续 spec、plan 或人工确认的影响：本期不触发数据模型停点；触发「API 契约变化」停点（`shop-agent/session` 需支持按调用方指定 `agent_id`，向后兼容的可选参数）与「鉴权或权限行为变化」停点（CORS 允许来源 = 可配置 + 新增桌面来源，且 shop-agent 会话允许为目标 Agent 签发），进入实现前必须人工确认。

## 剩余风险

- 资料时效性：Electron 官方安全文档无版本号，行为结论以本机 electron@37.10.3 实测为准；接入方后续升级 Electron 时需要复测 `Origin` 与 CORS 行为。
- 方案切换后的新增风险：改动加载方式会改变接入方主进程的可信来源判定与导航守卫逻辑，属于其应用启动链路的关键路径，需要真机回归（窗口能正常加载、内部导航不被误拦截）。
- 复用 shop 链路的依赖：`shop-agent/session` 需要 ai-base 能访问 hua8（`STORE_OPS_BASE_URL`）；店铺 token 会写入 ai-base Redis（TTL 跟随 hua8 登录时效），属于既有机制但需在接入说明中明确告知。
- 与本项目上下文的差异：`client_secret` 随安装包分发是标准里点名的反模式（RFC 8252 §8.5），本期接受该风险，配套措施只有短 TTL、token/连接配额、密钥轮换与按客户端撤销；这些措施降低的是「泄露后的影响面」，不是「不泄露」。
- 尚未验证的假设：
  - 假设桌面端渲染层能正常调用本地后端换取 token（`file://` → `http://127.0.0.1` 的 fetch 实测可行，但接入方本地后端的实际启动顺序、端口与鉴权尚未联调）。
  - 假设 SDK 在 `file://` 渲染层中无运行时代码改动即可工作（Vue 组件挂载、localStorage 会话持久化、附件 blob 下载需在联调中验证）。
  - 假设接入方可以接受用固定本地端口（`http://127.0.0.1:<port>`）承载渲染层，并在打包/更新流程中保持该端口稳定。
  - 假设接入方桌面端与 `apps/shop` 可以使用同一个 Embed Client（桌面来源追加到该 Client 的 `allowed_origins`），若需独立 Client 则要额外设计会话接口的客户端选择方式。
  - 假设改造后 `base: "./"` 的相对资源路径在 http 加载下仍可用（Vite 相对路径在 http 下正常，需在联调中确认）。
