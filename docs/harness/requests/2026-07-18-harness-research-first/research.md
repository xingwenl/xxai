# 业界调研记录

## 调研问题

如何在不增加不必要流程负担的前提下，让 AI 开发新功能前参考业界成熟实践，并把方案选择依据沉淀到 Harness request 中？

## 参考依据

### 1. FastAPI 官方文档的应用结构建议

- 来源：[Bigger Applications - Multiple Files](https://fastapi.tiangolo.com/tutorial/bigger-applications/)
- 版本或日期：文档页面，调研日期 2026-07-18
- 核心做法：将路由按业务模块拆分，通过 `APIRouter` 组合到应用入口，避免所有路由和逻辑堆在单文件中。
- 对本项目的启发：新接口应在 spec 阶段明确模块边界，plan 阶段列出路由、schema、service 和测试文件。

### 2. FastAPI 官方文档的测试建议

- 来源：[Testing](https://fastapi.tiangolo.com/tutorial/testing/)
- 版本或日期：文档页面，调研日期 2026-07-18
- 核心做法：使用 `TestClient` 调用应用，结合 pytest 验证接口行为。
- 对本项目的启发：verify 阶段必须记录实际 pytest 命令和结果，不能只写“已测试”。

### 3. 12-Factor App 配置原则

- 来源：[The Twelve-Factor App - Config](https://12factor.net/config)
- 版本或日期：文档页面，调研日期 2026-07-18
- 核心做法：配置与代码分离，部署环境相关配置通过环境变量注入。
- 对本项目的启发：后续新增配置时必须在调研和 spec 中说明配置来源、默认值和秘密信息处理方式。

## 方案比较

| 方案 | 优点 | 限制 | 结论 |
|---|---|---|---|
| 只在聊天中讨论案例 | 速度快 | 无法追溯，容易遗漏来源和决策依据 | 不采用 |
| 所有任务都做同等深度调研 | 规则统一 | 简单任务成本过高，容易形成形式主义 | 不采用 |
| 按功能复杂度分级调研，并沉淀 `research.md` | 有证据、可追溯、成本可控 | 需要 AI 判断复杂度并维护来源 | 采用 |

## 最终决策

采用“`research -> spec -> plan -> implement -> verify -> acceptance`”流程。`research.md` 作为新 request 的必备文件，先于方案定稿；调研深度按小功能、普通业务功能、核心功能分级。普通概念问答、已有 spec 范围内的小修正不强制创建新的调研报告。

## 剩余风险

- 本次只建立文档规则，尚未自动校验链接有效性或来源时效。
- 后续核心功能需要结合具体领域补充安全、性能和生产案例，不能仅引用 FastAPI 通用文档。
