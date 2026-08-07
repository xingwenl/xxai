# 验收记录

## 验收结论

- 结论：后端实现达到 `spec.md` 的验收标准，可以进入迁移联调与管理端接入。
- 本次包含第一方内置工具注册表、Agent 显式绑定、安全 `http_get`、会话资源存储、双主体鉴权下载、后台/SSE/Embed 运行时接入和 Alembic 迁移。
- 本次没有实现 `web_search`、认证 GET、其他 HTTP 方法、网页正文抽取、匿名下载或文件预览，范围符合非目标约束。

## 逐项验收

### 工具注册与授权

- 通过：管理员可以读取代码工具目录并按所属平台 Agent 启停 `http_get`。
- 通过：绑定查询校验 Agent 平台归属；运行时只加载已启用绑定，执行前再次检查绑定状态。
- 通过：绑定归属 Agent，与 AgentVersion 发布/回滚解耦。

### HTTP 行为

- 通过：JSON、文本、图片和普通文件按稳定结构返回；二进制只返回 `asset_id` 和下载路径，不向模型写 Base64。
- 通过：仅允许无自定义认证的 GET，禁用环境代理，30 秒总预算、3 次重定向、1 MiB 文本/JSON 和 25 MiB 文件上限已实现。
- 通过：`Content-Length` 预检查和流式实际字节累计同时生效；HTTPX 解压后的流仍受上限控制。
- 通过：非 2xx、超时、非法编码、超限和存储异常映射为稳定错误，不回传响应正文或堆栈。

### SSRF 与文件安全

- 通过：协议、URL 凭证、主机、全部 IPv4/IPv6 解析结果和每次重定向均校验；任一非公网地址即拒绝。
- 通过：文件名安全化，未知二进制类型降级为 `application/octet-stream`，下载强制 `attachment` 和 `nosniff`。
- 通过：取消、超限、流式错误和数据库写入失败均执行临时文件或最终文件补偿清理。
- 部署条件：生产环境仍需网络出口策略，应用层校验不能完全消除 DNS rebinding 时间窗口。

### 资源隔离

- 通过：资源记录包含平台、Agent、Conversation 和且仅一个后台用户/Embed 最终用户，数据库有检查约束。
- 通过：后台下载按用户匹配；Embed 下载同时匹配平台、Agent 和最终用户；内部 `storage_key` 不进入 API。
- 通过：最终 URL 与来源 URL 移除查询参数和片段；HTTPX/HTTPCore INFO 日志被关闭，避免完整 URL 进入应用日志。

### 工具调用链与工程验证

- 通过：后台非流式、后台 SSE 和 Embed Gateway 均加载同一内置工具定义和执行服务。
- 通过：模型工具循环定向测试确认调用进入本地执行器，步骤类型为 `builtin_tool`，结果回填后模型继续生成。
- 通过：全量 `225 passed, 1 skipped`，Ruff、定向 Black、OpenAPI、离线 Alembic SQL 和差异检查通过。
- 通过：MCP、Skill、Host Tool 与现有 conversation/gateway 回归未发现行为回归。

## 变更文件概览

- 新增：`app/modules/builtin_tool/`、`app/modules/asset/`、`20260807_0019` 迁移和对应测试。
- 修改：配置、日志、应用路由、conversation runtime/service/router、gateway runtime/router、Alembic 模型导入。
- 文档：当前 Harness request 的 research、spec、plan、verify、acceptance 和 meta。

## 剩余风险

- 真实 PostgreSQL 迁移与生产出口策略尚未在当前环境验证，部署前必须执行。
- 当前没有通用资源生命周期任务，长期运行需要监控 `storage/assets/` 增长。
- 首期不扫描恶意文件，资源只能鉴权下载，不应改为浏览器匿名内联预览。
- 默认 `pytest -q` 仍受仓库既有同名测试模块收集冲突影响；使用 `--import-mode=importlib` 可完整运行。

## 合并判断

- 后端代码和文档可以提交或合并。
- 上线前置条件：数据库备份、执行 `alembic upgrade head`、配置并验证网络出口阻断规则。

## 2026-08-07 管理端与 SDK 增量验收

- 通过：智能体列表每行新增“内置工具”图标入口，保持现有 Tooltip 和 Dialog 交互。
- 通过：弹窗按 Agent 加载工具目录，展示加载占位、失败重试、空状态、说明、副作用标识和启停开关。
- 通过：每个工具独立维护提交状态；成功后精确更新查询缓存，失败时保留服务端状态并提示错误。
- 通过：前端 API 复用既有查询和更新契约，没有修改后端 API、数据模型或权限语义。
- 通过：SDK `AgentLoopStepType` 已包含 `builtin_tool`，过程面板和消息摘要均将其归类为“调用工具”。
- 通过：管理端生产构建和定向 ESLint、SDK 类型检查/构建/34 个单测/包入口校验、差异检查全部通过。
- 例外：因本地浏览器会话未登录，未执行真实 UI 启停写操作；全量前端 ESLint 仍有 5 个无关既有错误。
- 结论：本次增量达到代码与自动化验收标准，可以由管理员登录后进行一次实际启停联调。
