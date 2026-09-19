# 业界调研记录

## 调研问题

- 当前 Docker 部署中，`api` / `worker` / `wechat-bot-worker` 三个服务共用 `LOG_FILE_PATH=/app/logs/app.log`，并挂载同一个宿主机目录 `apps/backend/logs`，导致三者写入同一个 `app-<date>.log`。多服务（多进程）写同一日志文件会有什么后果，业界成熟做法是什么？
- 容器内未设置 `TZ`，`DatedFileHandler` 用 `date.today()` 决定文件名，日志时间戳由 `logging` 按容器本地时间生成。时区不一致会给日志落盘带来哪些问题，如何对齐？
- Docker 默认 `json-file` 日志驱动在未配置 `max-size` / `max-file` 时如何增长，生产上如何限制？
- 日志保留（轮转后保留多少份、何时清理）的常见策略是什么？

本次调研结果将影响：`docker-compose.yml` 的服务环境变量与日志驱动配置、`apps/backend/app/core/logging.py` 的 handler 与清理逻辑、`apps/backend/app/core/config.py` 的路径解析、以及 `.env*` 示例文件的日志相关配置项。

## 功能复杂度

- 级别：普通业务功能（日志基础设施改造，涉及可观测性与可靠性，但不新增业务接口）
- 选择理由：改动集中在部署配置与日志基础设施层；一旦出错会影响线上排障能力，属于"不影响业务功能但影响可运维性"的改造
- 最低调研要求：至少一个官方/权威来源 + 一个成熟开源项目或生产实践案例；涉及可靠性，需补充多进程写文件的安全性与磁盘占用控制调研

## 参考依据

### 来源 1：Python 标准库 `logging.handlers` 实现（本机可核验）

- 类型：官方实现源码（Python 标准库）
- 名称：`logging.handlers`，本机路径 `/Applications/Xcode.app/Contents/Developer/Library/Frameworks/Python3.framework/Versions/3.9/lib/python3.9/logging/handlers.py`（本机 python3 为 3.9.6；后端容器运行 Python 3.12，同一作者 Vinay Sajip 维护，handler 语义一致）
- 版本或发布日期：Python 3.9.6（Debian/Apple 发行版，2023-12-07 构建）
- 调研日期：2026-09-19
- 核心做法：
  - `FileHandler` 默认以 `mode='a'` 打开文件，写入是"追加"而非"截断"，但标准库没有任何跨进程写入序列化机制；
  - `WatchedFileHandler` 的 docstring 明确指出：配合 `newsyslog` / `logrotate` 等**外部轮转工具**时，才需要监听 inode 变化并重新打开文件；
  - `RotatingFileHandler` / `TimedRotatingFileHandler` 的轮转与清理都假设"该文件由当前进程独占管理"。
- 对本项目的启发：**多容器共写一个文件在标准库层面没有任何保护**（不会截断，但会互相穿插、互相触发清理），必须由我们自己在配置层把"一个服务一个文件"作为约束；同时说明：既然我们自己做轮转（`DatedFileHandler`），就**不应该**再让宿主机对同一目录做 logrotate，否则需要换成 `WatchedFileHandler`。

### 来源 2：Python 官方文档 Logging Cookbook —— "Logging to a single file from multiple processes"

- 类型：官方文档
- 链接：https://docs.python.org/3/howto/logging-cookbook.html#logging-to-a-single-file-from-multiple-processes
- 版本或发布日期：长期稳定章节（Python 3.x 文档，最近复核版本 3.13）
- 调研日期：2026-09-19
- 核心做法：该章节明确结论是**不支持多进程直接写同一个文件**，需要改为让一个进程（或独立进程/线程）持有文件 handler，其他进程通过 `QueueHandler` / `SocketHandler` 把日志汇聚过去，或者干脆每个进程写自己的文件。
- 对本项目的启发：本项目 `worker` 使用 Celery 默认 prefork 模型，主进程与子进程共享同一个 handler 实例（同一 fd），属于该章节描述的"多进程写同一文件"场景；在**不改架构（不引入队列汇聚）**的前提下，业界给出的下位替代就是"每个进程/服务写自己的文件"。这与用户确认的"按服务分文件"方向一致。
- 说明：本机网络受限，未能实时抓取该页面（详见"剩余风险"），依据为该文档长期稳定章节的既有结论。

### 来源 3：Docker 官方文档 —— 日志驱动与 JSON File 驱动配置

- 类型：官方文档
- 链接：
  - https://docs.docker.com/engine/logging/configure/
  - https://docs.docker.com/engine/logging/drivers/json-file/
  - https://docs.docker.com/compose/compose-file/05-services/#logging
- 版本或发布日期：Docker Engine / Compose v2 现行文档
- 调研日期：2026-09-19
- 核心做法：
  - 默认日志驱动为 `json-file`，默认**不限制单文件大小**（`max-size` 未设置即无限增长），默认 `max-file=1`；
  - 可在 `daemon.json` 的 `log-opts` 设置全局上限，也可在每个服务的 `logging.options` 中按服务覆盖（Compose 文件参考中的 `logging` 字段）；
  - 官方建议生产环境配合日志驱动把日志转发到集中式日志系统（本文档"Configure logging drivers"章节）。
- 对本项目的启发：容器 stdout（`docker logs`）与文件日志是两条独立链路，两者的磁盘占用都要管。文件日志由我们的 `DatedFileHandler` 管控；容器 stdout 侧需要在 Compose 里补 `logging.options.max-size/max-file`，否则 `/var/lib/docker/containers/*/*-json.log` 无上限增长。
- 说明：本机网络受限，未能实时抓取页面；依据为官方文档中稳定存在的默认值与配置项（`max-size` 未设置即无限、`max-file` 默认 1、`logging.options` 可覆盖）。

### 来源 4：本机仓库内其他项目的生产 Compose 实践（可核验案例）

- 类型：生产实践（本机现有工程）
- 名称：`/Users/lixingwen/xw/zhoudan/store-ops-web/ci/deploy/docker-compose-prod.yml`、`/Users/lixingwen/xw/git/middleground/mysql/docker-compose.yml`
- 版本或发布日期：本机现有版本（2026-09-19 读取）
- 调研日期：2026-09-19
- 核心做法：在这两个真实项目的 Compose 中，服务统一显式声明
  ```yaml
  logging:
    driver: "json-file"
    options:
      max-size: "50m"
      max-file: "1"
  ```
  即：生产 Compose 显式限制容器 stdout 日志体积，而不是依赖宿主机 Docker 守护进程的默认值。
- 对本项目的启发：本仓库 `docker-compose.yml` / `deploy/docker-compose.prod.yml` 目前完全没有任何 `logging` 配置，属于与既有生产项目不一致的缺口；补 `max-size` / `max-file` 是本仓库其他项目的既有约定，落地风险低。

### 来源 5：Twelve-Factor App —— Logs（补充对照）

- 类型：行业权威实践
- 链接：https://12factor.net/logs
- 版本或发布日期：12factor.net 现行版本
- 调研日期：2026-09-19
- 核心做法：应用不应自己管理日志文件，应把日志作为事件流写到 stdout/stderr，由运行环境负责收集、路由与归档。
- 对本项目的启发：12-factor 的正解是"只写 stdout"。但本项目的排障方式是直接看宿主机 `apps/backend/logs` 下的文件（且用户明确要求保留文件日志），因此本次不采用"纯 stdout"方案，而是**保留 stdout 的同时**把文件日志做成分服务、分目录，保留 12-factor 关于"不要在应用内做无边界归档"的约束（即必须有限额与保留策略）。

## 方案比较

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| A. 纯 stdout：去掉文件 handler，只靠 `docker logs` + json-file 限额 | 最符合 12-factor；无多进程写文件问题；容器重建后日志仍可查 | 排障需依赖 Docker 命令；`docker logs` 随容器重建丢失；用户明确要求写文件 | 中：作为补充保留（stdout 已有），不作为主方案 |
| B. 保留文件日志，按服务分目录分文件（`/app/logs/<service>/app-<date>.log`） | 直接消除多服务共写同一文件；保留现有按天滚动与查看习惯；改动集中在 Compose 环境变量 | 需要在 Compose 中为每个服务单独声明路径；宿主机目录结构变深一层 | 高：用户已确认该方向 |
| C. 多进程写同一文件 + 引入汇聚（`QueueHandler` / `SocketHandler` / SQL，或 `concurrent-log-handler` 文件锁） | 理论上可保持单文件 | 需要引入新依赖或新进程，改动面大，超出本次范围 | 低：本次不做，记录为后续可选演进 |
| D. 宿主机 logrotate 管理容器日志目录 | 复用系统能力 | 容器内 handler 必须改为 `WatchedFileHandler`，否则轮转后继续写旧 inode；跨容器协同删除风险更高 | 低：继续使用应用内自轮转（`DatedFileHandler`），不叠加外部轮转 |

## 最终决策

- 选择方案：**B（按服务分文件）为主，A 作为补充，C/D 不采用**
- 选择原因：
  1. Python 官方明确不支持多进程写同一文件（来源 1、2），在不改架构的前提下，"每个服务一个文件"是最小侵入且可解释的修正；
  2. 与本项目现状契合：`DatedFileHandler` 已实现按天滚动与保留，只需把"文件路径"从服务间共享改为服务级私有，并把清理边界收敛到各自目录；
  3. 用户已明确选择"写到文件里、按服务分文件"。
- 不选择其他方案的原因：
  - A：用户要求保留文件日志，且现网排障依赖文件；但仍保留 stdout 链路（`docker logs` 可用）；
  - C：需要引入新依赖或新进程，超出"日志落盘修正"的范围，且当前日志量（单日百 KB 级）不值得引入队列汇聚；
  - D：与容器内自轮转冲突（来源 1 明确指出 `WatchedFileHandler` 是配合外部轮转才需要），叠加两套轮转会带来重复删除风险。
- 对后续 spec、plan 或人工确认的影响：
  - 需要在 Compose 中为 `api` / `worker` / `wechat-bot-worker` 分别声明 `LOG_FILE_PATH`；
  - 需要统一容器时区（`TZ`），否则文件名日期与宿主机日期不一致的问题依然存在；
  - 本次不涉及架构边界、数据模型、API 契约与鉴权变更，但会改变日志落盘路径与容器环境变量，仍需在 spec 后按 Harness 要求完成方案确认。

## 剩余风险

- 资料时效性：本机沙箱网络不可用（`curl` 无法解析 `docs.docker.com`、`docs.python.org`），来源 2、3、5 为"链接 + 稳定章节结论"，未能在本次调研中实时抓取原文；来源 1、4 为本机可核验的一手材料。后续联网后应复核来源 3 的默认值表述（`max-size` 未设置即无限、`max-file` 默认 1）。
- 与本项目上下文的差异：
  - 来源 4 的案例使用 `max-file: "1"`（单文件覆盖式），本仓库需要保留一段时间的历史，取值会更宽松；
  - 12-factor（来源 5）主张纯 stdout，与本项目保留文件日志的选择存在理念差异，已在决策中显式说明取舍。
- 尚未验证的假设：
  - 宿主机 Docker 守护进程是否已在 `daemon.json` 配置全局 `log-opts` —— 本次尝试通过 `docker inspect` 核验时，沙箱对 Docker socket 的访问被拒绝，未能确认，因此按"未配置"做保守假设；
  - Celery prefork 子进程是否各自持有文件 handler 实例（影响"多进程写同一文件"的具体表现）—— 未在真实容器中验证，本次改动按最保守假设处理（服务内不再要求单文件）。
