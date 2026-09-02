# 验证记录：Agent 运行时自感知

验证日期：2026-09-01

## 变更内容

- `apps/backend/app/modules/conversation/runtime.py`：新增 `build_runtime_metadata_block`
  纯函数（字段白名单），`build_system_prompt()` 在 `version.system_prompt` 后追加运行时信息段。
- `apps/backend/app/modules/model_usage/repositories.py`：新增
  `ModelUsageRepository.session_summary()`（按 conversation_id 汇总，跨平台/Agent 隔离）。
- `apps/backend/app/modules/tools/business/runtime_info.py`：新增业务工具 `get_runtime_info`
  （空输入契约，返回 model/agent/version/usage/client，失败降级 null）；
  `business/registry.py` 注册导入。
- 新增测试：`tests/builtin_tool/test_runtime_info.py`（3 个用例）；
  `tests/conversation/test_runtime.py` 追加 4 个元数据块用例；
  `tests/model_usage/test_repository.py` 追加 2 个 session_summary 用例。

## 验证证据

### 单元测试（实际执行）

命令（`apps/backend` 下）：

```bash
poetry run pytest tests/builtin_tool/ tests/conversation/ tests/model_usage/ -q
# 125 passed

poetry run pytest tests/ -q --import-mode=importlib
# 460 passed, 1 skipped（--import-mode=importlib 规避多目录同名 test_models.py 收集冲突，属环境既有问题）
```

覆盖断言：

- 元数据块：白名单字段齐全（模型/Agent 版本/服务版本/温度/能力）；缺失字段跳过；
  敏感字段（`api_key_encrypted`、`model_base_url`）绝不出现；`build_system_prompt`
  中运行时信息段位于基础提示词之后。
- `session_summary`：按会话汇总正确；同一 Agent 其他会话不计入；跨平台同 ID 不串数据；
  无用量会话返回全 0。
- `get_runtime_info`：注册契约（空输入 schema）；正常路径返回 model/agent/version/usage/client
  且不含 api_key/base_url；Agent 不存在时 model/agent/version 为 null、usage 不抛错。

### 静态检查（实际执行）

```bash
poetry run ruff check <改动文件>        # All checks passed!
poetry run black --check <改动文件>     # 已格式化，无差异
```

## 已知限制

- 业务工具 `get_runtime_info` 需 Agent 在管理端绑定启用后才对模型可见（与
  `knowledge_search` 一致），存量 Agent 默认不可见，未做迁移。
- `client` 身份依赖该会话已产生至少一条用量记录；首个请求前为 null（按设计降级）。
- 今日/累计用量以服务本地时区 `date.today()` 为界。
