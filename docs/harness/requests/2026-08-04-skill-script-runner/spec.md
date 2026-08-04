# Skill 脚本执行器规格

## 目标

- 让已导入技能包的脚本在智能体对话中作为结构化工具实际执行。
- 让现有 `allow_script_execution` 成为强制授权检查，而非仅写入提示词的状态。
- 使用独立 runner 隔离 API、数据库凭据和宿主写权限，并为每次执行保留审计证据。
- 方案依据 `research.md`：采用专用受限 runner 容器，不在 API/Celery 主工作进程内直接运行上传代码。

## 范围

### 执行边界

- 新增 `skill-runner` 内部服务，仅供 API 容器访问，不暴露宿主端口。
- runner 以非 root 用户运行，根文件系统只读，技能包目录只读挂载，临时目录使用受限 tmpfs。
- Compose 配置默认禁网或仅保留 API 到 runner 的专用内部网络；runner 不连接数据库、Redis 和外部网络。
- 配置 CPU、内存、PID、单次执行超时、stdout/stderr 和结果大小上限。
- 固定解释器白名单：`.py -> python3`、`.js/.mjs -> node`、`.sh -> /bin/sh`；禁止调用任意二进制、禁止 `shell=True`。

### 授权与校验

- 当前平台、智能体和 Skill 绑定必须有效且启用。
- Skill、SkillPackage 必须启用，且 `allow_script_execution=true`。
- `script_path` 必须命中该包的 `SkillPackageFile` 记录，且 `role=script`。
- 路径按 POSIX 相对路径规范化，拒绝绝对路径、路径穿越、符号链接逃逸和索引外文件。
- 参数使用字符串数组，限制参数数量、单项长度和总大小；stdin 首期不开放。
- 管理员打开包级脚本权限视为该包的持续授权；首期不增加每次调用人工确认。

### 运行时工具

- 对每个允许执行脚本的已绑定技能包，运行时注册唯一工具 `run_skill_script_<package_id>`。
- 工具输入：`script_path: string`、`arguments: string[]`。
- 工具描述列出该包允许执行的脚本相对路径，模型不能传入任意路径。
- 工具结果：`status`、`exit_code`、截断后的 `stdout`、`stderr`、`duration_ms`、`execution_id`。
- 对话 Graph 通过统一 invoke 回调区分 MCP 与 Skill Script 工具，并把执行结果作为 ToolMessage 返回模型。

### 数据模型与 API

- `SkillPackage` 新增稳定的 `storage_key`，不再依赖宿主绝对路径跨容器定位包目录；迁移回填现有记录。
- 新增 `SkillScriptExecution` 审计表，至少记录平台、包、Skill、智能体、调用用户/终端用户、会话、脚本路径、脱敏参数、状态、退出码、耗时、截断输出、错误和时间字段。
- 所有新增 ORM 字段添加中文 `comment`。
- 新增 `GET /api/v1/platforms/{platform_id}/skill-script-executions`，平台管理员分页查询执行审计。
- 内部 runner 协议使用共享密钥签名或短期 HMAC，请求包含执行 ID、storage key、脚本路径、参数和限制；runner 不接受平台 ID 作为文件路径。

### 前端

- 技能包列表显示可执行脚本数量和 runner 可用状态。
- 技能包详情展示脚本路径与支持的解释器。
- 新增脚本执行审计列表，可查看状态、耗时、退出码和截断输出，不展示敏感参数原文。
- 开启脚本权限时明确提示：仅允许受限 runner 执行，仍可能产生计算成本和脚本业务副作用。

## 非目标

- 不允许脚本访问 Docker Socket、宿主文件系统、数据库或 Redis。
- 不允许动态 `pip install`、`npm install` 或任意依赖安装。
- 不提供任意互联网访问；需要外部能力的 Skill 后续通过 MCP 或显式网络白名单实现。
- 不实现 microVM 级别隔离，也不承诺运行所有市场 Skill 的私有依赖。
- 不执行技能包根目录任意文件，只执行索引角色为 `script` 且解释器受支持的文件。

## 风险

- 架构风险：新增内部 runner 服务和对话工具类型，部署与运行时链路变长。
- 数据风险：新增审计表和 `storage_key` 回填迁移，需要验证现有绝对路径记录。
- API 风险：新增审计查询 API；运行时工具 schema 也会进入模型上下文。
- 权限风险：`allow_script_execution` 从提示状态升级为真实执行授权，误开启会改变智能体行为。
- 安全风险：容器隔离不是绝对边界；必须同时启用非 root、只读挂载、禁网、capability、资源和超时限制。
- 兼容风险：依赖第三方 Python/Node 包或外部网络的 Skill 会返回明确的运行失败。

## 停点判断

- 架构边界变化：是，新增专用 runner 服务。
- 数据模型变化：是，新增审计表和 `storage_key`。
- API 契约变化：是，新增审计查询 API 和内部 runner 协议。
- 鉴权或权限行为变化：是，脚本权限将控制真实执行。
- 人工确认：是，进入实现前必须确认上述完整方案。

## 验收标准

- 权限关闭时，模型运行时不注册脚本工具，任何直接调用均被拒绝且不启动进程。
- 权限开启且 Skill 已绑定时，模型可调用索引中的 Python、Node.js 或 shell 脚本并获得结构化结果。
- 索引外路径、路径穿越、不支持扩展名、过长参数和符号链接逃逸均被拒绝。
- runner 容器无数据库/Redis凭据、无 Docker Socket、非 root、包目录只读，并配置 CPU/内存/PID/超时/输出上限。
- 超时进程被终止，stdout/stderr 被截断，失败和成功均写入审计。
- 平台管理员可查看本平台审计，其他平台和非管理员不可访问。
- 对话非流式、SSE 和 Embed Gateway 路径均能正确处理 Skill Script 工具结果，不影响 MCP/Host Tool。
- 后端单元/集成测试、runner 契约测试、Compose 配置检查和前端静态检查通过。

## 变更记录

### 2026-08-04 第 3 次修复

- 变更原因：本地 Python API 即使使用开发 runner 端口，未设置 `SKILL_RUNNER_URL` 时仍默认请求 Docker DNS 名称，导致 502。
- 变更内容：开发环境默认 runner 地址改为 `http://127.0.0.1:8090`；Compose API 通过显式环境变量继续使用 `http://skill-runner:8090`。
- 影响章节：执行边界、部署验证。
- 是否触发人工确认：否，属于本地调试配置修复，不改变生产部署边界。
- 关联计划更新：验证本地 Python API 使用默认开发地址执行脚本。

### 2026-08-04 第 2 次变更

- 变更原因：本地 Python API 需要查看实时日志，但不能访问只存在于 Compose internal 网络的 runner。
- 变更内容：新增 `docker-compose.dev.yml`，仅开发模式将 runner 绑定到 `127.0.0.1:8090`，并使用只连接 runner 的开发网络；生产 Compose 保持无宿主端口暴露。
- 影响章节：执行边界、风险、部署验证。
- 是否触发人工确认：否，属于开发调试入口，不改变生产部署边界、权限语义或 API 契约。
- 关联计划更新：补充本地 Python API 调试启动方式。

### 2026-08-04 第 1 次修复

- 变更原因：真实 runner 探针发现 `0015` 对既有技能包回填的 `storage_key` 遗漏 `skill-packages/` 前缀，导致已迁移包执行时返回 500。
- 变更内容：修正新部署的 `0015` 回填表达式，新增 `0016` 纠正已执行迁移的数据库；runner 将文件不存在映射为 400，并新增回归测试。
- 影响章节：数据模型与 API、验收标准。
- 是否触发人工确认：否，属于已确认方案内的定位键修复，不改变架构、模型、API 或权限语义。
- 关联计划更新：验证阶段增加真实存储键迁移与 HTTP 执行探针。

### 2026-08-04 初始版本

- 变更原因：进入 Skill Zip B 方案下一阶段，实现包内脚本实际执行。
- 变更内容：定义独立受限 runner、执行授权、运行时工具、审计模型和前端审计能力。
- 影响章节：全部。
- 是否触发人工确认：是，涉及架构、数据模型、API 和权限行为变化。
