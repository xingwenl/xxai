# 验收记录

## 验收结论

- 数据模型：`platform_models` 与 `agent_model_bindings` 已按 spec 建表，字段带中文注释，唯一约束（同平台同类型同模型名、同 Agent 同角色）生效。
- API：注册表 CRUD 与 Agent 绑定 GET/PUT/DELETE 已注册并通过鉴权要求校验；API Key 加密落库，响应只返回 `has_api_key`；删除被绑定模型返回 `model_in_use`。
- 能力路由：`image_generate`/`image_read` 工具与附件 embedding 按 Agent 绑定解析，未绑定回退全局 `.env` 配置；主对话模型仍走发布版本。
- 测试：后端全量 410 passed、1 skipped；迁移在 PostgreSQL 执行成功。
- 结论：`spec.md` 验收标准已满足，本 request 可视为完成。

## 剩余风险

- 绑定模型未做 TTL 缓存，每次工具调用多一次索引查询；当前规模可接受，后续可按需优化。
- 迁移 `downgrade` 未在真实库回滚演练，回滚逻辑仅经代码评审。

## 人工验收记录

- 2026-08-27：用户确认方案 B 及数据模型/API 契约（`platform_models`、`agent_model_bindings`、注册表 CRUD、Agent 绑定、按角色路由与 `.env` 兜底），随后进入实现。
- 2026-08-27：用户确认前端管理界面方案（模型管理页 + 智能体模型绑定 Tab，复用既有 API），随后完成实现。

## 第 2 次变更验收结论

- 前端「模型管理」页完成注册表创建、编辑、启停、删除（`model_in_use` 中文提示）、类型过滤与分页。
- 智能体「模型绑定」Tab 完成三个能力角色绑定/解绑（仅可选启用且类型匹配模型），保存走 `PUT` 整体替换，未绑定提示回退全局配置。
- 前端构建（`tsc -b && vite build`）与 eslint 通过，路由与侧边栏入口已生成。
- 本次仅前端增量，后端 API 与数据模型未变化；原后端验收结论不受影响。

## 第 3 次变更验收结论（fix）

- 根因已确认并修复：`image_read` 绑定模型 `base_url` 缺少 `/v1`，网关返回 HTML 导致描述静默为空；数据修正后生产路径端到端返回正常描述。
- 超时从 60s 提升到 120s（`READ_IMAGE_TIMEOUT_SECONDS`，本地配置），并新增非 JSON 响应诊断日志与回归测试。
- 相关回归 `36 passed`；本次未改变数据模型与 API 契约。

## 第 4 次变更验收结论（架构：基本/业务工具分层）

- 4 个内置工具（`http_get`/`http_post`/`image_generate`/`image_read`）已按「基本工具 / 业务工具」双层完成搬移与接线：基本层输入即数据、零业务上下文、单一职责；业务层持有 `BusinessToolContext`，负责来源解析、鉴权、持久化、模型绑定解析与结果包装。
- 定义与 handler 同页、装饰器导入即注册；公共注册页只做 import 收集与 `list/get`；业务工具 `depends_on` 依赖在启动期校验。
- `builtin_tool/services.py` 收敛为薄委托层，`invoke_builtin_tool` 旧签名与对外 LLM 契约不变；稳定错误码映射与 `tool_failed` 兜底已由单元测试锁定。
- 后端全量 `418 passed, 1 skipped`，ruff 检查与格式化通过；旧实现文件已删除、无残留引用。
