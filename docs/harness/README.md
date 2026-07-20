# Harness Engineering

本目录承载仓库级 Harness Engineering 运行层，用来约束 AI 和人工如何以统一流程推进需求、落地实现、记录验证并完成验收。

## 目标

- 让每个需求都有独立工作区，避免设计、实现、验证记录散落在聊天里
- 让 AI 默认可以推进，但在高风险变更处必须停下等待人工确认
- 让文档、代码、验证结果形成可追溯闭环，适合 monorepo 长期维护

## 适用范围

- 默认适用于整个仓库
- 当前重点覆盖 `apps/backend/` 的 FastAPI 后端开发
- 目录与规则保留 monorepo 扩展能力，未来前端或其他服务可复用同一套 Harness

## 规则读取顺序

执行任务前按以下顺序读取规则：

1. 仓库根部的 `AGENTS.md`：仓库级强制约束
2. `policies/global.md`：跨模块通用流程、状态和审批规则
3. 专项规范，例如 `backend.md`：特定技术栈的补充约束
4. 当前 request 的 `research.md`：业界依据和方案比较
5. 当前 request 的 `spec.md`、`plan.md`：本次需求的具体边界和决策
6. 当前 request 的 `verify.md`、`acceptance.md`、`meta.json`：验证、验收和机器可读状态

规则发生冲突时，优先遵守上层规则；专项规范可以补充通用规则，但不能放宽人工确认条件。用户在当前对话中的明确要求优先于仓库文档。

## 目录结构

```text
docs/harness/
  README.md
  backend.md
  policies/
    global.md
  templates/
    research-template.md
    spec-template.md
    plan-template.md
    verify-template.md
    acceptance-template.md
    meta-template.json
  requests/
    <request-id>/
      research.md
      spec.md
      plan.md
      verify.md
      acceptance.md
      meta.json
  examples/
    golden-path.md
    fastapi-backend-example.md
  specs/
  plans/
```

目录职责：

- `policies/`：仓库规则与停点条件
- `templates/`：新 request 的起始模板
- `requests/<request-id>/`：单个需求的正式工作区
- `examples/`：命令示例、样例闭环、推荐写法
- `policies/global.md`：跨项目通用策略、状态定义和调研规则
- `specs/`：仓库级设计文档
- `plans/`：仓库级实施计划

## 标准阶段

所有正式任务必须遵守以下顺序：

1. `research`
2. `spec`
3. `plan`
4. `implement`
5. `verify`
6. `acceptance`

`meta.json` 是机器可读状态源，必须与文档阶段保持一致。

## 文档语言规则

- AI 生成的正式文档必须使用中文
- 代码、命令、路径、JSON 字段名、类名、函数名可保留英文
- 引用英文术语时，优先写中文说明，再保留必要英文原词

## 何时必须等待人工确认

遇到以下任一情况，AI 不能直接继续进入实现或宣称完成：

- 架构边界变化
- 数据模型变化
- API 契约变化
- 鉴权或权限行为变化
- 核心功能缺少关键业界资料，无法可靠完成方案比较

推荐同时在 `meta.json` 中记录：

- `approvalRequired`
- `approvalGranted`
- `approvalReasons`
- `approvalRecords`

## Request 工作区规范

每个正式需求都应创建独立 request 目录：

- 路径：`docs/harness/requests/<request-id>/`
- 推荐命名：`YYYY-MM-DD-<topic>`
- `<topic>` 使用英文短语，便于路径与命令复用

每个 request 至少包含：

- `research.md`
- `spec.md`
- `plan.md`
- `verify.md`
- `acceptance.md`
- `meta.json`

推荐流程：

1. 复制 `templates/` 中模板创建 request
2. 先完成 `research.md`，了解官方文档、成熟开源项目或生产实践
3. 基于调研结论完成 `spec.md`
4. 再完成 `plan.md`
5. 实现代码
6. 记录 `verify.md`
7. 输出 `acceptance.md`
8. 最后同步更新 `meta.json`

### 调研阶段

新功能必须先完成业界调研，再定 spec 和 plan。调研深度按功能复杂度分级：小功能至少参考一个官方来源和一个成熟案例；普通业务功能比较两到三种方案；核心功能补充安全、性能、可观测性和生产实践分析。

`research.md` 必须记录来源链接、版本或发布日期、调研日期、参考方案的做法、限制、方案比较和最终决策。普通概念问答、已有 spec 范围内的不涉及边界变化的小修正，不要求新建调研报告。

## 常用入口指令

以下是仓库约定的入口指令。根部 `AGENTS.md` 只保留识别指令所需的最小动作，本节是完整语义的唯一维护位置。

| 指令 | 用途 | 是否新建 request |
|---|---|---|
| `/new <主题>` | 新功能、新模块或新的独立需求闭环 | 是 |
| `/modify <request-id 或主题>` | 原闭环内增量功能或设计调整 | 否，先判断是否可复用 |
| `/fix <request-id 或主题>` | 原闭环内 bug 修复 | 否，必须复用原 request |
| `/verify <request-id>` | 补充或重做验证记录 | 否 |
| `/accept <request-id>` | 补充验收结论 | 否 |

## `/new` 工作方式

适用于：

- 新功能
- 新模块
- 新接口族
- 原需求已经无法承载的新闭环

最低动作：

1. 生成新的 `request-id`
2. 创建 request 工作区
3. 编写 `research.md`
4. 基于调研结论编写 `spec.md`
5. 编写 `plan.md`
6. 如果触发人工确认，先完成确认
7. 再进入实现

阶段必须按以下条件流转：

- `research -> spec`：调研结论、来源和方案比较已记录
- `spec -> plan`：目标、范围、方案、风险和验收标准已确定
- `plan -> implement`：计划已完成，且人工确认已通过或明确不需要
- `implement -> verify`：实现已完成，或明确记录本次只涉及文档/配置
- `verify -> acceptance`：验证记录包含真实命令、结果、失败项和例外
- `acceptance -> done`：验收标准全部满足，剩余风险已记录
- 任意阶段 -> `blocked`：存在明确的人工确认、外部依赖或环境阻塞

## `/modify` 与 `/fix` 工作方式

`/modify` 和 `/fix` 的 request 复用、变更记录、调研补充条件、轻量模式和升级条件，统一遵守 [`policies/global.md`](policies/global.md)。本节只规定入口动作：先定位原 request，再根据全局策略判断是否复用和采用何种模式。

- `/modify`：原闭环内的增量功能或设计调整
- `/fix`：原闭环内的 bug 修复，必须在变更记录中标注 `fix`
- 无法确认是否仍属同一闭环时，不应强行复用，应改用 `/new`

## `/verify` 工作方式

1. 确认 request 的实现已完成，或明确记录当前只验证文档/配置
2. 执行与风险匹配的测试、静态检查、启动检查或人工核对
3. 在 `verify.md` 记录命令、预期结果、实际结果、失败项和例外
4. 不得用“已测试通过”替代真实验证证据

## `/accept` 工作方式

1. 对照 `spec.md` 的验收标准逐项核对
2. 汇总 `verify.md` 中已经完成的验证
3. 记录剩余风险、人工回归或联调要求
4. 明确当前是否达到验收标准，以及是否可以合并或归档

## 增量与轻量规则

增量 request 的复用条件、变更记录格式、轻量模式适用范围、最小痕迹和升级条件统一见 [`policies/global.md`](policies/global.md)。README 只在入口章节说明 `/modify` 和 `/fix` 如何触发这些规则，避免多处维护同一套政策。

## FastAPI 后端任务要求

涉及 `apps/backend/` 的需求，除遵守本文件外，还必须阅读并遵守：

- [backend.md](backend.md)

## 推荐命令

当前仓库尚未提供完整自动化脚本前，推荐先使用以下人工检查方式：

- `find docs/harness/requests/<request-id> -maxdepth 1 -type f | sort`
- `sed -n '1,220p' docs/harness/requests/<request-id>/research.md`
- `sed -n '1,220p' docs/harness/requests/<request-id>/spec.md`
- `sed -n '1,220p' docs/harness/requests/<request-id>/plan.md`
- `sed -n '1,220p' docs/harness/requests/<request-id>/verify.md`
- `sed -n '1,220p' docs/harness/requests/<request-id>/acceptance.md`

如果未来补充 `tools/harness/`，应继续保持 `meta.json` 为唯一结构化状态源。

## 审批记录示例

```json
{
  "approvalRequired": true,
  "approvalGranted": true,
  "approvalReasons": [
    "数据模型变化",
    "API 契约变化"
  ],
  "approvalRecords": [
    {
      "by": "user",
      "at": "2026-07-18",
      "scope": "新增用户表与用户创建接口",
      "note": "用户确认可以按当前设计继续实现"
    }
  ]
}
```

## 推荐实践

1. 在根仓库确定任务边界，不要跨任务混改
2. 先补 Harness 文档，再写实现代码
3. 验证记录必须写实际执行过的命令和结果
4. 验收记录必须明确是否可合并、是否有剩余风险
5. 同一需求涉及文档和代码时，优先保持单一闭环提交
