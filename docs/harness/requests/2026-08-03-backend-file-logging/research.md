# 业界调研记录

## 调研问题

- 当前后端只有控制台日志，服务运行时没有稳定写入本地文件的日志。
- 本次调研需要确定后端本地文件日志的实现方式、滚动策略、配置方式和对现有 FastAPI 应用的集成边界。

## 功能复杂度

- 级别：小功能
- 选择理由：本次只增强已有 `app/core/logging.py` 的日志输出目标，不新增业务模块、不修改数据库、不修改 API 契约、不改变鉴权或权限语义。
- 最低调研要求：至少参考一个官方来源和一个成熟实践来源，比较标准库文件日志、时间滚动日志和第三方日志库方案。

## 参考依据

### 来源 1

- 类型：官方文档
- 名称：Python 3.12 `logging.handlers.RotatingFileHandler`
- 链接：https://docs.python.org/3.12/library/logging.handlers.html#rotatingfilehandler
- 版本或发布日期：Python 3.12 文档
- 调研日期：2026-08-03
- 核心做法：使用标准库 `RotatingFileHandler` 按文件大小滚动日志，并通过 `maxBytes` 与 `backupCount` 控制单个日志文件大小和保留份数。
- 对本项目的启发：可以不新增依赖，在已有 `logging.config.dictConfig` 基础上增加文件 handler，实现本地日志落盘与容量控制。

### 来源 2

- 类型：官方文档
- 名称：Python 3.12 `logging.config.dictConfig`
- 链接：https://docs.python.org/3.12/library/logging.config.html#logging.config.dictConfig
- 版本或发布日期：Python 3.12 文档
- 调研日期：2026-08-03
- 核心做法：通过字典配置统一声明 formatter、handler、logger 和 root logger，handler 参数会传入对应 handler 构造函数。
- 对本项目的启发：项目当前已经使用 `dictConfig`，继续扩展配置字典比引入新初始化流程更符合现有结构。

### 来源 3

- 类型：官方文档
- 名称：Uvicorn Logging
- 链接：https://www.uvicorn.org/settings/#logging
- 版本或发布日期：Uvicorn 当前官方文档
- 调研日期：2026-08-03
- 核心做法：Uvicorn 支持通过 logging 配置控制日志输出，ASGI 服务日志仍基于 Python logging 生态。
- 对本项目的启发：保持标准库 logging 兼容性，后续如需接管 Uvicorn access/error logger，可以在同一配置体系内扩展。

### 来源 4

- 类型：成熟框架实践
- 名称：Django Logging
- 链接：https://docs.djangoproject.com/en/4.2/howto/logging/
- 版本或发布日期：Django 4.2 文档
- 调研日期：2026-08-03
- 核心做法：生产项目常通过字典配置组合 console/file handler，并用环境差异控制日志级别和输出目标。
- 对本项目的启发：本项目应把日志路径、文件大小和保留份数收口到配置层，避免在业务代码中分散读取环境变量。

## 方案比较

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| 标准库 `RotatingFileHandler` 按大小滚动 | 无新增依赖；与现有 `dictConfig` 完全兼容；可控制磁盘占用；适合本地和轻量部署 | 不按自然日期切分；按日期排查时不够直观 | 中 |
| 标准库 `TimedRotatingFileHandler` 按时间滚动 | 轮转后的历史文件会带日期后缀；同样无需新增依赖 | 当前正在写入的文件仍是 `app.log`，不符合用户希望当前文件带日期的直觉；若日志量突增，单日文件可能过大 | 中 |
| 自定义 `DatedFileHandler` 当前文件按日期命名 | 当前正在写入的文件就是 `app-YYYY-MM-DD.log`；跨天后自动切换到新日期文件；无需新增依赖 | 需要维护少量自定义 handler 代码；不是标准库开箱即用行为 | 高 |
| 引入 Loguru 或 structlog | API 更友好；结构化日志能力更强；扩展丰富 | 新增依赖和迁移成本；需要统一团队使用方式；当前需求过重 | 低 |

## 最终决策

- 选择方案：在现有 `app/core/logging.py` 中增加基于标准库 `FileHandler` 的 `DatedFileHandler`，当前活跃日志文件直接命名为 `app-YYYY-MM-DD.log`，并保留控制台日志。
- 选择原因：用户反馈 `TimedRotatingFileHandler` 仍写入 `app.log`，这符合标准库语义但不符合“文件名带日期”的实际期望；自定义轻量 handler 可以让当前文件立即带日期，并保持现有 `get_logger` 调用方式不变。
- 不选择其他方案的原因：按大小滚动不符合用户最新偏好；`TimedRotatingFileHandler` 只给轮转后的旧文件加日期；第三方日志库会增加依赖和学习成本，不符合本次小功能的范围。
- 对后续 spec、plan 或人工确认的影响：本次不触发架构边界、数据模型、API 契约、鉴权或权限行为变化，不需要额外人工审批。

## 剩余风险

- 资料时效性：Python logging 标准库能力稳定，资料时效风险低；Uvicorn 日志配置后续版本可能有细节变化，但本次未直接修改 Uvicorn 启动参数。
- 与本项目上下文的差异：当前项目主要通过应用启动时 `setup_logging(settings.log_level)` 初始化日志，若生产部署另行使用外部 supervisor 或容器日志采集，文件日志路径需由环境变量明确配置。
- 尚未验证的假设：默认 `apps/backend/logs` 目录在本地运行时可创建并写入；将在测试和验证阶段覆盖目录创建与日期文件写入。跨日切换逻辑由 handler 在每次 emit 前检查日期，未通过等待真实跨日进行端到端验证。
