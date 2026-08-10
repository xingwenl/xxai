# 实施计划

## 变更文件

- `apps/backend/app/core/config.py`：增加历史窗口配置。
- `.env.example`、`docker-compose.yml`：记录默认值并向后端容器透传配置。
- `apps/backend/app/modules/conversation/repositories.py`：增加按时间窗口查询消息的方法。
- `apps/backend/app/modules/conversation/runtime.py`：支持把历史消息映射并注入模型。
- `apps/backend/app/modules/conversation/services.py`：在流式和非流式调用前读取历史。
- `apps/backend/tests/conversation/test_runtime.py`：覆盖历史消息顺序和角色映射。

## 实施步骤

1. 增加默认 1 小时的配置项。
2. 在仓储层使用 `created_at` 截止时间和完成状态查询历史，并保持正序。
3. 扩展运行时图函数的可选历史参数，构建系统消息、历史消息、当前用户消息序列。
4. 在两条聊天服务路径创建当前用户消息前读取历史，传入运行时。
5. 增加单元测试，运行后端定向测试和 SDK 构建。

## 测试步骤

- `cd apps/backend && poetry run pytest tests/conversation/test_runtime.py -q`
- `cd apps/backend && poetry run ruff check app tests`
- `cd apps/ai-sdk && npm test -- --runInBand`（若脚本支持）
- `cd apps/ai-sdk && npm run build`

## 回滚说明

删除配置、仓储、运行时和服务改动即可恢复原先只发送当前消息的行为；无需数据库回滚。

## 人工确认点

无。本次不涉及架构、数据模型、API 契约或权限变化。
