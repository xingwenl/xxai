# FastAPI 后端 Harness 示例

本示例展示一个典型后端 request 应如何组织，不要求逐字照抄，但建议保持同样的结构和完整度。

## 示例主题

`/new 健康检查接口`

## 推荐 request-id

`2026-07-18-health-check-api`

## 推荐工作区

```text
docs/harness/requests/2026-07-18-health-check-api/
  research.md
  spec.md
  plan.md
  verify.md
  acceptance.md
  meta.json
```

## spec.md 应写什么

- 先在 `research.md` 记录 FastAPI 官方健康检查、路由组织和测试文档，以及一个成熟案例
- 目标：新增一个 `GET /health` 接口，用于服务可用性检查
- 范围：FastAPI 路由、响应 schema、最小测试
- 非目标：不接入数据库，不增加鉴权，不引入复杂监控
- 风险：低，主要是路由注册和响应结构稳定性
- 停点判断：无架构、数据模型、权限变化；若响应契约已对外承诺，则修改时需审批
- 验收标准：接口可访问、返回结构稳定、测试记录完整

## plan.md 应写什么

- 说明实施如何落实调研中选择的路由组织和测试方案
- 修改 `apps/backend/main.py` 或拆分出的路由文件
- 如需要，新增 `app/schemas/health.py`
- 新增对应测试文件
- 记录 `pytest`、`ruff`、启动验证命令

## verify.md 应写什么

- `poetry run pytest`
- `poetry run ruff check .`
- `poetry run uvicorn main:app --reload`

如果只做文档演练而不运行命令，也要明确写清原因，例如“当前仓库尚未补齐测试目录，本次仅完成文档闭环示例”。

## acceptance.md 应写什么

- 是否达到 spec 中的验收标准
- 是否还需要人工打开接口实际访问
- 是否存在未覆盖的错误场景

## meta.json 应写什么

建议至少维护：

- `id`
- `title`
- `scope`
- `phase`
- `riskLevel`
- `changeTypes`
- `approvalRequired`
- `approvalGranted`
- `updatedAt`

## 何时必须停下来

以下情况不要直接实现，先等人工确认：

- 把 `/health` 扩展成对外正式监控契约
- 同时引入数据库连接检查并改变启动行为
- 增加鉴权要求
- 把简单探活接口扩展为跨服务聚合状态接口
