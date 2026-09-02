# 设计说明：智能体接入店铺运营项目（查询我的店铺）

## 目标

- 解决什么问题：在 `ai-base` 智能体上新增「店铺运营项目」能力。用户先登录店铺系统（hua8），再打开智能体页面，提问「查询我的店铺」时，智能体通过服务器端工具查询该登录用户的店铺信息并回答。
- 目标用户/调用方：店铺运营系统（hua8）的登录用户；调用链路为「新前端 `apps/shop/`（vite-vue）→ ai-sdk（WebSocket）→ ai-base 后端业务工具 → hua8 API」。
- 完成后可验证结果：用户登录店铺系统后在智能体页面问「我的店铺」，智能体返回该用户（按店铺 token 鉴权）的店铺列表；token 过期或接口报错时，智能体原样透传 hua8 的错误。
- 引用 `research.md` 关键结论：采用「服务器工具 + 店铺 token 会话级透传」方案——ai-base 新增业务工具 `store_ops_query`，token 在建会话时注入并存入 Redis（TTL 跟随店铺 token 时效），不进消息 payload；企业实践要求工具内鉴权、只读白名单、错误对模型可见。

## 范围

### 新前端 `apps/shop/`（新增，vite-vue 独立项目）

- 登录页：调 hua8 `GET /hua8-api/code`（验证码）与 `POST /hua8-api/auth/login`，成功后持有 `access_token`（有效期 43200 秒）与 `user_id`（JWT payload 或登录后用户信息），存浏览器内存/会话（不落库）。
- 聊天页：ai-sdk 以 `embedded` 模式渲染（新开页面）。
- `getToken`：调用 ai-base 新增 `POST /api/v1/shop-agent/session`（入参 `{shopToken, shopUserId}`），返回 ai-base 签发的 embed access_token；`client_secret` 不进浏览器。
- 可选：注册 `ShopList` 自定义组件渲染店铺列表（`registerCustomComponent`），未注册时展示 fallback 文本。

### ai-base 后端（本仓库）

- 新增接口 `POST /api/v1/shop-agent/session`：
  - 入参：`shopToken`、`shopUserId`（浏览器持有）；
  - 服务端把 `shopToken` 加密存入 Redis（key 与 `external_user_id` 关联，TTL=43200，跟随店铺 token 时效）；
  - 复用现有 Embed Token 链路（`EMBED_CLIENT_ID` / `EMBED_CLIENT_SECRET` / `EMBED_AGENT_ID`）签发 embed access_token，`external_user_id = shopUserId`；
  - 可选加固：用 `shopToken` 调 hua8 用户信息接口核对 `user_id`，防止伪造（接口是否存在实现时确认）。
- 扩展 `BusinessToolContext`：新增 `shop_token` / `shop_user_id` 字段，构造时从 Redis 按当前 `external_user_id` 读取（注入点：embed 会话上下文）。
- 新增业务工具（`apps/backend/app/modules/tools/shop/` 分层）：
  - 名称 `store_ops_query`，MVP 仅 `action=list_my_shops`（查询我的店铺）；
  - handler：用 `ctx.shop_token` 调 hua8 `POST /hua8-api/shop/platform/list`（`Authorization: Bearer <shop_token>`），**响应与错误透传**（含 401 过期）；
  - 未注入 token 时返回 `store_ops_not_authenticated`；网络/网关异常映射稳定错误码。
- 展示工具 `show_shop_list`（`tools/shop/ui/`）：仅当用户明确要求展示店铺列表时渲染 `ShopList` 卡片，数据复用 `tools/shop/data/client.py` 的真实查询，不允许模型编造。
- 注册：`tools/shop/registry.py` 汇总 ui/data 层工具，`tools/business/registry.py` 作为统一总注册页聚合导入。
- 配置：`STORE_OPS_BASE_URL`（hua8 API 地址）、`STORE_OPS_REDIS_TTL_SECONDS`（默认 43200）等。
- 测试：`apps/backend/tests/` 新增 mock hua8 的用例（列表、401、未注入 token、网络异常）。
- 返回结构：数据层 `store_ops_query` 返回纯数据（`kind=store_ops_shop_list`，字段名与 hua8 响应一致）；UI 层 `show_shop_list` 返回 `kind=custom` 的 ShopList 渲染块（`props.shops` 用 hua8 原字段含 `tagList`）。查询信息与展示卡片解耦，避免每次问店铺问题都弹组件。

### 店铺系统 hua8

- 零改动：复用验证码登录、`auth/login`、`shop/platform/list` 接口。

## 非目标

- 不在 ai-base 新增持久化数据表（店铺 token 仅存 Redis，TTL 跟随店铺 token 时效，不落库）。
- 不做 token 过期后的自动刷新/重新授权引导流程（本次按「接口报什么错就报什么错」处理，过期方案后续单独设计）。
- 不做「店铺里的产品」查询、改价、上下架、改店铺信息等后续操作（工具契约预留 `action` 枚举扩展位，本轮只实现 `list_my_shops`）。
- 不改 `message_send` WebSocket 协议（token 走会话级注入，不进消息 payload）。
- 不做用户绑定表持久化（`external_user_id = shopUserId` 会话内有效）。

## 风险

- 店铺 token 安全：token 从浏览器传到 ai-base（会话接口走 HTTPS）；ai-base 只存 Redis 不落库；不进日志、不进消息审计。
- `shopUserId` 伪造风险：浏览器可伪造入参。MVP 信任前端传入，风险点记录；实现时优先用 `shopToken` 调 hua8 用户信息接口校验（需确认接口存在）。
- 跨域/网络：浏览器调 hua8 登录接口需 hua8 允许跨域或经代理；ai-base → hua8 为服务端调用，无 CORS 问题（登录发生在浏览器，查询发生在服务端）。
- 联调风险：依赖 hua8 真实环境（验证码登录、真实店铺数据）；mock 测试覆盖本地，真实联调记录在 `verify.md`。
- 回归风险：仅新增接口、工具上下文字段与业务工具，以现有 `pytest`、ruff 与 SDK 协议测试作为回归基线。

## 停点判断

- 是否涉及架构边界变化：是（ai-base 新增外部系统集成面与店铺会话接口；新增 `apps/shop/` 前端项目）→ 进入实现前需人工确认
- 是否涉及数据模型变化：否（不新增数据库表；店铺 token 仅存 Redis）
- 是否涉及 API 契约变化：是（新增 `POST /api/v1/shop-agent/session`；新增 `store_ops_query` 工具契约）→ 进入实现前需人工确认
- 是否涉及鉴权或权限行为变化：是（ai-base 接收并持有店铺系统 token，按用户签发 embed token）→ 进入实现前需人工确认
- 结论：进入实现前需人工确认。待确认项：① `apps/shop/` 作为新前端项目目录；② hua8 用户信息校验接口是否存在；③ Embed Client 配置（`EMBED_CLIENT_ID/SECRET/AGENT_ID`）已就绪。

## 验收标准

- [ ] ai-base 新增 `POST /api/v1/shop-agent/session`：入参 `shopToken/shopUserId` 校验、Redis 写入（TTL 43200）、返回 embed access_token。
- [ ] `BusinessToolContext` 支持 `shop_token`/`shop_user_id`，embed 会话中工具可读到注入值。
- [ ] `store_ops_query` 注册后 `list_business_tools()` 包含该工具；未注入 token 时返回 `store_ops_not_authenticated`。
- [ ] mock 测试通过：店铺列表、401（token 过期）、未注入 token、网络异常四类场景（`poetry run pytest tests/ -k store_ops -q` 全绿，具体命令以仓库现有测试入口为准）。
- [ ] 相关既有测试无回归：`tests/builtin_tool`、`tests/gateway`、`tests/embed` 全绿；ruff 无新增错误。
- [ ] `apps/shop/` 前端可构建（`pnpm build` 成功），登录页 + embedded 聊天页可用本地 mock/开发环境联调。
- [ ] 人工联调（记录在 `verify.md`）：真实 hua8 环境登录后提问「查询我的店铺」，返回该用户店铺列表；token 过期后错误原样透传。
- [ ] 文档闭环：六份文档齐全，`meta.json` 阶段与状态一致，`tools/harness/audit.py` 无新增 ERROR。

## 变更记录

### 2026-09-02 第 6 次变更（店铺列表筛选参数透传）

- 变更原因：用户提供 hua8 店铺列表接口完整筛选入参（平台类型/绑定/同步/营业/在线/授权状态、关键词、标签、负责人、主体、店铺 ID 列表等），要求店铺查询支持按条件筛选
- 变更内容：`tools/shop/data/client.py` 新增 `SHOP_LIST_FILTER_KEYS` 并支持 `fetch_my_shops(filters=...)` 原样并入 POST body；`store_ops_query.list_my_shops` 的 input_schema 增加对应可选筛选参数；分页仍用抓包验证的 `page/page_size`（用户 JSON 中为 pageNum/pageSize，联调确认后再定）
- 影响章节：范围（store_ops_query 契约）、测试
- 是否触发人工确认：是（工具入参契约扩展；用户直接提供参数清单要求修改）

### 2026-09-02 第 5 次变更（接入订单查询接口 order_query）

- 变更原因：用户要求接入店铺运营平台订单接口（`GET /hua8-api/order/manage/orders`），询问订单数据时使用
- 变更内容：新增独立数据工具 `order_query`（`tools/shop/data/order_query.py`，不并入 store_ops_query，避免不同接口参数互相污染）；`tools/shop/data/client.py` 抽出公共 `_request` 并新增 `fetch_orders`/`ORDER_FIELDS` 白名单（剔除手机号、骑手/发货人电话、`op_desc` 等隐私字段）；时间入参 `start_date/end_date`（YYYY-MM-DD，Asia/Shanghai 转 epoch）
- 影响章节：范围（shop/data 工具集）、测试、meta 相关路径
- 是否触发人工确认：是（工具契约与字段白名单已获用户确认：独立工具名 `order_query`、白名单不含电话等隐私字段、日期入参格式）

### 2026-09-02 第 4 次变更（工具分层与查询/展示解耦）

- 变更原因：store_ops_query 直接输出渲染块导致「每次问店铺相关信息都弹 ShopList」；且店铺工具混在通用 business 层不清晰
- 变更内容：`tools/` 新增 `shop/ui` + `shop/data` 分层——`store_ops_query` 迁移到 `tools/shop/data/` 并回退为纯数据查询（不再输出 custom 渲染块）；新增 `tools/shop/ui/show_shop_list.py` 负责渲染 ShopList 卡片（复用 `tools/shop/data/client.py` 的真实 hua8 查询）；删除通用 demo `tools/business/shop_list.py`；`tools/shop/registry.py` 汇总后由 `tools/business/registry.py` 统一聚合，注册名 `store_ops_query`/`show_shop_list` 不变
- 影响章节：范围（工具目录与契约）、前端组件（不变）、测试（路径与断言更新）、ai-sdk README 9.2/9.4
- 是否触发人工确认：是（架构边界变化与 demo 删除已获用户确认：① 删除 demo shop_list；② business/registry.py 保留为统一总注册页）

### 2026-09-02 第 3 次变更（店铺展示输出规范）

- 变更原因：联调中发现模型会在 Markdown 里逐条复述店铺明细，与 ShopList 卡片重复
- 变更内容：`store_ops_query` 工具描述增加输出规范——调用成功只输出简短总览（如「共 N 家店铺，明细见下方卡片」），不逐条罗列店铺信息，明细交由 ShopList 卡片渲染
- 影响章节：范围（`store_ops_query` 描述）
- 是否触发人工确认：是（输出形态方案已获用户确认：A 方案「一句话结论 + 卡片明细」）

### 2026-09-02 第 2 次变更（店铺列表渲染对齐 hua8 移动端字段）

- 变更原因：用户确认店铺运营平台（hua8）为移动端平台，要求组件展示结构与平台原字段统一，避免模型经通用 demo 工具（`show_shop_list` 的 `name/address/status`）编造或改写店铺数据
- 变更内容：`store_ops_query.list_my_shops` 由「纯文本数据结果」改为返回 `kind=custom` 的 ShopList 渲染块——`props.shops` 直接使用 hua8 原字段（新增 `tagList` 白名单），`fallback` 由后端按店铺名生成；`apps/shop` 的 `ShopList.vue` 重做为移动端列表卡片，展示 `platformStoreName`/`principalUserName`/`platformStoreId`/`tagList`；通用 demo 工具 `show_shop_list` 保留为 SDK 示例不参与业务查询
- 影响章节：范围（store_ops_query 返回契约）、前端组件、测试（`tests/tools/test_store_ops_query.py` 断言更新）
- 是否触发人工确认：是（工具返回契约调整；字段清单与展示形态已获用户逐点确认）
- 关联计划更新：无需改动 `plan.md`（渲染对齐属实现细节），已同步 `verify.md` 与 `meta.json`

### 2026-09-02 第 1 次变更（方案重定）

- 变更原因：与用户讨论后确认需求形态（用户级绑定、token 时效跟随店铺系统、服务器工具、新前端 + ai-sdk embedded），原「平台级共享账号 + API Key 网关」方案不再适用
- 变更内容：方案改为「店铺 token 会话级透传 + 服务器业务工具」——新增 `apps/shop/` 前端（登录页 + ai-sdk embedded）、ai-base 新增 `POST /api/v1/shop-agent/session`、`BusinessToolContext` 注入 `shop_token/shop_user_id`、`store_ops_query`（MVP 仅 `list_my_shops`）；删除原运营平台网关接口设计
- 影响章节：目标、范围、非目标、风险、停点判断、验收标准（全部）
- 是否触发人工确认：是（架构边界、API 契约、鉴权变化；方案本身已获用户逐点确认，待确认目录/配置/联调细节）
- 关联计划更新：已同步更新 `plan.md` 与 `research.md`（方案修订章节）

### 初始版本

- 时间：2026-09-02
- 变更原因：首次创建 request（用户发起 `/new 店铺运营项目功能`）
- 变更内容：确定方案 B（运营平台 AI 只读网关 + ai-base `store_ops_query` 业务工具），完成目标、范围、风险、停点判断与验收标准
- 影响章节：全部
- 是否触发人工确认：是（架构边界、API 契约、鉴权变化）
