# 实施计划：Agent 运行时自感知

## 前置条件

- 停点判断结论为「需人工确认」（API 契约/行为变化），用户已于 2026-09-01 批准 spec.md（“可以”）。

## 实施状态

- 全部实施步骤已完成，验证证据见 `verify.md`。

## 实施步骤

1. **纯函数 `build_runtime_metadata_block`**
   - `apps/backend/app/modules/conversation/runtime.py` 新增纯函数，按白名单拼装运行时信息段；
   - `build_system_prompt()` 在 `version.system_prompt` 后追加该段（三个调用点自动生效）。

2. **会话用量汇总方法**
   - `apps/backend/app/modules/model_usage/repositories.py` 新增
     `session_summary(conversation_id, platform_id, agent_id)`，按 `conversation_id` 汇总
     prompt/completion/total_tokens 与记录数。

3. **业务工具 `get_runtime_info`**
   - 新增 `apps/backend/app/modules/tools/business/runtime_info.py`：空输入契约、白名单返回结构、
     会话/今日/累计用量、身份查询、失败降级 null；
   - `apps/backend/app/modules/tools/business/registry.py` 注册导入。

4. **单元测试**
   - 元数据块：字段齐全/缺失跳过/敏感字段不出现/能力白名单；
   - `session_summary`：按会话汇总正确、跨会话隔离；
   - `get_runtime_info` handler：正常返回、降级 null、不抛错；
   - 工具注册完整性校验不回归。

5. **验证**
   - 运行 `apps/backend` 相关单测（`pytest` 指定文件）；
   - 后台 REST 会话与 embed 会话各手动触发一次「你是什么模型/用量多少」验证回答准确；
   - 确认未绑定工具的 Agent 不暴露 `get_runtime_info`。

## 回滚说明

- 元数据块：移除 `build_system_prompt()` 中追加段落即可，无数据迁移。
- 业务工具：从 `business/registry.py` 移除注册导入即可，不触碰数据。
- 全程无数据库结构变更，回滚成本低。

## 文档同步

- 实现完成后更新 `verify.md`（记录真实验证证据）与 `acceptance.md`（验收结论与剩余风险）；
- 若实现中发现范围外问题，按 Harness 变更记录规则处理。
