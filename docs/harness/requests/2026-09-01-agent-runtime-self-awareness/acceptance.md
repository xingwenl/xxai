# 验收记录

## 验收结论

- 系统提示词注入：`build_system_prompt()` 在基础提示词后追加「【运行时信息】」段（模型名、Agent 版本、服务版本、SDK 最低版本、温度、能力摘要），后台 REST 与 embed WebSocket 三个调用点自动生效；白名单单测断言 `api_key_encrypted`、`model_base_url` 不出现。
- 业务工具：`get_runtime_info` 已注册进 `BUSINESS_TOOL_REGISTRY`，经 `_from_business` 进入既有 builtin 工具链路；返回 model/agent/version/usage（当前会话/今日/累计）/client，失败降级 null；Agent 不存在时不抛错。
- 用量：`ModelUsageRepository.session_summary()` 按 `conversation_id` 汇总且跨平台/Agent 隔离；无新表、无数据模型变化。
- 测试：后端全量 `460 passed, 1 skipped`（`--import-mode=importlib` 规避多目录同名测试文件收集冲突），ruff 通过；black 提示的 reformat 均为仓库既有代码，未混入本次改动。
- 结论：`spec.md` 验收标准已满足，本 request 可视为完成。

## 剩余风险

- `get_runtime_info` 需 Agent 在管理端绑定启用后才对模型可见（与 `knowledge_search` 一致），存量 Agent 默认不可见；如需默认可用需另做迁移，本期按「绑定才可见」语义处理。
- `client` 身份依赖当前会话已产生至少一条用量记录，首个请求前为 null（按设计降级）。
- 今日/累计用量以服务本地时区 `date.today()` 为界，跨时区部署时统计边界与前端展示可能不一致。

## 人工验收记录

- 2026-09-01：用户审阅 `spec.md` 后批准（“可以”），批准范围含 API 契约/行为变化（系统提示词新增运行时信息段 + 模型可见工具新增 `get_runtime_info`）。
- 2026-09-02：用户确认功能可用（“可以 能用”），批准提交代码。
