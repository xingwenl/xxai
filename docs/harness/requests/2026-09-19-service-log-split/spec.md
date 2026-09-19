# 设计说明

## 目标

- 解决 Docker 部署下"日志看起来被覆盖/丢失"的可运维性问题。已定位的真实原因有三个，全部来自仓库与真实日志文件的可核验证据：
  1. `api` / `worker` / `wechat-bot-worker` 三者共用 `LOG_FILE_PATH=/app/logs/app.log`，且都挂载 `apps/backend/logs`，写入同一个 `app-<date>.log`（证据：`apps/backend/logs/app-2026-09-18.log` 中同时存在 `app.modules.*`、`celery.*`、`__main__` 三来源日志）；
  2. 容器内未设置 `TZ`，`DatedFileHandler` 用 `date.today()`（容器 UTC）决定文件名，日志时间戳也是 UTC，比宿主机 CST 早 8 小时。当前时刻（2026-09-19 01:25 CST = 09-18 17:25 UTC）的活跃日志全部落在 `app-2026-09-18.log`，而 `app-2026-09-19.log` 只有本机 dev 进程写入的 294 字节，看起来就像"今天的日志被覆盖了"；
  3. `wechat-bot-worker` 每分钟一行 `wechat bot supervise running=...` 心跳，占 `app-2026-09-18.log` 1593 行中的 722 行（45%），真实业务日志被淹没。
- 目标对象：使用 Docker Compose 部署本仓库的开发与运维人员（`deploy/deploy.sh` 使用者）。
- 完成后应产生的可验证结果：宿主机 `apps/backend/logs/` 下出现按服务隔离的目录，每个目录内的 `app-<date>.log` 只包含该服务日志；文件名日期与日志时间戳与宿主机 CST 一致；容器 stdout 日志有体积上限。
- 调研结论引用：Python 官方明确不支持多进程写同一日志文件（`research.md` 来源 1、2），在不引入 `QueueHandler` 汇聚进程的前提下，"每个服务一个文件"是最小侵入修正；Docker `json-file` 驱动在未配置 `max-size` / `max-file` 时无上限增长（来源 3），本机其他生产项目已在 Compose 中显式限额（来源 4）。

## 范围

包含：

- `docker-compose.yml`
  - 从共享锚点 `&backend-environment` 中移除 `LOG_FILE_PATH`，改为在 `api` / `worker` / `wechat-bot-worker` 三个服务上分别声明：
    - `api` → `/app/logs/api/app.log`
    - `worker` → `/app/logs/worker/app.log`
    - `wechat-bot-worker` → `/app/logs/wechat-bot/app.log`
  - 在 `&backend-environment` 中新增 `TZ: ${TZ:-Asia/Shanghai}`，与 `db` 服务及宿主机保持一致。
  - 新增顶层 `x-logging` 锚点并在全部服务上引用，为容器 stdout 日志设置 `driver: json-file` + `max-size` / `max-file` 上限。
- `apps/backend/app/core/logging.py`
  - `DatedFileHandler` 支持"启动时清理一次过期日志"，不再只在跨天时才清理。
  - 保留数量的语义明确为"保留最近 N 个日期文件"，清理范围严格限定在同一目录、同一 `app-*.log` 前缀，避免误删其他服务目录。
- `apps/backend/app/core/config.py`
  - `LOG_FILE_PATH` 若配置为相对路径，统一按 `BASE_DIR`（`apps/backend`）解析，消除对容器/本地工作目录（CWD）的隐式依赖；绝对路径行为不变。
  - `LOG_FILE_BACKUP_COUNT` 默认值由 5 调整为 14（保留 14 天），仍可用环境变量覆盖。
- `apps/backend/app/modules/wechat_bot/worker.py`
  - 每分钟心跳改为"状态变化时 INFO，状态未变化时 DEBUG"，消除 45% 的噪音。
- `deploy/deploy.sh`
  - 启动容器前 `mkdir -p` 创建 `apps/backend/logs/{api,worker,wechat-bot}`，避免 Docker 在宿主机上以 root 身份创建目录带来的权限不确定。
  - 部署完成提示中的日志查看方式更新为新的分服务路径。
- 配置示例与死配置清理：`.env.example`、`deploy/.env.prod.example`、本机 `.env`、`apps/backend/.env`
  - 删除已无代码引用的 `LOG_FILE_ROTATION_WHEN`、`LOG_FILE_ROTATION_INTERVAL`。
  - 补充"每个服务通过 `LOG_FILE_PATH` 区分文件"的注释说明。
- `apps/backend/tests/system/test_logging.py`：补充按服务路径、启动清理、保留数量三个方向的用例。
- `docs/CHANGELOG.md`：记录本次变更。

涉及的目录或模块：仓库根 `docker-compose.yml`、`deploy/`、`apps/backend/app/core/`、`apps/backend/app/modules/wechat_bot/`、`apps/backend/tests/system/`、`docs/`。

若为增量任务，说明与原闭环的关系：本次为新建 request，不属于已有闭环的增量。

## 非目标

- 不引入集中式日志系统（ELK / Loki / 云日志服务），不引入 `QueueHandler` / `SocketHandler` / `concurrent-log-handler` 等跨进程汇聚方案（记录在 `research.md` 方案 C，留待后续按需演进）。
- 不改动 `nginx`（`front` 容器）、`db`、`redis`、`skill-runner` 的日志内容与落盘方式；它们继续保持 stdout-only，仅继承新增的 `json-file` 体积上限。
- 不做宿主机 `logrotate` 与容器内轮转的叠加（`research.md` 方案 D 已说明风险）。
- 不新增日志查询接口、日志级别动态调整接口，不修改任何 HTTP 接口契约。
- 不处理本次顺带发现的其他问题（例如 `.env.example` 中存在的明文 `EMBED_CLIENT_SECRET`），仅在交付说明中提示。

## 风险

- 落盘路径变更导致排障习惯改变：`apps/backend/logs/` 下会新增 `api/`、`worker/`、`wechat-bot/` 三个子目录，旧路径 `apps/backend/logs/app-<date>.log` 不再有新内容写入。缓解：`deploy.sh` 输出与 `docs/CHANGELOG.md` 中明确新路径；旧文件不删除，保留历史可查。
- 时区变更的影响面：新增 `TZ=Asia/Shanghai` 会改变容器本地时间，进而影响 `date.today()`、`logging` 时间戳以及任何使用本地时间的代码路径。缓解：统一到宿主机时区后行为更可预期；数据库时间戳为 `timestamptz`/UTC 存储，不受影响；`wechat-bot` 的登录凭据持久化只存文件与游标，不依赖本地时区。
- 历史兼容性：`.env` 中删除 `LOG_FILE_ROTATION_*` 对运行时代码无影响（`config.py` 未读取这两个键，已核实），但用户本地若有其他脚本读取需要自查。
- 日志量增加带来的磁盘占用：分服务后文件数量从 1 份/天变为 3 份/天，14 天保留意味着最多约 42 个文件。缓解：单日单服务日志当前为百 KB 级，总量可控；`json-file` 侧另有 10m × 5 上限。
- 回归风险：`config.py` 相对路径解析基准变化（CWD → `BASE_DIR`）会改变"以相对路径配置 `LOG_FILE_PATH` 且工作目录不在 `apps/backend`"这一场景的落盘位置。缓解：容器内 CWD 与本地 dev CWD 均导致相同结果，行为实际收敛；测试覆盖相对路径解析。
- 数据风险：无数据模型变更，不涉及迁移。
- 未验证项：宿主机 Docker 守护进程是否已有全局 `log-opts` 无法在本机核验（Docker socket 提权被拒），因此本次在 Compose 层显式声明，属于叠加而非冲突配置。

## 停点判断

- 是否涉及架构边界变化：否（仍为"应用内写文件 + stdout 双通道"，未引入新的日志汇聚组件）
- 是否涉及数据模型变化：否
- 是否涉及 API 契约变化：否
- 是否涉及鉴权或权限行为变化：否
- 若任一项为"是"，必须明确写"进入实现前需人工确认"：**本次四项均为否，不触发强制审批条件；但按 Harness 规则，`spec.md` 完成后仍需先与用户对齐方案（含时区统一、相对路径解析基准、保留 14 天三个决策点）再进入 `plan` 与实现。**

## 验收标准

1. `docker-compose.yml` 中 `api` / `worker` / `wechat-bot-worker` 的 `LOG_FILE_PATH` 互不相同，且均位于 `/app/logs/<service>/app.log`；`docker compose config` 渲染无报错。
2. `&backend-environment` 包含 `TZ: ${TZ:-Asia/Shanghai}`，且 `api` / `worker` / `wechat-bot-worker` 三个服务的容器内 `date` 与宿主机 CST 一致。
3. 全部服务在 Compose 中声明 `logging.driver=json-file` 且带 `max-size` / `max-file`。
4. 宿主机 `apps/backend/logs/` 下出现 `api/`、`worker/`、`wechat-bot/`，各目录内 `app-<date>.log` 只包含本服务日志（按 logger 名与来源进程可区分，且不再出现 `celery.*` 混在 `api` 目录的情况）。
5. `setup_logging` 启动时会清理超出保留数量的历史文件，且不会删除其他服务目录或非 `app-*.log` 文件；新增用例通过。
6. `wechat-bot-worker` 在状态未变化时不再每分钟产生 INFO 心跳；状态变化时仍能打印一条 INFO。
7. `LOG_FILE_BACKUP_COUNT` 默认 14，`.env*` 示例中不再出现 `LOG_FILE_ROTATION_WHEN` / `LOG_FILE_ROTATION_INTERVAL`。
8. `apps/backend/tests/system/test_logging.py` 全部通过，且不破坏 `apps/backend` 既有测试。
9. `docs/CHANGELOG.md` 已记录本次变更。

## 变更记录

### 初始版本

- 时间：2026-09-19
- 变更原因：首次创建 request，修复 Docker 多服务日志共写同一文件、容器 UTC 时区导致日志文件名错位、心跳噪音淹没真实日志、stdout 日志无体积上限四类问题
- 变更内容：建立本次任务的初始设计说明
- 影响章节：全部
- 是否触发人工确认：否（不涉及架构、数据模型、API 契约、鉴权变更），但按 Harness 规则需完成 spec 后方案对齐
