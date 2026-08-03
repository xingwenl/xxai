# 实施计划

## 变更文件

- `docs/harness/requests/2026-08-03-backend-file-logging/research.md`：记录日志模块业界调研、方案比较和最终决策。
- `docs/harness/requests/2026-08-03-backend-file-logging/spec.md`：记录目标、范围、风险、停点判断和验收标准。
- `docs/harness/requests/2026-08-03-backend-file-logging/plan.md`：记录实施步骤、测试步骤、回滚说明和人工确认点。
- `docs/harness/requests/2026-08-03-backend-file-logging/verify.md`：实现后记录真实验证证据。
- `docs/harness/requests/2026-08-03-backend-file-logging/acceptance.md`：验证后记录验收结论。
- `docs/harness/requests/2026-08-03-backend-file-logging/meta.json`：维护 request 机器可读状态。
- `apps/backend/app/core/config.py`：新增日志文件基础路径和保留份数配置。
- `apps/backend/app/core/logging.py`：基于标准库 `FileHandler` 增加当前文件名带日期的 `DatedFileHandler`。
- `apps/backend/app/__init__.py`：把配置层日志参数传给 `setup_logging`。
- `apps/backend/tests/system/test_logging.py`：新增日志配置和写入行为测试。
- `.gitignore`：忽略后端本地日志文件目录。

## 实施步骤

1. 创建 request 工作区，并补齐 `research.md`、`spec.md`、`plan.md`、初始 `verify.md`、`acceptance.md` 和 `meta.json`。
2. 编写 `apps/backend/tests/system/test_logging.py`，先覆盖以下预期：
   - `build_logging_config` 默认包含 console 和 file handler。
   - 文件 handler 使用 `app.core.logging.DatedFileHandler`。
   - 调用 `setup_logging` 后，日志目录会被创建，日志内容会写入指定文件。
3. 运行目标测试，确认当前实现因缺少文件 handler 或函数参数而失败。
4. 修改 `apps/backend/app/core/config.py`：
   - 增加 `log_file_path: str`。
   - 增加 `log_file_backup_count: int`。
   - 默认日志路径为 `BASE_DIR / "logs" / "app.log"`。
5. 修改 `apps/backend/app/core/logging.py`：
   - `build_logging_config` 接收日志文件基础路径和保留份数。
   - 文件 handler 使用 `app.core.logging.DatedFileHandler`。
   - 文件编码使用 `utf-8`。
   - `setup_logging` 在配置前创建日志目录。
6. 修改 `apps/backend/app/__init__.py`，应用启动时使用 `settings` 中的日志文件配置。
7. 修改 `.gitignore`，忽略 `apps/backend/logs/`。
8. 重新运行目标测试并确认通过。
9. 运行后端相关最小验证命令。
10. 更新 `verify.md`、`acceptance.md` 和 `meta.json`。

## 测试步骤

- 命令：`poetry run pytest tests/system/test_logging.py -q`
- 预期结果：日志模块相关测试全部通过。
- 命令：`poetry run pytest tests/system/test_health_service.py tests/system/test_logging.py -q`
- 预期结果：系统模块既有测试和新增日志测试全部通过。

## 回滚说明

- 撤回 `apps/backend/app/core/config.py`、`apps/backend/app/core/logging.py`、`apps/backend/app/__init__.py`、`apps/backend/tests/system/test_logging.py` 和 `.gitignore` 的本次改动即可恢复到控制台日志行为。
- 若本地已经生成 `apps/backend/logs/`，可手工删除该目录；目录已被 `.gitignore` 忽略，不影响版本控制。

## 人工确认点

- 无。本次不涉及架构边界、数据模型、API 契约、鉴权或权限行为变化。
