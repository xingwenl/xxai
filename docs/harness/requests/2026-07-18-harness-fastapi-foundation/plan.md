# 实施计划

## 变更文件

- `docs/harness/README.md`：补齐仓库级 Harness 入口说明
- `docs/harness/backend.md`：补齐 FastAPI 后端开发规范
- `docs/harness/policies/global.md`：保留现有全局策略，作为 README 的规则落点
- `docs/harness/templates/spec-template.md`：补齐 spec 填写提示
- `docs/harness/templates/plan-template.md`：补齐 plan 填写提示
- `docs/harness/templates/verify-template.md`：补齐 verify 填写提示
- `docs/harness/templates/acceptance-template.md`：补齐 acceptance 填写提示
- `docs/harness/templates/meta-template.json`：新增结构化状态模板
- `docs/harness/examples/golden-path.md`：补充 request 和 FastAPI 后端场景
- `docs/harness/examples/fastapi-backend-example.md`：新增 FastAPI 后端示例
- `docs/harness/requests/2026-07-18-harness-fastapi-foundation/*`：记录本次任务闭环

## 实施步骤

1. 创建本次 request 工作区，先补 `spec.md` 和 `plan.md`
2. 重写 `docs/harness/README.md`，明确阶段、目录、request 规范和审批边界
3. 填充 `docs/harness/backend.md`，定义 FastAPI 分层职责、验证要求和停点条件
4. 强化模板文件，让新 request 可以直接填写，不再只有空标题
5. 新增 `meta-template.json` 作为结构化状态示例
6. 补充 `golden-path` 与 FastAPI 示例，形成可复用样本
7. 完成后回填 `verify.md`、`acceptance.md` 和 `meta.json`

## 测试步骤

- 使用 `sed -n '1,220p'` 逐个检查新增和修改文档是否落盘
- 使用 `find docs/harness/requests/2026-07-18-harness-fastapi-foundation -maxdepth 1 -type f | sort` 检查 request 文件完整性
- 使用 `rg "TODO|TBD" docs/harness` 检查是否遗留明显占位符

## 回滚说明

- 若需回滚，可整体撤回本次新增和修改的 `docs/harness/` 文档
- 回滚时应保持 request 工作区与 README、模板一致，不要只删除部分文件导致规范失衡

## 人工确认点

- 无
