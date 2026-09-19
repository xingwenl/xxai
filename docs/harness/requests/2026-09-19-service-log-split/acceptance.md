# 验收记录

## 验收结论

对照 `spec.md` 的 9 条验收标准，逐条结论如下：

1. `api` / `worker` / `wechat-bot-worker` 的 `LOG_FILE_PATH` 互不相同且位于 `/app/logs/<service>/app.log`，`docker compose config` 无报错 —— **通过**（渲染结果见 `verify.md` 第 3 节）。
2. 三个后端服务容器内时区统一为 `Asia/Shanghai` —— **部分通过**：Compose 已注入 `TZ: Asia/Shanghai`（渲染结果可见），但容器内 `date` 与跨零点行为未在真实容器验证（Docker socket 被沙箱拒绝），列为剩余风险。
3. 全部服务声明 `json-file` + `max-size` / `max-file` —— **通过**（渲染结果中出现 7 次）。
4. 宿主机出现 `api/`、`worker/`、`wechat-bot/` 三个日志目录且互不混写 —— **部分通过**：双进程真实落盘验证已证明隔离生效（`verify.md` 第 6 节），真实容器路径未验证。
5. 启动时清理过期文件且不误删其他目录/前缀 —— **通过**（启动清理用例 + 跨目录隔离用例 + 双进程脚本：9 个历史文件按保留 3 个清理，`worker/` 目录与其他前缀文件未受影响）。
6. 心跳在状态未变化时不再产生 INFO —— **通过**（`_heartbeat_log_level` 用例 + `_supervise` 异步用例断言 INFO 仅 1 条、DEBUG 存在）。
7. `LOG_FILE_BACKUP_COUNT` 默认 14，`.env*` 不再出现 `LOG_FILE_ROTATION_*` —— **通过**（`test_settings_default_log_file_backup_count_is_14`；四个 env 文件已清理并复核）。
8. `tests/system/test_logging.py` 全部通过且不破坏既有测试 —— **通过**（11 passed；`tests/system` + `tests/wechat_bot` 共 40 passed，唯一 warning 为既有用例的无关告警）。
9. `docs/CHANGELOG.md` 已记录 —— **通过**。

结论：本 request 的实现与验证已完成，可视为完成（`status: done`）。第 2、4 条的"真实容器内运行"部分属于环境受限的未覆盖项，已明确记录，不阻塞交付，但建议按剩余风险中的步骤做一次线上复核。

## 剩余风险

- 真实容器运行未验证（沙箱禁止访问 Docker socket，两次提权被审批服务以 HTTP 400 拒绝）：
  - 建议在有 Docker 权限的环境执行 `docker compose -f docker-compose.yml up -d api worker` 后确认：`ls apps/backend/logs/api/` 出现 `app-<今天>.log`；`docker compose exec api date` 与宿主机 CST 一致；`apps/backend/logs/api/` 内不再出现 `celery.*` / `__main__` 来源日志。
- 切换 `TZ` 后，跨零点那天的日志会按新时区分文件：预计 `app-2026-09-18.log` 不再增长，新内容进入 `app-2026-09-19.log`（当前活跃文件按 UTC 命名，历史文件保持原样）。
- 宿主机若已配置 Docker 守护进程级 `log-opts`，与服务级 `logging.options` 的关系为服务级优先；本次未核验守护进程配置。
- `wechat-bot-worker` 心跳降噪仅在单测与代码路径层面验证，未在真实微信会话下观察。
- 旧格式文件 `apps/backend/logs/app-<date>.log`（2026-09-18 及更早）保持原样，不参与新的按服务清理；如需归档请人工处理。
- 顺带发现（不在本次范围）：`.env.example` 中保留了明文 `EMBED_CLIENT_SECRET`，建议后续单独治理。

## 人工验收记录

- 2026-09-19：用户在 spec 对齐检查点确认方案（"写到文件里，按服务分文件"、时区统一、保留 14 天、相对路径按 `BASE_DIR` 解析，答复"可以"）。
- 本次不涉及架构边界、数据模型、API 契约、鉴权变更，无其他强制人工确认点。
- 未执行 Git 提交，等待用户按仓库约定在根仓库统一提交。
