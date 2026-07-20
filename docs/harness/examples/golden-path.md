# Harness Golden Path 示例

## 场景 1：`/new` 新建功能

1. 使用 `/new 聊天消息已读状态`
2. 新建 request 目录，例如 `docs/harness/requests/2026-06-03-chat-read-status/`
3. 复制模板，补齐 `research.md`、`spec.md`、`plan.md`、`verify.md`、`acceptance.md`、`meta.json`
4. 先调研官方文档、成熟开源项目和生产实践，记录在 `research.md`
5. 基于调研结论完成 `spec.md` 与 `plan.md`
6. 若触发审批条件，先记录审批状态
7. 实现完成后补 `verify.md`
8. 最后补 `acceptance.md`
9. 同步更新 `meta.json.phase`

## 场景 2：`/modify` 在原 spec 上补功能

1. 使用 `/modify 2026-06-03-chat-read-status`
2. 判断仍属于原目标闭环
3. 若新增范围需要重新比较方案，先更新 `research.md`
4. 在 `spec.md` 中追加 `## 变更记录`
5. 同步更新正文中的范围、风险、验收标准
6. 如实施方式变化，再同步更新 `plan.md`

## 场景 3：`/fix` 修复已有 spec 对应 bug

1. 使用 `/fix 2026-06-03-chat-read-status`
2. 判断 bug 修复仍属于原需求闭环
3. 在 `spec.md` 的 `变更记录` 中追加一条 `fix`
4. 若修复涉及方案选择变化，更新 `research.md`
5. 根据影响面更新 `verify.md`
6. 若验收结论受影响，更新 `acceptance.md`

## 场景 4：FastAPI 后端新增接口

1. 使用 `/new 健康检查接口`
2. 创建 `docs/harness/requests/2026-07-18-health-check-api/`
3. 先查阅 FastAPI 官方文档和一个成熟案例，在 `research.md` 记录方案和取舍
4. 在 `spec.md` 说明接口目标、路径、响应体、风险和停点判断
5. 在 `plan.md` 说明将修改的 FastAPI 入口、schema、测试文件
6. 若不涉及数据模型、API 破坏性变更、鉴权变化，可直接进入实现
7. 在 `verify.md` 记录 `pytest`、`ruff`、启动命令或文档核对结果
8. 在 `acceptance.md` 明确该接口是否达到验收标准
