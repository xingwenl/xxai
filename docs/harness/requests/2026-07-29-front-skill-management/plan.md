# 技能管理实施计划

## 变更文件

- 修改 `apps/backend/app/modules/skill/repositories.py`：增加分页列表、详情更新、硬删除、绑定查询和解绑。
- 修改 `apps/backend/app/modules/skill/schemas.py`：增加列表、更新和绑定读取结构。
- 修改 `apps/backend/app/modules/skill/services.py`、`router.py`：补齐 CRUD 与绑定管理接口。
- 新增 `apps/backend/tests/skill/test_skill_routes.py` 和服务测试：验证路由、权限、停用和级联删除契约。
- 重写 `apps/front/src/api/skills.ts`：迁移至平台级 API。
- 新增 `apps/front/src/features/skills/index.tsx`、`apps/front/src/routes/_authenticated/ai/skills.tsx`：实现管理页面。
- 更新 request 的 `verify.md`、`acceptance.md`、`meta.json`。

## 实施步骤

1. 等待本 request 的 API 契约和硬删除语义确认。
2. 补充后端 schema/repository/service/router 和定向测试。
3. 更新前端 API 类型与真实路径。
4. 实现技能表单、状态、删除和智能体绑定交互。
5. 执行后端 pytest/ruff、前端 ESLint/Prettier，并记录全量构建基线。
6. 更新验证与验收记录。

## 测试步骤

- `cd apps/backend && poetry run pytest tests/skill tests/agent tests/platform -q`
- `cd apps/backend && poetry run ruff check app/modules/skill tests/skill`
- `cd apps/front && pnpm exec eslint <本次前端文件>`
- `cd apps/front && pnpm exec prettier --check <本次前端文件>`
- `cd apps/front && pnpm build`，记录已有基线失败。

## 回滚说明

- 代码回滚需同时撤回技能 API、前端页面和 Harness 文档。
- 硬删除已经发生后不能依靠代码回滚恢复绑定或技能数据。

## 人工确认点

- 新增技能列表、更新、删除、绑定查询和解绑 API。
- 技能停用保留绑定；技能删除采用硬删除并级联清理绑定。
