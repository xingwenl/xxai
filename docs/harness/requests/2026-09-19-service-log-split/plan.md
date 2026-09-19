# 实施计划

## 变更文件

部署配置：

- `docker-compose.yml`：新增顶层 `x-logging` 锚点（`json-file` + `max-size` / `max-file`）并在所有服务引用；`&backend-environment` 移除共用 `LOG_FILE_PATH`、新增 `TZ`；`api` / `worker` / `wechat-bot-worker` 分别声明各自 `LOG_FILE_PATH`。
- `deploy/deploy.sh`：启动前创建日志子目录；更新部署完成提示中的日志路径。
- `deploy/docker-compose.prod.yml`：不修改（它是叠加文件，只覆盖端口与重启策略，日志配置来自基础文件；`docker compose -f a -f b` 的合并语义已由该文件头部注释说明）。

后端代码：

- `apps/backend/app/core/config.py`：新增 `_resolve_log_file_path()`（相对路径按 `BASE_DIR` 解析）；`LOG_FILE_BACKUP_COUNT` 默认值改为 14。
- `apps/backend/app/core/logging.py`：`DatedFileHandler` 新增启动清理；清理逻辑收敛为"同目录、同前缀、保留最近 N 个"并跳过当前正在写的文件；`setup_logging` 保持既有签名。
- `apps/backend/app/modules/wechat_bot/worker.py`：心跳日志改为状态变化时 INFO、未变化时 DEBUG。

配置示例与文档：

- `.env.example`、`deploy/.env.prod.example`：删除 `LOG_FILE_ROTATION_WHEN` / `LOG_FILE_ROTATION_INTERVAL`，补充分服务路径说明，`LOG_FILE_BACKUP_COUNT` 示例值改 14。
- `.env`、`apps/backend/.env`（本机未跟踪文件）：同步清理死配置，避免本机继续误导。
- `docs/deploy/部署方案.md`：更新"监控与日志"章节中的落盘路径。
- `docs/CHANGELOG.md`：追加本次变更条目。

测试：

- `apps/backend/tests/system/test_logging.py`：新增/调整用例，覆盖相对路径解析、启动清理、保留数量、目录隔离。
- 本机清理：删除遗留的 `apps/backend/logs/app.log`（旧 `TimedRotatingFileHandler` 时代产物，仅存在于本机，未跟踪）。

实施步骤如何落实调研结论：`research.md` 选定方案 B（按服务分文件）。本计划把"文件路径"从共享改为服务级私有（Compose 层），把"清理边界"收敛到服务目录（代码层），并按来源 3、4 给容器 stdout 补 `json-file` 体积上限。

## 实施步骤

1. 修改 `apps/backend/app/core/config.py`
   - 新增 `_resolve_log_file_path()`：读取 `LOG_FILE_PATH`；相对路径拼到 `BASE_DIR` 下；未配置时用 `BASE_DIR / "logs" / "app.log"`。
   - `log_file_backup_count` 默认值 5 → 14。
2. 修改 `apps/backend/app/core/logging.py`
   - `DatedFileHandler.__init__` 增加 `cleanup_on_init: bool = True`；在打开文件后调用一次 `_remove_expired_logs()`。
   - `_remove_expired_logs()`：显式跳过 `self.baseFilename` 指向的当前文件；只匹配 `f"{stem}-*{suffix}"`；只处理文件（`is_file()`）；删除失败时忽略（`missing_ok`）并记录不做中断。
3. 修改 `apps/backend/app/modules/wechat_bot/worker.py`
   - 在 `_supervise`（心跳处）记录上一次的 `running` / `active_bindings`，仅在变化时用 `logger.info`，未变化时 `logger.debug`；首次循环按"变化"处理。
4. 修改 `docker-compose.yml`
   - 顶层新增：
     ```yaml
     x-logging: &default-logging
       driver: json-file
       options:
         max-size: "10m"
         max-file: "5"
     ```
   - 所有服务（`db`、`redis`、`api`、`worker`、`wechat-bot-worker`、`skill-runner`、`front`）加 `logging: *default-logging`。
   - `&backend-environment` 中删除 `LOG_FILE_PATH`，新增 `TZ: ${TZ:-Asia/Shanghai}`。
   - `api` / `worker` / `wechat-bot-worker` 的 `environment` 用 `<<: *backend-environment` 追加各自 `LOG_FILE_PATH`。
5. 修改 `deploy/deploy.sh`：在"启动服务"前 `mkdir -p apps/backend/logs/api apps/backend/logs/worker apps/backend/logs/wechat-bot`；更新尾部日志提示为 `apps/backend/logs/<服务>/`。
6. 更新 `.env.example`、`deploy/.env.prod.example`、本机 `.env`、`apps/backend/.env`。
7. 更新 `docs/deploy/部署方案.md` 与 `docs/CHANGELOG.md`。
8. 补测试并运行（见测试步骤）。

## 测试步骤

1. 单元测试：
   - 命令：`cd apps/backend && poetry run pytest tests/system/test_logging.py -q`
   - 预期：全部通过；覆盖相对路径解析、启动清理（写入超过 N 个历史文件后只留 N 个）、不删除其他服务目录与无关文件。
2. 相关回归：
   - 命令：`cd apps/backend && poetry run pytest tests/system -q`
   - 预期：全部通过。
3. Compose 配置渲染：
   - 命令：`docker compose config`（或 `docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml config`）
   - 预期：无报错；`api` / `worker` / `wechat-bot-worker` 的 `LOG_FILE_PATH` 互不相同；`TZ` 与 `logging.options` 正确注入。
   - 说明：本机沙箱对 Docker socket 的访问被拒绝；若 `docker compose config` 也因守护进程/权限不可用，则退化为用 `python -c "import yaml"` 解析校验 YAML 结构，并在 `verify.md` 记录该降级与原因。
4. 运行时验证（尽量执行）：
   - 命令：`docker compose -f docker-compose.yml up -d api wechat-bot-worker` 后检查 `apps/backend/logs/api/app-<今天>.log`
   - 预期：`api` 目录内不再出现 `celery.*` 或 `__main__` 的 wechat bot 心跳；文件名日期与宿主机 CST 一致（东八区 0 点后进入当天文件）。
   - 若容器启动不可用，记录为未验证项，并在 `acceptance.md` 的剩余风险中列明。
5. 噪音验证（无需 Docker）：
   - 命令：`cd apps/backend && poetry run python -c "..."` 或直接跑相关单测，确认状态未变化时不产生 INFO 级心跳。

## 回滚说明

- 代码/配置回滚：`git revert`（或 `git checkout --`）本次涉及的 `docker-compose.yml`、`deploy/deploy.sh`、`apps/backend/app/core/{config,logging}.py`、`apps/backend/app/modules/wechat_bot/worker.py`、`.env.example`、`deploy/.env.prod.example`、`docs/` 文件即可。
- 数据与日志回滚：日志目录结构变化不影响历史文件，旧的 `apps/backend/logs/app-<date>.log` 保持原样可查；如需回到共享文件，只需恢复 Compose 中的 `LOG_FILE_PATH` 并重启服务。
- 特别关注：`TZ` 变更后新写入的文件名会切换为 CST 日期；回滚 `TZ` 会导致日期再次错位，但不会造成数据损坏。回滚 `deploy.sh` 的 `mkdir` 不影响运行中的容器。

## 人工确认点

- spec 后方案对齐检查点：已于 2026-09-19 由用户确认（"写到文件里，按服务分文件" + "可以"），确认覆盖分服务路径、时区统一到 `Asia/Shanghai`、保留 14 天、相对路径按 `BASE_DIR` 解析四个决策点。
- 本次不涉及架构、数据模型、API 契约、鉴权变更，无其他强制人工确认点。
