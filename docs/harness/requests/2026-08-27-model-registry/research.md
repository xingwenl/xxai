# 平台级模型注册表与 Agent 能力路由调研

## 调研问题

当前辅助模型（生图、读图、embedding）全部由全局 `.env` 配置，且不同模型能力不同（生成图片、读取图片、纯文本）。需求是把模型放到后台维护：`agent_versions` 保持"一个发布版本 = 主对话模型"不变，新增平台级模型注册表管理辅助模型，Agent 绑定模型并声明能力，工具调用按 capabilities 自动选择模型。调研重点是业界如何管理多模型目录、如何做能力感知的路由、以及凭据和默认模型如何处理。

## 功能复杂度

- 级别：核心功能
- 选择理由：涉及新增数据模型、平台管理 API、Agent 绑定关系，并改变内置工具与 embedding 的模型解析链路，属于架构边界变化。
- 最低调研要求：至少两个成熟开源/商业案例、两种以上方案比较、记录凭据管理和默认模型语义。

## 参考依据

### 来源 1

- 类型：成熟开源项目（代理网关）
- 名称：LiteLLM Proxy `model_list` 与 Router
- 链接：https://docs.litellm.ai/docs/proxy/model_management
- 版本或发布日期：在线文档，调研日期 2026-08-27
- 调研日期：2026-08-27
- 核心做法：LiteLLM 以 `model_list` 集中注册模型部署（`model_name`、`litellm_params` 内放 `api_key`、`api_base`、`model`），业务侧只感知 `model_name`，由 Router 按负载/延迟/优先级选择实际后端；凭据集中在部署条目内维护。
- 对本项目的启发：模型注册表应当集中维护"模型名 + base_url + api_key"，业务调用方只按逻辑名取用，不必感知真实后端；一个逻辑名可以对应一个具体模型，满足本项目"按 Agent 绑定"的最小诉求。

### 来源 2

- 类型：官方 API 文档
- 名称：OpenRouter List Models API（`architecture.input_modalities`）
- 链接：https://openrouter.ai/docs/api-reference/list-models
- 版本或发布日期：在线文档，调研日期 2026-08-27
- 调研日期：2026-08-27
- 核心做法：OpenRouter `/api/v1/models` 返回每个模型的 `architecture.input_modalities`（如 `text`、`image`、`file`）和 `output_modalities`，是权威的能力来源，调用方可按输入模态过滤模型。
- 对本项目的启发：模型注册表的 `capabilities` 字段沿用 Task 7 已经建立的语义（`image`、`native_file`、`text_retrieval`），并为生图模型补充输出能力标记；路由选择以显式配置优先、OpenRouter 探测次之、模型名兜底。

### 来源 3

- 类型：成熟开源项目（Agent 平台）
- 名称：Dify 模型供应商集成与模型选择
- 链接：https://enterprise-docs.dify.ai/en/3.6.x/use/model-configuration/predefined-model ；https://github.com/langgenius/dify/issues/23258
- 版本或发布日期：3.6.x 在线文档，调研日期 2026-08-27
- 调研日期：2026-08-27
- 核心做法：Dify 把模型按"供应商（Provider）"组织，凭据在供应商级统一管理，供应商下的模型可被多个应用选择；模型选择器按模型类型和能力过滤，Agent 使用工具时要求模型具备对应能力（issue #23258 提到模型需支持 tool 能力才可被 Agent 使用）。
- 对本项目的启发：凭据应在模型条目上维护一次、多处复用；Agent 绑定模型时按能力角色（生图/读图/embedding）过滤，避免把纯文本模型绑定到生图角色。

### 来源 4

- 类型：生产实践/研究方案
- 名称：Ema EmaFusion 模型目录与能力过滤路由
- 链接：https://builder.ema.ai/builder/v2/emafusion.md ；https://arxiv.org/abs/2504.02396
- 版本或发布日期：在线文档与 arXiv 论文（2025-04），调研日期 2026-08-27
- 调研日期：2026-08-27
- 核心做法：EmaFusion 维护一个跨供应商的模型目录，任务执行时先按子任务类型做能力过滤（candidate selection），再结合优先级、置信度和成本做级联选择；默认模型可作为未命中能力时的兜底。
- 对本项目的启发：路由语义为"按能力角色选模型，未绑定时回退全局配置"，可选用默认模型作为兜底，符合本项目当前规模。

## 方案比较

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| A：扩展 `agent_versions` 每版本维护多个模型 | 无新表，复用版本快照语义 | 版本间重复维护模型配置；主对话模型与辅助模型生命周期耦合；平台级模型无法跨 Agent 复用 | 低 |
| B：平台级模型注册表 + Agent 绑定表 | 模型配置平台级维护一次、多 Agent 复用；主对话仍由发布版本决定；按能力角色路由清晰；便于后台管理 | 新增两张表与两组 API；需要解析层兼容既有 `.env` 兜底 | 高 |
| C：全局模型注册表 + 配置文件路由 | 实现最少 | 不满足"按 Agent 绑定"，无法实现每 Agent 不同的辅助模型；与需求目标不符 | 低 |

## 最终决策

采用方案 B：新增平台级模型注册表 `platform_models` 与 Agent 绑定表 `agent_model_bindings`。主对话模型继续由发布版本 `agent_versions` 决定；生图、读图、embedding 等辅助模型由 Agent 绑定到注册表条目；未绑定或注册表未启用时回退到现有 `.env` 全局配置，保证兼容。注册表条目维护 `capabilities` 能力矩阵，路由时按能力角色过滤。
