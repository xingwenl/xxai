# AI 管理后台模型用量统计设计

## 目标

在现有 Phase 2D 管理后台中增加“模型用量统计”页面，用于查看 `model_usage_records` 的明细与汇总。页面保持单页结构，顶部看概况，底部看明细，满足按 Agent / Client / 日期快速判断消耗情况的日常管理场景。

## 方案结论

采用单页两块内容的方案：

- 顶部：筛选条件、关键汇总卡片、按 Agent / Client / 日期切换的汇总区。
- 底部：可分页的明细表。

原因很简单：这类页面的核心诉求不是浏览，而是快速定位“谁在消耗、什么时候消耗、消耗多少”。把汇总和明细放在同一屏里，切换筛选时同步刷新，最符合后台管理的实际使用方式。

## 页面结构

- 路由建议：`/ai/model-usage`
- 入口位置：侧边栏 `AI 管理`
- 页面块：
  - 平台选择器
  - 日期范围筛选
  - Agent 筛选（来自当前平台已绑定的 Agent）
  - Embed Client 筛选（来自当前平台的 Embed Client）
  - 汇总卡片
  - 汇总分组切换：Agent / Client / 日期
  - 明细表

## 数据口径

查询对象只来自 `model_usage_records`，不回头从消息表或运行时事件拼凑。

默认统计口径：

- 时间范围按 `created_at` 过滤，前端选择的是自然日区间，后端按 `[start 00:00:00, end + 1 day 00:00:00)` 计算
- 日期分组按服务端默认时区截断为天
- 汇总展示三类指标：
  - 记录数
  - `prompt_tokens`
  - `completion_tokens`
  - `total_tokens`

## 后端接口

建议新增两个读取接口，保持职责清晰：

- `GET /api/v1/platforms/{platform_id}/model-usage-records`
  - 返回分页明细
  - 支持 `agent_id`、`client_id`、`start_date`、`end_date`、`page`、`page_size`
  - 返回字段包含：
    - `id`
    - `created_at`
    - `agent_id`、`agent_name`
    - `client_id`、`client_name`
    - `platform_end_user_id`
    - `conversation_id`
    - `request_id`
    - `model_name`
    - `prompt_tokens`
    - `completion_tokens`
    - `total_tokens`

- `GET /api/v1/platforms/{platform_id}/model-usage-records/summary`
  - 返回同一筛选条件下的汇总结果
  - 返回：
    - `totals`
    - `by_agent`
    - `by_client`
    - `by_day`

汇总接口一次返回三个分组，前端只需要一次请求就能驱动顶部三块汇总内容。

汇总卡片固定展示 4 个指标：

- 记录数
- `prompt_tokens`
- `completion_tokens`
- `total_tokens`

## 前端交互

页面默认加载最近 7 天数据。用户修改筛选后：

1. 重新拉取汇总数据。
2. 重新拉取分页明细。
3. 保持当前分组 tab，不强制跳回默认视图。

展示方式：

- `Agent` tab：按总 token 降序展示 Agent 聚合结果，辅助判断哪个 Agent 最耗。
- `Client` tab：按总 token 降序展示 Embed Client 聚合结果，帮助定位哪个客户端流量更大。
- `日期` tab：按日期升序展示每日聚合结果，帮助观察峰值和异常日。

明细表优先展示最有操作价值的列：

- 时间
- Agent
- Client
- 最终用户
- 会话
- 请求 ID
- 模型名
- token 三列

## 错误与空状态

- 没有数据时，汇总卡片显示 0，表格显示空状态。
- 筛选条件不合法时，由前端先做基础校验；后端仍保留 422 兜底。
- 平台管理员权限不足时沿用现有后台鉴权错误，不单独发明新错误语义。
- 不展示 `client_secret`、token、完整 prompt、完整回复或任何敏感参数。

## 性能与扩展

初版直接按时间范围和维度做 SQL 聚合，不引入物化汇总表。

如果后续数据量明显增大，再考虑补充组合索引或离线汇总层；当前阶段先保证路径短、可验证、可回滚。

## 测试策略

后端：

- repository / service 单测覆盖：
  - 按 Agent / Client / 日期分组正确
  - 日期范围边界正确
  - 空数据返回 0
- 路由测试覆盖：
  - 仅平台管理员可读取
  - 分页参数生效
  - 汇总接口和明细接口返回结构稳定

前端：

- 页面测试覆盖：
  - 默认 7 天范围
  - 筛选联动后汇总与明细一起刷新
  - 空状态与加载状态正常
- 保持现有管理后台组件风格，不新增独立图表库。

## 变更记录

### 2026-07-30 初始版本

- 变更原因：在 Phase 2D 管理后台中补齐模型用量查看与汇总能力。
- 变更内容：选定单页两块内容方案，定义汇总卡片、三种分组统计和明细表。
- 影响范围：后台页面、后端查询接口、筛选语义、测试。
