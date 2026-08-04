# Skill Zip 导入实施计划

## 变更文件

- 新增 `apps/backend/app/modules/skill/importers.py`：封装 zip 安全校验、包清单生成、frontmatter 解析、slug 派生和资产索引。
- 修改 `apps/backend/pyproject.toml` 与 `poetry.lock`：显式引入 PyYAML，使用结构化 YAML 解析 Skill frontmatter。
- 新增或扩展 `apps/backend/app/modules/skill/models.py`：定义技能包、包文件索引和脚本权限字段；所有新增字段必须带中文 `comment`。
- 新增 Alembic 迁移：创建技能包与包文件索引结构。
- 修改 `apps/backend/app/modules/skill/schemas.py`：新增技能包读写 schema、权限切换 schema 和导入响应 schema。
- 修改 `apps/backend/app/modules/skill/repositories.py`：新增技能包、包文件和权限状态读写方法。
- 修改 `apps/backend/app/modules/skill/services.py`：增加导入、包权限切换和运行时约束判断服务函数。
- 修改 `apps/backend/app/modules/skill/router.py`：新增 multipart 上传接口、包查询接口和权限切换接口。
- 修改 `apps/backend/tests/skill/test_skill_services.py`：覆盖包级导入、脚本权限、非法 zip、路径穿越、缺少入口文件等场景。
- 修改 `apps/backend/tests/skill/test_skill_routes.py`：覆盖路由注册和鉴权要求。
- 修改 `apps/front/src/api/skills.ts`：新增技能包 API 类型与请求函数。
- 修改 `apps/front/src/features/skills/index.tsx`：新增 zip 上传按钮、包详情弹窗、脚本权限开关和技能同步流程。
- 更新本 request 的 `verify.md`、`acceptance.md`、`meta.json`。

## 实施步骤

1. 等待人工确认新增技能包持久化、脚本权限和运行时约束的完整 B 方案。
2. 设计包级数据模型和迁移，明确技能、技能包、文件索引和权限字段关系。
3. 在后端实现受控 zip 导入、包清单生成和 frontmatter 解析。
4. 在后端实现包查询与脚本权限切换接口，并补充运行时消费逻辑。
5. 在前端实现上传、包详情和权限切换。
6. 执行后端定向测试、路由 OpenAPI 检查和前端 lint/prettier；把结果写入 `verify.md`。
7. 对照验收标准更新 `acceptance.md` 和 `meta.json`。

## 测试步骤

- `cd apps/backend && poetry run pytest tests/skill -q`
- `cd apps/backend && poetry run ruff check app/modules/skill tests/skill`
- `cd apps/front && pnpm exec eslint src/api/skills.ts src/features/skills/index.tsx`
- `cd apps/front && pnpm exec prettier --check src/api/skills.ts src/features/skills/index.tsx`

## 回滚说明

- 回滚后端 `importers.py`、包模型、迁移、schema、service、router 和测试，即可移除技能包能力。
- 回滚前端 API 和技能页面导入入口，即可恢复手工创建技能体验。
- 如果迁移已经执行，需要先回滚数据库变更，再恢复旧代码。

## 人工确认点

- 确认新增技能包持久化、脚本权限和运行时约束。
- 确认技能包执行权限默认关闭，且只能由平台管理员切换。
