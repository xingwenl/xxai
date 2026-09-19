# 验证记录

## 变更文件

- `docker-compose.yml`：新增 `x-logging` 锚点（json-file + `max-size: 10m` / `max-file: 5`）并在 7 个服务引用；把共享环境变量上移为 `x-backend-environment` 锚点，移除共用 `LOG_FILE_PATH`，新增 `TZ: ${TZ:-Asia/Shanghai}`；`api` / `worker` / `wechat-bot-worker` 分别声明 `/app/logs/{api,worker,wechat-bot}/app.log`。
- `apps/backend/app/core/config.py`：新增 `_resolve_log_file_path()`（相对路径按 `BASE_DIR` 解析）；`LOG_FILE_BACKUP_COUNT` 默认值 5 → 14。
- `apps/backend/app/core/logging.py`：`DatedFileHandler` 支持 `cleanupOnInit`（默认启动即清理）；清理限定同目录同前缀、跳过当前文件、忽略删除失败；`build_logging_config` / `setup_logging` 默认保留数量改为 14。
- `apps/backend/app/modules/wechat_bot/worker.py`：新增 `_heartbeat_log_level()`，心跳仅在状态变化时 INFO，未变化降为 DEBUG。
- `apps/backend/tests/system/test_logging.py`：新增 7 个用例（相对/绝对路径解析、默认保留 14、启动清理、跨目录隔离、心跳级别、异步心跳行为）。
- `deploy/deploy.sh`：启动前创建三个日志子目录；输出新增文件日志路径提示。
- `.env.example`、`deploy/.env.prod.example`、`.env`、`apps/backend/.env`：删除已无代码读取的 `LOG_FILE_ROTATION_WHEN` / `LOG_FILE_ROTATION_INTERVAL`，`LOG_FILE_BACKUP_COUNT` 改 14，补充分服务路径说明。
- `docs/deploy/部署方案.md`、`docs/CHANGELOG.md`：同步文档与变更日志。
- Harness 文档：本 request 的 `research.md` / `spec.md` / `plan.md` / `verify.md` / `acceptance.md` / `meta.json`。

## 验证命令与结果

1. 日志专项单测

```bash
cd apps/backend && poetry run pytest tests/system/test_logging.py -q
```

结果：`11 passed in 2.96s`（原 4 个用例保持通过 + 新增 7 个用例全部通过）。

2. 相关目录回归

```bash
cd apps/backend && poetry run pytest tests/system tests/wechat_bot -q
```

结果：`40 passed, 1 warning in 3.12s`。唯一 warning 来自既有用例 `tests/wechat_bot/test_services.py::test_poll_binding_status_timeout_returns_error`（`RuntimeWarning: coroutine ... was never awaited`），与本次改动无关，改动前后一致。

3. Compose 渲染（基础文件）

```bash
docker compose config > /tmp/rendered-compose.yml
```

结果：`exit=0`。渲染结果中：
- `api` → `LOG_FILE_PATH: /app/logs/api/app.log`
- `worker` → `LOG_FILE_PATH: /app/logs/worker/app.log`
- `wechat-bot-worker` → `LOG_FILE_PATH: /app/logs/wechat-bot/app.log`
- 三个后端服务均带上 `TZ: Asia/Shanghai`
- 7 个服务均渲染出 `driver: json-file` 与 `max-size: 10m` / `max-file: "5"`

4. Compose 渲染（叠加生产覆盖文件）

```bash
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml config > /tmp/rendered-prod.yml
```

结果：`exit=0`，三条 `LOG_FILE_PATH` 与基础文件一致，`driver: json-file` 出现 7 次，生产覆盖文件中的端口 `!override` 行为不受影响。

5. 路径解析与 CWD 无关性

```bash
cd apps/backend && LOG_FILE_PATH=logs/api/app.log poetry run python -c "
import os; os.chdir('/tmp')
from app.core.config import get_settings
print(get_settings().log_file_path, get_settings().log_file_backup_count)"
```

结果：`cwd= /private/tmp` 时仍解析为 `/Users/lixingwen/xw/study/ai-base/apps/backend/logs/api/app.log`，`backup_count=14`。证明相对路径不再依赖进程工作目录。

6. 双进程真实落盘验证（无 Docker，脚本 `/tmp/log_split_check.py`）

```bash
cd apps/backend && poetry run python /tmp/log_split_check.py
```

脚本内容：预置 `api/` 目录下 9 个历史 `app-2026-01-*.log`，随后并发启动两个进程，分别以 `LOG_FILE_PATH=/tmp/log-split-check/{api,worker}/app.log`、`LOG_FILE_BACKUP_COUNT=3` 各写 50 条日志。

结果：
- `api 文件行数: 50`、`worker 文件行数: 50`
- `api 含 worker 日志: False`、`worker 含 api 日志: False`（分文件隔离生效）
- `api 目录剩余文件: ['app-2026-01-08.log', 'app-2026-01-09.log', 'app-2026-09-19.log']`、`worker 目录剩余文件: ['app-2026-09-19.log']`（启动清理按保留 3 个生效，且未跨目录删除）

7. 部署脚本语法

```bash
bash -n deploy/deploy.sh
```

结果：`deploy.sh 语法 OK`。

8. 代码风格

```bash
cd apps/backend && poetry run ruff check app/core/logging.py app/core/config.py app/modules/wechat_bot/worker.py tests/system/test_logging.py
cd apps/backend && poetry run ruff format --check app/core/logging.py app/modules/wechat_bot/worker.py tests/system/test_logging.py
```

结果：`ruff check` → `All checks passed!`。`ruff format --check` 报告 3 个文件可被重排，但 `ruff format --diff` 显示差异**全部落在本次未触碰的历史代码行**（如 `app/core/config.py` 的 `tool_snapshot_total_chars`、既有测试函数签名），属于仓库现状；为避免制造无关改动，本次未执行格式化。

## 未验证项与原因

- **真实容器内运行验证未执行**：本机沙箱对 Docker socket 的访问被拒绝（`permission denied ... docker.sock`），两次提权请求均被审批服务以内部错误（HTTP 400）拒绝。因此以下内容仅有静态证据，缺少运行时证据：
  - 容器内 `TZ=Asia/Shanghai` 后 `date` 与宿主机一致、跨零点的文件切换行为；
  - 三个容器分别写入 `/app/logs/{api,worker,wechat-bot}/` 的实际目录结构。
- **宿主 Docker 守护进程 log-opts 是否已配置全局上限**：无法通过 `docker inspect` 核验；本次在 Compose 层显式声明，属于按服务覆盖（即使守护进程已配置也以服务级为准）。
- **`wechat-bot-worker` 心跳降噪的线上效果**：仅通过单测与代码路径验证（`_heartbeat_log_level` + `_supervise` 异步用例），未在真实微信机器人会话下观察。

## 与计划的偏差

- `plan.md` 中"删除遗留 `apps/backend/logs/app.log`"未执行：该文件是历史日志数据（2026-08-03 本地运行残留，2.4KB），保留可查且不影响新逻辑；且它不匹配清理模式 `app-*.log`，不会被新逻辑误删。
- `deploy/docker-compose.prod.yml` 未修改（与计划一致）：日志配置来自基础文件，叠加文件只覆盖端口与重启策略。
