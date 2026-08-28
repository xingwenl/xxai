# DSH「万物皆插件」思想借鉴方案调研

## 调研问题

- 本次要解决什么问题：评估 DeepSeek Harness（DSH）"Everything is a Plugin" 架构思想对本仓库生产多租户 Agent 平台的借鉴价值，确定借鉴边界、可落地的增量点和必须规避的实践。
- 调研结果将影响哪些范围：工具注册表与依赖图（`apps/backend/app/modules/tools/`）、工具执行链路（`apps/backend/app/modules/gateway/dispatcher.py`）、工具元数据契约、Harness 平台原则文档。

## 功能复杂度

- 级别：核心功能（架构级）
- 选择理由：涉及工具依赖图校验、执行链路事件钩子、插件元数据规范，属于架构边界变化，按 Harness 规则进入实现前必须人工确认。
- 最低调研要求：官方来源 + 成熟开源案例 + 拆解/生产实践；两种以上方案比较；记录安全边界结论。

## 参考依据

### 来源 1

- 类型：官方文档 / 官方项目
- 名称：deepseek-ai/deepseek-harness 官方仓库
- 链接：https://github.com/deepseek-ai/deepseek-harness
- 版本或发布日期：v0.1 系列，developer preview；调研日期 2026-08-28
- 核心做法：MIT 开源的 Agent Harness，架构口号 "Everything is a Plugin"，基于 Cordis 插件系统构建；官方明示 "THERE WILL BE COMPATIBILITY-BREAKING CHANGES"，插件 API 与配置 schema 尚未稳定。
- 对本项目的启发：思想方向确认存在且被官方背书，但当前仍是快速迭代的 preview，不能把它的 API 形态当作稳定契约引入。

### 来源 2

- 类型：官方文档
- 名称：DeepSeek Harness 官方架构文档 `docs/architecture.zh.md`
- 链接：https://github.com/deepseek-ai/DeepSeek-Harness/blob/master/docs/architecture.zh.md
- 版本或发布日期：master 分支在线文档；调研日期 2026-08-28
- 核心做法：
  - Cordis 元框架只负责插件的加载/卸载、依赖与服务注入；模型适配器、工具注册表、会话日志、agent loop 全部是插件，"不存在需要打补丁的特权内核"。
  - seam（可替换能力）三件套：Service Definition / Provider / Consumer，替换 Provider 即可改变整个产品行为。
  - 事件即扩展点：轮次流中定义 `agent/pre-step`、`llm/stream`、`tools/pre-execute`、`tools/execute`、`tools/post-execute` 等 waterfall 事件，监听器可观察或拦截。
  - profile / bundle 配置树：按序叠加组合包与 patch 文件，用配置组装能力集合。
- 对本项目的启发：
  - "依赖显式化 + 可替换 seam" 与本仓库 basic/business/skill 分层同构，印证我们分层方向正确。
  - `tools/pre-execute` / `tools/post-execute` 事件正是本仓库工具执行链路可观测性缺的一环。
  - "无特权内核"对本仓库是反模式：安全原语必须收敛为平台代码。

### 来源 3

- 类型：成熟开源项目（底层框架）
- 名称：Cordis（cordiverse/cordis）
- 链接：https://github.com/cordiverse/cordis
- 版本或发布日期：在线仓库；调研日期 2026-08-28
- 核心做法：元框架，只负责插件的加载/卸载与依赖关系管理，能力全部由插件提供；插件通过服务与事件协作，卸载时撤销其注册副作用。
- 对本项目的启发：依赖图、生命周期、服务注入是插件化的核心价值；其中依赖图部分值得以低成本方式借鉴。

### 来源 4

- 类型：生产实践 / 拆解文章
- 名称：DSH 拆解与社区讨论（雷峰网、网易、DataLearner、GitHub Discussion #2536）
- 链接：
  - https://m.leiphone.com/category/ai/u43j44fx6Rly10nI.html （2026-08-16）
  - https://m.163.com/dy/article/L4AHS9B70518R7MO.html （2026-08-14）
  - https://www.datalearner.com/blog/deepseek-harness-agent-runtime-framework （2026-08-14）
  - https://github.com/deepseek-ai/deepseek-harness/discussions/2536 （2026-08-15）
- 版本或发布日期：2026-08 期间；调研日期 2026-08-28
- 核心做法：拆解确认 DSH 没有"核心 Harness vs 外挂插件"之分，Harness 自己由插件拼装；同时指出自修改/自进化在长期运行下有状态残留、恢复与复杂度成本；社区普遍认为 preview 迭代过快、升级路径缺失是早期采用者最大摩擦。
- 对本项目的启发：运行时自进化/自替换核心组件是宣传价值大于生产价值；对多租户系统而言热替换核心组件是审计与安全灾难，应明确排除。

### 来源 5

- 类型：成熟开源项目（渐进式插件化对照）
- 名称：OpenAI Agents SDK Lifecycle Hooks；Dify Plugin System
- 链接：
  - https://openai.github.io/openai-agents-python/ref/lifecycle/
  - https://dify.ai/blog/introducing-dify-plugins
  - https://dify.ai/blog/dify-plugin-system-design-and-implementation
- 版本或发布日期：在线文档；调研日期 2026-08-28
- 核心做法：OpenAI Agents SDK 提供 RunHooks/AgentHooks 生命周期钩子（agent run、tool call、handoff 前后），是观察者机制，不修改核心执行流程；Dify 将模型、工具、扩展插件化，但平台核心（工作流引擎、权限、沙箱）保持内置，插件通过受限反向调用访问内部服务。
- 对本项目的启发：成熟平台普遍采用"外围可扩展、核心收敛"的渐进式插件化，而非全插件化；生命周期钩子先做观测、不拦截，是业界通行做法，与本仓库"先只做可观测"的增量一致。

## 方案比较

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| A：全盘 Cordis 化，照搬 DSH | 与 DSH 同构，最大化组件可替换性 | 需重写工具、会话、loop 全部注册链路；DSH 自身仍在 breaking 阶段；多租户安全原语不能插件化；成本与风险极高 | 低 |
| B：借鉴边界思想，做 4 个增量点加固 | 成本低，贴合现有 basic/business/skill 分层；依赖图、元数据、事件钩子均可独立验证；安全原语继续收敛 | 不能获得 DSH 的完整可替换性；增量点需人工确认范围 | 高 |
| C：不借鉴，保持现状 | 零成本、零风险 | 丢失依赖环检测、执行可观测钩子、元数据规范等低成本收益 | 低 |

## 最终决策

- 选择方案：方案 B（借鉴边界思想，做增量加固）
- 选择原因：本仓库已有 `basic_tool`/`business_tool` 注册表、`depends_on` 启动校验、`model_registry` 按角色路由，本身就是"边界即接口"的生产化版本；DSH/Cordis 帮我们把依赖图、插件元数据、组合配置这几个增量点排了优先级。
- 不选择其他方案的原因：方案 A 违背"平台原语收敛"硬约束，且 DSH 尚未稳定；方案 C 放弃低成本、可验证的收益。
- 对后续 spec、plan 或人工确认的影响：spec 将包含 4 个增量点 + 1 条平台原则；因涉及架构边界变化（依赖图校验、执行链路事件钩子），进入实现前需人工确认。

## 剩余风险

- 资料时效性：DSH 处于快速迭代期，本次只借鉴架构思想，不引入其 API 或实现。
- 与本项目上下文的差异：DSH 是单机开源工具，本仓库是生产多租户平台，鉴权、SSRF 防护、密钥管理、资产权限隔离必须保持平台收敛代码，不能做成可热替换插件。
- 尚未验证的假设：事件钩子对 dispatcher 的运行时开销——方案限定为异步发布、先只做可观测，实施时通过压测/日志确认不阻塞工具执行。
