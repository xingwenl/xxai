# 实施计划

## 变更文件

- `docs/harness/requests/2026-07-19-backend-technical-spec/research.md`
  - 记录官方文档、成熟案例、方案比较与最终选择。
- `docs/harness/requests/2026-07-19-backend-technical-spec/spec.md`
  - 说明目标、范围、风险、停点判断和验收标准。
- `docs/harness/requests/2026-07-19-backend-technical-spec/plan.md`
  - 说明当前文档任务的推进方式，以及后续若进入实现应如何落地。
- `docs/harness/requests/2026-07-19-backend-technical-spec/verify.md`
  - 记录本次文档核对动作与未执行项。
- `docs/harness/requests/2026-07-19-backend-technical-spec/acceptance.md`
  - 记录本次阶段性验收结论和待人工讨论点。
- `docs/harness/requests/2026-07-19-backend-technical-spec/meta.json`
  - 记录 request 当前处于 `plan` 阶段并等待人工确认。
- `docs/harness/specs/backend-technical-spec.md`
  - 形成后续后端 request 可以长期引用的正式规范文档。

本次实施落实 `research.md` 的方式：

- 按领域模块化目录写规范，而不是采用纯分层目录。
- 明确数据库访问采用 SQLAlchemy 2.0 async + PostgreSQL。
- 明确迁移采用 Alembic，而不是手动 SQL 演进。
- 明确启动资源采用 FastAPI `lifespan` 管理。

## 实施步骤

1. 建立 request 工作区，完成 `research.md`、`spec.md` 和 `plan.md`。
2. 新增仓库级后端技术规范文档，写清楚已定方案、目录职责和工程边界。
3. 记录本次实际执行的文档核对动作，补充 `verify.md`。
4. 在 `acceptance.md` 中记录“文档已就绪，但架构方案仍待人工讨论确认”。
5. 更新 `meta.json`，保持 `phase=plan`、`status=blocked`，在确认前不进入实现。
6. 等你讨论并确认后，再决定是否进入下一步后端基础设施实现 request 或继续在当前 request 内推进。

## 测试步骤

- `find docs/harness/requests/2026-07-19-backend-technical-spec -maxdepth 1 -type f | sort`
  - 预期结果：request 所需文档文件齐全。
- `sed -n '1,240p' docs/harness/specs/backend-technical-spec.md`
  - 预期结果：规范文档内容完整，包含技术栈、目录结构、职责边界和待讨论事项。
- `sed -n '1,240p' docs/harness/requests/2026-07-19-backend-technical-spec/research.md`
  - 预期结果：调研来源、方案比较和最终决策完整可追溯。

## 回滚说明

- 本次仅新增文档文件，若要回滚，只需删除本 request 目录和新增的技术规范文档。
- 因为尚未进入代码实现，不涉及数据库、接口或运行时行为回滚。

## 人工确认点

- 是否接受“后端统一采用 SQLAlchemy 2.0 async + `asyncpg`”。
- 是否接受“数据库演进必须统一走 Alembic”。
- 是否接受“目录采用领域模块化 `modules/<domain>/...`，而不是纯按层拆目录”。
- 是否接受“本阶段先不确定鉴权实现，只在 `core/security.py` 预留统一边界”。
