# 知识库管理实施计划

## 变更文件

- 修改 `apps/backend/app/modules/knowledge/repositories.py`：增加知识库/文档列表、删除、失败重试查询与写入。
- 修改 `apps/backend/app/modules/knowledge/router.py`：暴露平台级管理接口并复用管理员校验。
- 必要时修改 `apps/backend/app/modules/knowledge/services.py`、`schemas.py`：补齐重试状态约束和列表响应。
- 新增或修改 `apps/backend/tests/knowledge/`：验证接口、权限、级联删除和重试约束。
- 修改 `apps/front/src/api/knowledge.ts`：迁移到 `/platforms/{platform_id}/knowledge-bases`，删除旧 API 假设。
- 修改 `apps/front/src/api/knowledge.ts`、`apps/front/src/features/knowledge/index.tsx`：复用现有绑定接口，新增知识库绑定智能体弹窗。
- 新增 `apps/front/src/api/platform.ts`（如现有封装不足）：提供当前用户平台列表。
- 新增 `apps/front/src/features/knowledge/` 和 `apps/front/src/routes/_authenticated/ai/knowledge-bases.tsx`：实现知识库与文档管理页面。
- 更新 Harness 的 `verify.md`、`acceptance.md`、`meta.json`，记录真实验证结果。

## 实施步骤

1. 完成并确认本 request 的 research、spec、plan。
2. 核对数据库级联、Celery 任务状态和现有文件存储清理边界。
3. 补后端 repository/service/router/schema，并为新增契约添加定向测试。
4. 更新前端 API 封装，使用真实响应格式和 `/api/v1` 基础路径约定。
5. 实现平台选择、知识库表单/删除确认、文档列表、上传、URL 添加、删除和失败重试。
5.1. 在知识库列表操作区增加绑定智能体入口，选择平台内智能体后调用已有绑定接口。
6. 执行后端 pytest/ruff，前端文件级 ESLint/Prettier，必要时执行前端全量构建并记录基线问题。
7. 更新验证与验收文档，逐项对照验收标准。

## 测试步骤

- `cd apps/backend && poetry run pytest tests/knowledge -q`
- `cd apps/backend && poetry run ruff check app/modules/knowledge tests/knowledge`
- `cd apps/front && pnpm exec eslint <本次前端文件>`
- `cd apps/front && pnpm exec prettier --check <本次前端文件>`
- `cd apps/front && pnpm exec eslint src/api/knowledge.ts src/features/knowledge/index.tsx`
- `cd apps/front && pnpm exec prettier --check src/api/knowledge.ts src/features/knowledge/index.tsx`
- `cd apps/front && pnpm build`，若失败记录具体基线错误。

## 回滚说明

- 代码回滚需同时撤回后端新增路由、repository/service、前端页面和 API 封装。
- 硬删除已经发生后不能由代码回滚恢复，生产操作必须依赖数据库和文件存储备份。
- 本次不新增迁移；若实现过程中确认必须改表，应暂停并单独更新 spec 后重新确认。

## 人工确认点

- 必须确认：新增平台级知识库/文档列表、删除、重试 API。
- 必须确认：知识库和文档采用硬删除，知识库删除级联清理关联数据。
- 2026-08-04 增量不新增后端 API，仅复用已有绑定接口，不触发新的人工确认。
