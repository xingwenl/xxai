---
source: script
request: 2026-10-20-user-memory
ranAt: "2026-10-20 18:33:15 CST"
exitCode: 0
---

## 已执行的命令与结果

工作目录：`/Users/lixingwen/xw/study/ai-base`；日期：2026-10-20 18:32:57 CST

### 1. 迁移 0043 与模型一致

命令：`sed -n "1,40p" apps/backend/migrations/versions/20261020_0043_user_memories.py`
```text
"""新增用户记忆表 user_memories

「把个人信息放进知识库」在检索上是错的：短事实与长文档的命中概率没有保证，
改一条事实还要重建索引。本表承载另一套机制——短条目、按 key 覆盖、问到才查：

- ``kind`` 区分事实（会变，覆盖时关闭旧行保留时间线）与经历（只追加）；
- 「同用户同 key 只有一条有效事实」由部分唯一索引
  ``uq_user_memories_active_fact`` 在数据库层保证，应用层先查再写在并发下会失效；
- 记忆内容**不进系统提示**（用户明确要求），只注入一行不含内容的条数索引，
  模型被问到时用 ``memory_search`` 取。

设计取舍见 docs/adr/0013-user-memory.md。

Revision ID: 20261020_0043
Revises: 20261019_0042
Create Date: 2026-10-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261020_0043"
down_revision: Union[str, None] = "20261019_0042"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_memories",
        sa.Column(
            "id",
            sa.Integer(),
            autoincrement=True,
            nullable=False,
            comment="用户记忆主键",
        ),
```
- ✔ 迁移链接在 0042 之后（down_revision=20261019_0042）

命令：`grep -n "uq_user_memories_active_fact\|ck_user_memories_\|create_table" apps/backend/migrations/versions/20261020_0043_user_memories.py`
```text
8:  ``uq_user_memories_active_fact`` 在数据库层保证，应用层先查再写在并发下会失效；
32:    op.create_table(
112:            "kind IN ('fact', 'event')", name="ck_user_memories_kind"
115:            "source IN ('explicit', 'inferred')", name="ck_user_memories_source"
118:            "kind = 'event' OR key IS NOT NULL", name="ck_user_memories_fact_key"
122:            name="ck_user_memories_event_valid_until",
126:            name="ck_user_memories_event_occurred_at",
139:        "uq_user_memories_active_fact",
149:        "uq_user_memories_active_fact",
```

部分唯一索引 where 子句出现次数：2；CheckConstraint 出现次数：5
- ✔ 存在「有效事实」部分唯一索引
- ✔ 5 个 CheckConstraint 齐全

### 2. 本人视图路由与业务工具注册

命令：`apps/backend/.venv/bin/python - <<PY ... PY`（建 app 读 openapi 与工具注册表）
```text
{
  "paths": [
    "/api/v1/platforms/{platform_id}/me/memories",
    "/api/v1/platforms/{platform_id}/me/memories/stats",
    "/api/v1/platforms/{platform_id}/me/memories/{memory_id}"
  ],
  "security": {
    "/api/v1/platforms/{platform_id}/me/memories": [
      {
        "HTTPBearer": []
      }
    ],
    "/api/v1/platforms/{platform_id}/me/memories/stats": [
      {
        "HTTPBearer": []
      }
    ]
  },
  "tools": {
    "remember_user_memory": "write",
    "forget_user_memory": "write",
    "memory_search": "none"
  }
}
```
- ✔ 列表/新增路由已注册
- ✔ 条数路由已注册
- ✔ remember_user_memory 声明 side_effect=write
- ✔ memory_search 声明 side_effect=none

### 3. 后端单测（tests/memory）

命令：`cd apps/backend && .venv/bin/python -m pytest tests/memory -q`
```text
....................                                                     [100%]
20 passed in 1.57s
```
- ✔ tests/memory 全部通过

### 4. 注入上下文的是条数，不是事实值

命令：`python -c "build_memory_index_line(2,1) 断言不含内容"`
```text
索引行包含条数： True
索引行包含使用规则： True
泄漏的事实值： []
```
- ✔ 索引行不含任何记忆内容

### 5. 无人值守写入返回 memory_principal_required

命令：`python - <<PY`（构造 unattended=True 的工具调用）
```text
status = failed
code = memory_principal_required
```
- ✔ 无人值守写入被拒绝且错误码正确

### 6. 前端记忆页与构建

命令：`ls apps/front/src/api/memory.ts apps/front/src/features/my-memory/index.tsx apps/front/src/routes/_authenticated/ai/my-memory.tsx`
apps/front/src/api/memory.ts
apps/front/src/features/my-memory/index.tsx
apps/front/src/routes/_authenticated/ai/my-memory.tsx

命令：`grep -n "my-memory" apps/front/src/components/layout/data/sidebar-data.ts`
```text
89:          url: '/ai/my-memory',
```
- ✔ 侧栏已挂载「用户记忆」入口

命令：`pnpm --dir apps/front exec vite build`
```text
[plugin builtin:vite-reporter] 
(!) Some chunks are larger than 500 kB after minification. Consider:
- Using dynamic import() to code-split the application
- Use build.rolldownOptions.output.codeSplitting to improve chunking: https://rolldown.rs/reference/OutputOptions.codeSplitting
- Adjust chunk size limit for this warning via build.chunkSizeWarningLimit.
✓ built in 710ms
```
- ✔ 前端 vite build 通过

命令：`pnpm --dir apps/front exec tsc -b`
```text
src/api/knowledge.test.ts(1,34): error TS2591: Cannot find name 'node:assert'. Do you need to install type definitions for node? Try `npm i --save-dev @types/node` and then add 'node' to the types field in your tsconfig.
src/features/agent-navigation/routes.test.ts(1,34): error TS2591: Cannot find name 'node:assert'. Do you need to install type definitions for node? Try `npm i --save-dev @types/node` and then add 'node' to the types field in your tsconfig.
src/features/agents/agent-usage-utils.test.ts(1,34): error TS2591: Cannot find name 'node:assert'. Do you need to install type definitions for node? Try `npm i --save-dev @types/node` and then add 'node' to the types field in your tsconfig.
```
存量报错（node:assert 类型缺失，来自 HEAD 已有的 *.test.ts 与 tsconfig，与本次改动无关）：3 条
- ✔ tsc 在本次新增文件上无报错（其余 3 条为存量问题）

## 未执行项与原因

- 真实数据库迁移：未执行 `alembic upgrade head`。验证环境没有 PostgreSQL，迁移文件只做静态一致性核对；真库执行由部署流程覆盖。
- 前端手动点检：未在浏览器里逐项点击新增/编辑/删除。验证只覆盖构建与入口存在，交互行为由单测与代码评审覆盖。
- 管理侧「只看条数」口径：路由层已无代查他人内容的入口，未做多账号越权测试（当前测试环境无第二账号）。

## 验收结论

- 结果：**全部通过**（13 项检查通过，0 失败）
- 退出码：0
