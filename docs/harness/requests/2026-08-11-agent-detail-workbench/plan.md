# 智能体详情工作台实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把智能体管理从“列表 + 弹窗”重构为“列表 + 独立详情工作台”，在详情页内完成概览、配置、知识库/技能/工具关联、版本管理和当前智能体用量查看。

**Architecture:** 保留现有前后端模块与权限边界；后端在 agent 模块新增详情读取，在 knowledge 模块新增按智能体查询/解除关联接口，技能/MCP/宿主/内置工具与用量全部复用现有接口；前端新增 `/ai/bots/:agentId` 详情路由和七个一级标签，标签状态写入 URL search，关联变更保存后立即生效。

**Tech Stack:** FastAPI + SQLAlchemy Async + Pydantic v2（后端）；React 19 + TanStack Router/Query + shadcn/ui + Tailwind + recharts（前端）。

---

## 变更文件总览

| 类型 | 文件 | 职责 |
|---|---|---|
| 后端修改 | `apps/backend/app/modules/agent/schemas.py` | 新增 `AgentDetailRead` |
| 后端修改 | `apps/backend/app/modules/agent/repositories.py` | 新增 `get_agent_detail` |
| 后端修改 | `apps/backend/app/modules/agent/router.py` | 新增 `GET /agents/{agent_id}` |
| 后端修改 | `apps/backend/app/modules/knowledge/schemas.py` | 新增 `AgentKnowledgeBaseRead` |
| 后端修改 | `apps/backend/app/modules/knowledge/repositories.py` | 新增按智能体查询/解除关联 |
| 后端修改 | `apps/backend/app/modules/knowledge/router.py` | 新增 agent 作用域路由 `knowledge_agent_router` |
| 后端修改 | `apps/backend/app/__init__.py` | 注册 `knowledge_agent_router` |
| 后端测试 | `apps/backend/tests/agent/test_agent_routes.py`、`test_agent_repository.py` | 详情接口注册与仓储行为 |
| 后端测试 | `apps/backend/tests/knowledge/test_knowledge_routes.py`、`test_agent_bindings.py` | 关联接口注册与仓储行为 |
| 前端修改 | `apps/front/src/api/agent.ts` | `getAgent` 与 `AgentDetail` |
| 前端修改 | `apps/front/src/api/knowledge.ts` | 查询/解除知识库关联 |
| 前端新增 | `apps/front/src/features/agents/agent-usage-utils.ts` | 日期区间、数字格式化、环比 |
| 前端新增 | `apps/front/src/features/agents/agent-usage-utils.test.ts` | 工具函数断言 |
| 前端修改 | `apps/front/src/features/agents/index.tsx` | 列表页：搜索、状态筛选、详情入口 |
| 前端新增 | `apps/front/src/routes/_authenticated/ai/bots.$agentId.tsx` | 详情路由 |
| 前端新增 | `apps/front/src/features/agents/agent-detail-page.tsx` | 详情页骨架与一级标签 |
| 前端新增 | `apps/front/src/features/agents/agent-form-schema.ts` | 共享基础信息校验 |
| 前端新增 | `apps/front/src/features/agents/agent-version-form.tsx` | 共享版本表单 |
| 前端新增 | `apps/front/src/features/agents/agent-overview-tab.tsx` | 概览 |
| 前端新增 | `apps/front/src/features/agents/agent-config-tab.tsx` | 配置 + 删除 |
| 前端新增 | `apps/front/src/features/agents/agent-versions-tab.tsx` | 版本 |
| 前端新增 | `apps/front/src/features/agents/agent-knowledge-tab.tsx` | 知识库关联 |
| 前端新增 | `apps/front/src/features/agents/agent-skills-tab.tsx` | 技能关联 |
| 前端新增 | `apps/front/src/features/agents/agent-tools-tab.tsx` | 工具子标签容器 |
| 前端新增 | `apps/front/src/features/agents/builtin-tools-section.tsx` | 内置工具关联 |
| 前端新增 | `apps/front/src/features/agents/mcp-tools-section.tsx` | MCP 服务关联 |
| 前端新增 | `apps/front/src/features/agents/host-tools-section.tsx` | 宿主工具关联 |
| 前端新增 | `apps/front/src/features/agents/association-toolbar.tsx` | 搜索/状态筛选工具条 |
| 前端删除 | `apps/front/src/features/agents/builtin-tools-dialog.tsx` | 已由内置工具 Section 替代 |
| 前端修改 | `apps/front/src/routes/_authenticated/ai/model-usage.tsx` | 支持 `platform`/`agent` search |
| 前端修改 | `apps/front/src/features/model-usage/index.tsx` | 接受初始平台/智能体 |
| 文档 | `docs/harness/requests/2026-08-11-agent-detail-workbench/meta.json`、`spec.md`、`verify.md`、`acceptance.md` | 阶段流转与记录 |

## 前置条件

- 后端：`cd apps/backend && poetry install`（若 `.venv` 不存在；网络受限时需批准）。
- 前端：`cd apps/front && pnpm install`（若 `node_modules` 不存在）。
- 每次提交前运行 `git status --short`，只暂存本任务相关文件。

## Task 1: 后端智能体详情接口

**Files:**
- Modify: `apps/backend/app/modules/agent/schemas.py`
- Modify: `apps/backend/app/modules/agent/repositories.py`
- Modify: `apps/backend/app/modules/agent/router.py`
- Modify: `apps/backend/tests/agent/test_agent_routes.py`
- Create: `apps/backend/tests/agent/test_agent_repository.py`

- [ ] **Step 1: 写失败测试（路由注册 + 仓储行为）**

在 `apps/backend/tests/agent/test_agent_routes.py` 追加：

```python
def test_agent_detail_route_requires_get() -> None:
    paths = app.openapi()["paths"]
    path = "/api/v1/platforms/{platform_id}/agents/{agent_id}"
    assert "get" in paths[path]
```

新建 `apps/backend/tests/agent/test_agent_repository.py`：

```python
"""智能体详情仓储测试。"""
import asyncio
from datetime import UTC, datetime

from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.agent.models import Agent, AgentVersion
from app.modules.agent.repositories import AgentRepository
from app.modules.platform.models import Platform
from app.shared.base_model import BaseModel


async def _make_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(BaseModel.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def test_get_agent_detail_loads_current_version_and_isolates_platform():
    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform = Platform(name="Acme", code="acme")
            other_platform = Platform(name="Other", code="other")
            session.add_all([platform, other_platform])
            await session.flush()
            agent = Agent(platform_id=platform.id, name="客服", slug="support")
            other_agent = Agent(
                platform_id=other_platform.id, name="Other", slug="other"
            )
            session.add_all([agent, other_agent])
            await session.flush()
            version = AgentVersion(
                agent_id=agent.id,
                version=1,
                system_prompt="你是客服助手",
                model_name="gpt-4o-mini",
                temperature=0.2,
                created_at=datetime.now(UTC),
                published_at=datetime.now(UTC),
            )
            session.add(version)
            await session.flush()
            agent.default_version_id = version.id
            await session.commit()

            repo = AgentRepository(session)
            detail = await repo.get_agent_detail(agent.id, platform.id)
            assert detail is not None
            assert detail.default_version_id == version.id
            assert detail.default_version is not None
            assert detail.default_version.model_name == "gpt-4o-mini"

            assert await repo.get_agent_detail(agent.id, other_platform.id) is None

        await engine.dispose()

    asyncio.run(run())
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/backend && poetry run pytest tests/agent/test_agent_routes.py tests/agent/test_agent_repository.py -q`
Expected: `test_agent_detail_route_requires_get` 与仓储测试 FAIL（`AttributeError: 'AgentRepository' object has no attribute 'get_agent_detail'` / 断言失败）。

- [ ] **Step 3: 实现 schema、仓储与路由**

`apps/backend/app/modules/agent/schemas.py` 在 `AgentVersionRead` 之后追加：

```python
class AgentDetailRead(AgentRead):
    current_version: AgentVersionRead | None = None
```

`apps/backend/app/modules/agent/repositories.py` 在 `get_agent` 之后追加：

```python
    async def get_agent_detail(self, agent_id: int, platform_id: int) -> Agent | None:
        result = await self.session.execute(
            select(Agent)
            .options(selectinload(Agent.default_version))
            .where(Agent.id == agent_id, Agent.platform_id == platform_id)
        )
        return result.scalar_one_or_none()
```

`apps/backend/app/modules/agent/router.py`：在 `AgentDetailRead` 加入导入列表，并在 `update_agent_endpoint` 之前新增：

```python
@router.get("/{agent_id}", response_model=ApiResponse[AgentDetailRead])
async def get_agent_endpoint(
    platform_id: int,
    agent_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[AgentDetailRead]:
    await _require_platform_admin(platform_id, current_user.id, session)
    agent = await AgentRepository(session).get_agent_detail(agent_id, platform_id)
    if agent is None:
        raise NotFoundException("agent not found")
    data = AgentDetailRead.model_validate(
        {
            **agent.__dict__,
            "current_version": (
                _version_read(agent.default_version)
                if agent.default_version is not None
                else None
            ),
        }
    )
    return success_response(data=data, message="agent fetched")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/backend && poetry run pytest tests/agent -q`
Expected: PASS，全部通过。

- [ ] **Step 5: 提交**

```bash
git add apps/backend/app/modules/agent/schemas.py apps/backend/app/modules/agent/repositories.py apps/backend/app/modules/agent/router.py apps/backend/tests/agent
git commit -m "feat(agent): 新增智能体详情读取接口"
```

## Task 2: 后端知识库按智能体查询与解除关联

**Files:**
- Modify: `apps/backend/app/modules/knowledge/schemas.py`
- Modify: `apps/backend/app/modules/knowledge/repositories.py`
- Modify: `apps/backend/app/modules/knowledge/router.py`
- Modify: `apps/backend/app/__init__.py`
- Modify: `apps/backend/tests/knowledge/test_knowledge_routes.py`
- Create: `apps/backend/tests/knowledge/test_agent_bindings.py`

- [ ] **Step 1: 写失败测试**

`apps/backend/tests/knowledge/test_knowledge_routes.py` 追加：

```python
def test_agent_knowledge_routes_are_registered() -> None:
    paths = app.openapi()["paths"]
    list_path = (
        "/api/v1/platforms/{platform_id}/agents/{agent_id}/knowledge-bases"
    )
    unbind_path = (
        "/api/v1/platforms/{platform_id}/agents/{agent_id}/knowledge-bases/{base_id}"
    )
    assert list_path in paths
    assert unbind_path in paths
    assert "get" in paths[list_path]
    assert "delete" in paths[unbind_path]
```

新建 `apps/backend/tests/knowledge/test_agent_bindings.py`：

```python
"""智能体知识库关联仓储测试。"""
import asyncio

from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.agent.models import Agent
from app.modules.knowledge.models import KnowledgeBase, KnowledgeDocument
from app.modules.knowledge.repositories import KnowledgeRepository
from app.modules.platform.models import Platform
from app.shared.base_model import BaseModel


async def _make_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(BaseModel.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def test_agent_bindings_are_isolated_and_unbind_is_idempotent():
    async def run():
        engine, session_factory = await _make_session()
        async with session_factory() as session:
            platform = Platform(name="Acme", code="acme")
            other_platform = Platform(name="Other", code="other")
            session.add_all([platform, other_platform])
            await session.flush()
            agent = Agent(platform_id=platform.id, name="客服", slug="support")
            session.add(agent)
            await session.flush()
            base = KnowledgeBase(
                platform_id=platform.id,
                name="产品手册",
                slug="manual",
                embedding_model="text-embedding-3-small",
                embedding_dimension=1536,
            )
            other_base = KnowledgeBase(
                platform_id=other_platform.id,
                name="其他平台资料",
                slug="other",
                embedding_model="text-embedding-3-small",
                embedding_dimension=1536,
            )
            session.add_all([base, other_base])
            await session.flush()
            session.add(
                KnowledgeDocument(
                    knowledge_base_id=base.id,
                    source_type="file",
                    title="手册.pdf",
                    status="ready",
                )
            )
            await session.commit()

            repo = KnowledgeRepository(session)
            await repo.bind_to_agent(agent.id, base.id, platform.id, 0)
            await repo.bind_to_agent(agent.id, other_base.id, platform.id, 0)

            rows = await repo.list_agent_bindings(platform.id, agent.id)
            assert len(rows) == 1
            assert rows[0]["knowledge_base_id"] == base.id
            assert rows[0]["name"] == "产品手册"
            assert rows[0]["document_count"] == 1
            assert rows[0]["has_embedding_api_key"] is False

            assert await repo.unbind_agent(agent.id, base.id, platform.id) is True
            assert await repo.unbind_agent(agent.id, base.id, platform.id) is False
            assert (
                await repo.unbind_agent(agent.id, other_base.id, platform.id)
                is False
            )

        await engine.dispose()

    asyncio.run(run())
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd apps/backend && poetry run pytest tests/knowledge/test_knowledge_routes.py tests/knowledge/test_agent_bindings.py -q`
Expected: 注册断言 FAIL；仓储测试 FAIL（方法不存在）。

- [ ] **Step 3: 实现 schema、仓储、路由并注册**

`apps/backend/app/modules/knowledge/schemas.py` 在 `AgentKnowledgeBaseBind` 前追加：

```python
class AgentKnowledgeBaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    agent_id: int
    knowledge_base_id: int
    is_enabled: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime
    name: str
    slug: str
    embedding_model: str
    active_index_version: int
    has_embedding_api_key: bool = False
    document_count: int = 0
```

`apps/backend/app/modules/knowledge/repositories.py` 追加两个方法：

```python
    async def list_agent_bindings(self, platform_id: int, agent_id: int):
        document_count = (
            select(func.count(KnowledgeDocument.id))
            .where(KnowledgeDocument.knowledge_base_id == KnowledgeBase.id)
            .scalar_subquery()
        )
        statement = (
            select(
                AgentKnowledgeBase,
                KnowledgeBase,
                document_count.label("document_count"),
            )
            .join(
                KnowledgeBase,
                KnowledgeBase.id == AgentKnowledgeBase.knowledge_base_id,
            )
            .where(
                AgentKnowledgeBase.agent_id == agent_id,
                KnowledgeBase.platform_id == platform_id,
            )
            .order_by(AgentKnowledgeBase.sort_order, KnowledgeBase.id)
        )
        rows = (await self.session.execute(statement)).all()
        return [
            {
                **base.__dict__,
                **binding.__dict__,
                "document_count": int(document_count or 0),
                "has_embedding_api_key": bool(base.embedding_api_key_encrypted),
            }
            for binding, base, document_count in rows
        ]

    async def unbind_agent(
        self, agent_id: int, knowledge_base_id: int, platform_id: int
    ) -> bool:
        binding = await self.session.scalar(
            select(AgentKnowledgeBase)
            .join(
                KnowledgeBase,
                KnowledgeBase.id == AgentKnowledgeBase.knowledge_base_id,
            )
            .where(
                AgentKnowledgeBase.agent_id == agent_id,
                AgentKnowledgeBase.knowledge_base_id == knowledge_base_id,
                KnowledgeBase.platform_id == platform_id,
            )
        )
        if binding is None:
            return False
        await self.session.delete(binding)
        await self.session.commit()
        return True
```

`apps/backend/app/modules/knowledge/router.py` 追加导入与第二个路由器（放在 `router` 定义之后）：

```python
from app.modules.agent.repositories import AgentRepository
from app.modules.knowledge.schemas import (
    ...,
    AgentKnowledgeBaseRead,
)

knowledge_agent_router = APIRouter(
    prefix="/platforms/{platform_id}/agents", tags=["knowledge-agent"]
)


@knowledge_agent_router.get(
    "/{agent_id}/knowledge-bases",
    response_model=ApiResponse[list[AgentKnowledgeBaseRead]],
)
async def list_agent_knowledge_bases_endpoint(
    platform_id: int,
    agent_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _require_admin(platform_id, current_user.id, session)
    if await AgentRepository(session).get_agent(agent_id, platform_id) is None:
        raise NotFoundException("agent not found")
    rows = await KnowledgeRepository(session).list_agent_bindings(
        platform_id, agent_id
    )
    return success_response(
        data=[AgentKnowledgeBaseRead.model_validate(row) for row in rows],
        message="agent knowledge bases listed",
    )


@knowledge_agent_router.delete(
    "/{agent_id}/knowledge-bases/{base_id}",
    response_model=ApiResponse[None],
)
async def unbind_agent_knowledge_base_endpoint(
    platform_id: int,
    agent_id: int,
    base_id: int,
    current_user=Depends(require_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _require_admin(platform_id, current_user.id, session)
    if await AgentRepository(session).get_agent(agent_id, platform_id) is None:
        raise NotFoundException("agent not found")
    if not await KnowledgeRepository(session).unbind_agent(
        agent_id, base_id, platform_id
    ):
        raise NotFoundException("knowledge base binding not found")
    return success_response(message="knowledge base unbound")
```

`apps/backend/app/__init__.py`：导入与注册改为：

```python
from app.modules.knowledge.router import (
    knowledge_agent_router,
    router as knowledge_router,
)
...
    app.include_router(knowledge_router, prefix=settings.api_v1_prefix)
    app.include_router(knowledge_agent_router, prefix=settings.api_v1_prefix)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd apps/backend && poetry run pytest tests/knowledge tests/agent -q`
Expected: PASS，全部通过。

- [ ] **Step 5: 提交**

```bash
git add apps/backend/app/modules/knowledge apps/backend/app/__init__.py apps/backend/tests/knowledge
git commit -m "feat(knowledge): 支持按智能体查询与解除知识库关联"
```

## Task 3: 前端 API 层与工具函数

**Files:**
- Modify: `apps/front/src/api/agent.ts`
- Modify: `apps/front/src/api/knowledge.ts`
- Create: `apps/front/src/features/agents/agent-usage-utils.ts`
- Create: `apps/front/src/features/agents/agent-usage-utils.test.ts`

- [ ] **Step 1: 写失败测试（工具函数）**

新建 `apps/front/src/features/agents/agent-usage-utils.test.ts`：

```ts
import { strict as assert } from 'node:assert'
import { formatNumber, getUsageRanges, percentChange } from './agent-usage-utils'

const ranges = getUsageRanges(7)
assert.equal(ranges.start.length, 10)
assert.equal(ranges.start <= ranges.end, true)
assert.equal(ranges.previousEnd < ranges.start, true)
assert.equal(ranges.previousStart <= ranges.previousEnd, true)
assert.equal(formatNumber(1234567), '1,234,567')
assert.equal(percentChange(120, 100), '+20.0%')
assert.equal(percentChange(80, 100), '-20.0%')
assert.equal(percentChange(100, 0), null)
```

- [ ] **Step 2: 运行测试确认失败**

Run（仓库既有模式：先 tsc 编译到临时目录再 node 执行）：

```bash
cd apps/front && pnpm exec tsc --target es2022 --module commonjs --moduleResolution node --outDir /tmp/agent-usage-utils src/features/agents/agent-usage-utils.ts src/features/agents/agent-usage-utils.test.ts && node /tmp/agent-usage-utils/features/agents/agent-usage-utils.test.js
```

Expected: FAIL（`agent-usage-utils` 模块不存在）。

- [ ] **Step 3: 实现 API 函数与工具函数**

`apps/front/src/api/agent.ts` 在 `AgentVersion` 类型后追加：

```ts
export type AgentDetail = Agent & {
  current_version: AgentVersion | null
}

export async function getAgent(
  platformId: number,
  agentId: number
): Promise<AgentDetail> {
  const { data } = await http.get<AgentDetail>(
    `/platforms/${platformId}/agents/${agentId}`
  )
  return data
}
```

`apps/front/src/api/knowledge.ts` 在 `AgentKnowledgeBaseBinding` 后追加：

```ts
export type AgentKnowledgeBaseBindingDetail = {
  id: number
  agent_id: number
  knowledge_base_id: number
  is_enabled: boolean
  sort_order: number
  created_at: string
  updated_at: string
  name: string
  slug: string
  embedding_model: string
  active_index_version: number
  has_embedding_api_key: boolean
  document_count: number
}

export async function listAgentKnowledgeBases(
  platformId: number,
  agentId: number
): Promise<AgentKnowledgeBaseBindingDetail[]> {
  const { data } = await http.get<AgentKnowledgeBaseBindingDetail[]>(
    `/platforms/${platformId}/agents/${agentId}/knowledge-bases`
  )
  return data ?? []
}

export async function unbindKnowledgeBaseAgent(
  platformId: number,
  agentId: number,
  baseId: number
) {
  await http.delete(
    `/platforms/${platformId}/agents/${agentId}/knowledge-bases/${baseId}`
  )
}
```

新建 `apps/front/src/features/agents/agent-usage-utils.ts`：

```ts
const DAY_MS = 24 * 60 * 60 * 1000

function toDateInput(value: Date) {
  return value.toISOString().slice(0, 10)
}

export type UsageRange = {
  start: string
  end: string
  previousStart: string
  previousEnd: string
}

export function getUsageRanges(days: 7 | 30): UsageRange {
  const end = new Date()
  const start = new Date(end.getTime() - (days - 1) * DAY_MS)
  const previousEnd = new Date(start.getTime() - DAY_MS)
  const previousStart = new Date(start.getTime() - days * DAY_MS)
  return {
    start: toDateInput(start),
    end: toDateInput(end),
    previousStart: toDateInput(previousStart),
    previousEnd: toDateInput(previousEnd),
  }
}

export function formatNumber(value: number) {
  return new Intl.NumberFormat('zh-CN').format(value)
}

export function percentChange(current: number, previous: number): string | null {
  if (previous === 0) return null
  const delta = ((current - previous) / previous) * 100
  return `${delta >= 0 ? '+' : ''}${delta.toFixed(1)}%`
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: 同 Step 2 命令
Expected: 输出为空且退出码 0（PASS）。

- [ ] **Step 5: 提交**

```bash
git add apps/front/src/api/agent.ts apps/front/src/api/knowledge.ts apps/front/src/features/agents/agent-usage-utils.ts apps/front/src/features/agents/agent-usage-utils.test.ts
git commit -m "feat(agent): 前端补充详情与知识库关联 API"
```

## Task 4: 智能体列表页重构

**Files:**
- Create: `apps/front/src/features/agents/agent-form-schema.ts`
- Modify: `apps/front/src/features/agents/index.tsx`

- [ ] **Step 1: 新增共享表单 schema**

新建 `apps/front/src/features/agents/agent-form-schema.ts`：

```ts
import { z } from 'zod'

export const agentSchema = z.object({
  name: z.string().min(1, '请输入名称').max(120),
  slug: z
    .string()
    .min(2, '标识至少 2 个字符')
    .regex(/^[a-z0-9][a-z0-9_-]*$/, '只允许小写字母、数字、下划线和短横线'),
  description: z.string().max(500).optional(),
  is_active: z.boolean(),
})

export type AgentForm = z.infer<typeof agentSchema>
```

- [ ] **Step 2: 改造列表页**

`apps/front/src/features/agents/index.tsx` 修改：

1. 删除本地 `const agentSchema` 与 `type AgentForm`，改为：

```ts
import { Link } from '@tanstack/react-router'
import { agentSchema, type AgentForm } from './agent-form-schema'
```

2. 删除与版本/工具/删除相关的状态与查询：

```ts
const [deleting, setDeleting] = useState<Agent | null>(null)
const [versionsForId, setVersionsForId] = useState<number | null>(null)
const [toolsForId, setToolsForId] = useState<number | null>(null)
const [versionDialog, setVersionDialog] = useState(false)
```

新增搜索与状态筛选状态：

```ts
const [keyword, setKeyword] = useState('')
const [status, setStatus] = useState('all')
```

3. 删除 `deleteMutation`、`versionsFor`、`toolsFor`、`invalidateAgents` 中仅服务于删除/版本的部分可保留 `invalidateAgents`（保存后仍需要）。渲染前计算过滤结果：

```ts
const filteredAgents = (agentsQuery.data?.items ?? []).filter((agent) => {
  const matchesKeyword =
    !keyword ||
    agent.name.includes(keyword) ||
    agent.slug.includes(keyword)
  const matchesStatus =
    status === 'all' ||
    (status === 'active' && agent.is_active) ||
    (status === 'inactive' && !agent.is_active)
  return matchesKeyword && matchesStatus
})
```

4. 在“新建智能体”按钮左侧新增搜索框与状态筛选：

```tsx
<Input
  value={keyword}
  onChange={(event) => setKeyword(event.target.value)}
  placeholder='搜索名称或标识'
  className='w-56'
/>
<Select value={status} onValueChange={setStatus}>
  <SelectTrigger className='w-32'>
    <SelectValue placeholder='全部状态' />
  </SelectTrigger>
  <SelectContent>
    <SelectItem value='all'>全部状态</SelectItem>
    <SelectItem value='active'>启用</SelectItem>
    <SelectItem value='inactive'>停用</SelectItem>
  </SelectContent>
</Select>
```

5. 表格 `TableBody` 中把 `agentsQuery.data.items.map(...)` 改为 `filteredAgents.map(...)`；操作列只保留“详情”入口：

```tsx
<TableCell className='text-end'>
  <Button
    size='sm'
    variant='outline'
    asChild
  >
    <Link
      to='/ai/bots/$agentId'
      params={{ agentId: String(agent.id) }}
      search={{ platform: activePlatformId }}
    >
      详情
    </Link>
  </Button>
</TableCell>
```

6. 删除列表页底部 `VersionsDialog`、`VersionFormDialog`、`BuiltinToolsDialog` 与 `AlertDialog` 渲染；保留 `AgentDialog`（新建/编辑基本信息）。同步删除不再使用的 import（`History`、`Wrench`、`Trash2`、`Edit`、`AlertDialog*`、`BuiltinToolsDialog`、`listAgentVersions`、`createAgentVersion`、`publishAgentVersion`、`rollbackAgentVersion`、`type AgentVersionInput`、`deleteAgent`）。

- [ ] **Step 3: 运行静态检查**

Run: `cd apps/front && pnpm exec eslint src/features/agents/index.tsx src/features/agents/agent-form-schema.ts && pnpm exec prettier --check src/features/agents/index.tsx src/features/agents/agent-form-schema.ts`
Expected: 退出码 0。

- [ ] **Step 4: 提交**

```bash
git add apps/front/src/features/agents/agent-form-schema.ts apps/front/src/features/agents/index.tsx
git commit -m "refactor(agent): 列表页收敛为搜索筛选与详情入口"
```

## Task 5: 详情路由与页面骨架

**Files:**
- Create: `apps/front/src/routes/_authenticated/ai/bots.$agentId.tsx`
- Create: `apps/front/src/features/agents/agent-detail-page.tsx`

- [ ] **Step 1: 创建详情路由**

新建 `apps/front/src/routes/_authenticated/ai/bots.$agentId.tsx`：

```tsx
import { createFileRoute } from '@tanstack/react-router'
import { z } from 'zod'
import { AgentDetailPage } from '@/features/agents/agent-detail-page'

const agentDetailSearch = z.object({
  platform: z.coerce.number().optional(),
  tab: z
    .enum([
      'overview',
      'config',
      'knowledge',
      'skills',
      'tools',
      'versions',
      'usage',
    ])
    .optional(),
})

export const Route = createFileRoute('/_authenticated/ai/bots/$agentId')({
  validateSearch: agentDetailSearch,
  component: AgentDetailPage,
})
```

- [ ] **Step 2: 创建详情页骨架**

新建 `apps/front/src/features/agents/agent-detail-page.tsx`：

```tsx
import { useQuery } from '@tanstack/react-query'
import { getRouteApi } from '@tanstack/react-router'
import { ArrowLeft, Boxes } from 'lucide-react'
import { getAgent } from '@/api/agent'
import { listPlatforms } from '@/api/platform'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '@/components/ui/tabs'
import { ConfigDrawer } from '@/components/config-drawer'
import { Header } from '@/components/layout/header'
import { Main } from '@/components/layout/main'
import { ProfileDropdown } from '@/components/profile-dropdown'
import { ThemeSwitch } from '@/components/theme-switch'
import { AgentConfigTab } from './agent-config-tab'
import { AgentKnowledgeTab } from './agent-knowledge-tab'
import { AgentOverviewTab } from './agent-overview-tab'
import { AgentSkillsTab } from './agent-skills-tab'
import { AgentToolsTab } from './agent-tools-tab'
import { AgentUsageTab } from './agent-usage-tab'
import { AgentVersionsTab } from './agent-versions-tab'

export type AgentTabKey =
  | 'overview'
  | 'config'
  | 'knowledge'
  | 'skills'
  | 'tools'
  | 'versions'
  | 'usage'

const routeApi = getRouteApi('/_authenticated/ai/bots/$agentId')

export function AgentDetailPage() {
  const { agentId } = routeApi.useParams()
  const search = routeApi.useSearch()
  const navigate = routeApi.useNavigate()
  const platformsQuery = useQuery({
    queryKey: ['platforms'],
    queryFn: listPlatforms,
  })
  const platformId = search.platform ?? platformsQuery.data?.[0]?.id
  const agentIdNumber = Number(agentId)
  const tab = search.tab ?? 'overview'
  const agentQuery = useQuery({
    queryKey: ['agent', platformId, agentIdNumber],
    queryFn: () => getAgent(platformId!, agentIdNumber),
    enabled: platformId != null,
  })
  const agent = agentQuery.data
  const currentVersion = agent?.current_version

  return (
    <>
      <Header fixed>
        <div />
        <div className='ms-auto flex items-center space-x-4'>
          <ThemeSwitch />
          <ConfigDrawer />
          <ProfileDropdown />
        </div>
      </Header>
      <Main className='flex flex-1 flex-col gap-4 sm:gap-6'>
        <Button
          variant='ghost'
          size='sm'
          className='w-fit'
          onClick={() =>
            navigate({ to: '/ai/bots', search: { platform: platformId } })
          }
        >
          <ArrowLeft className='size-4' />
          智能体列表
        </Button>
        <div className='flex flex-wrap items-start justify-between gap-3'>
          <div className='flex items-center gap-3'>
            <div className='flex size-11 items-center justify-center rounded-md bg-muted'>
              <Boxes className='size-5 text-muted-foreground' />
            </div>
            <div>
              <div className='flex flex-wrap items-center gap-2'>
                <h2 className='text-2xl font-bold tracking-tight'>
                  {agentQuery.isLoading ? (
                    <Skeleton className='h-7 w-40' />
                  ) : (
                    (agent?.name ?? '智能体')
                  )}
                </h2>
                {agent && (
                  <Badge variant={agent.is_active ? 'default' : 'secondary'}>
                    {agent.is_active ? '启用' : '停用'}
                  </Badge>
                )}
              </div>
              <div className='mt-1 text-sm text-muted-foreground'>
                {agent ? `${agent.slug} · 当前配置实时生效` : ''}
              </div>
            </div>
          </div>
          <div className='text-sm text-muted-foreground'>
            {currentVersion ? (
              <>
                当前版本{' '}
                <span className='font-medium text-foreground'>
                  v{currentVersion.version}
                </span>
                <span className='mx-2'>·</span>
                {currentVersion.model_name}
              </>
            ) : agent ? (
              '尚未发布版本'
            ) : null}
          </div>
        </div>
        {agentQuery.isError && (
          <div className='flex min-h-24 flex-col items-center justify-center gap-3 rounded-md border border-dashed p-6 text-center'>
            <p className='text-sm text-muted-foreground'>智能体加载失败</p>
            <Button
              size='sm'
              variant='outline'
              onClick={() => agentQuery.refetch()}
              disabled={agentQuery.isFetching}
            >
              重试
            </Button>
          </div>
        )}
        <Tabs
          value={tab}
          onValueChange={(value) =>
            navigate({
              search: { platform: platformId, tab: value as AgentTabKey },
            })
          }
          className='gap-0'
        >
          <TabsList className='h-auto w-full justify-start overflow-x-auto rounded-lg'>
            <TabsTrigger value='overview'>概览</TabsTrigger>
            <TabsTrigger value='config'>配置</TabsTrigger>
            <TabsTrigger value='knowledge'>知识库</TabsTrigger>
            <TabsTrigger value='skills'>技能</TabsTrigger>
            <TabsTrigger value='tools'>工具</TabsTrigger>
            <TabsTrigger value='versions'>版本</TabsTrigger>
            <TabsTrigger value='usage'>用量</TabsTrigger>
          </TabsList>
          <TabsContent value='overview'>
            <AgentOverviewTab
              platformId={platformId}
              agentId={agentIdNumber}
            />
          </TabsContent>
          <TabsContent value='config'>
            <AgentConfigTab platformId={platformId} agentId={agentIdNumber} />
          </TabsContent>
          <TabsContent value='knowledge'>
            <AgentKnowledgeTab
              platformId={platformId}
              agentId={agentIdNumber}
            />
          </TabsContent>
          <TabsContent value='skills'>
            <AgentSkillsTab platformId={platformId} agentId={agentIdNumber} />
          </TabsContent>
          <TabsContent value='tools'>
            <AgentToolsTab platformId={platformId} agentId={agentIdNumber} />
          </TabsContent>
          <TabsContent value='versions'>
            <AgentVersionsTab
              platformId={platformId}
              agentId={agentIdNumber}
            />
          </TabsContent>
          <TabsContent value='usage'>
            <AgentUsageTab platformId={platformId} agentId={agentIdNumber} />
          </TabsContent>
        </Tabs>
      </Main>
    </>
  )
}
```

- [ ] **Step 3: 生成路由树并验证**

Run: `cd apps/front && pnpm exec tsr generate`
Expected: `apps/front/src/routeTree.gen.ts` 出现 `bots/$agentId` 相关导入与注册。
若本机没有 `tsr` CLI：启动 `pnpm dev --host 127.0.0.1` 看到 `Local:` 输出后按 Ctrl+C 停止，再确认 `routeTree.gen.ts` 已更新。

- [ ] **Step 4: 静态检查**

Run: `cd apps/front && pnpm exec eslint src/routes/_authenticated/ai/bots.\$agentId.tsx src/features/agents/agent-detail-page.tsx && pnpm exec prettier --check src/routes/_authenticated/ai/bots.\$agentId.tsx src/features/agents/agent-detail-page.tsx`
Expected: 退出码 0（若组件尚未创建导致 import 报错，需先完成 Task 6-12 对应文件再复跑，或在 Task 5 创建占位组件）。

- [ ] **Step 5: 提交**

```bash
git add apps/front/src/routes/_authenticated/ai/bots.\$agentId.tsx apps/front/src/features/agents/agent-detail-page.tsx apps/front/src/routeTree.gen.ts
git commit -m "feat(agent): 新增智能体详情路由与标签骨架"
```

## Task 6: 概览标签页

**Files:**
- Create: `apps/front/src/features/agents/agent-overview-tab.tsx`

- [ ] **Step 1: 实现概览组件**

新建 `apps/front/src/features/agents/agent-overview-tab.tsx`：

```tsx
import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  AlertTriangle,
  Cable,
  Database,
  FileCode2,
  Link2,
  Wrench,
} from 'lucide-react'
import {
  Bar,
  BarChart,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from 'recharts'
import { getAgent, listAgentVersions } from '@/api/agent'
import { listAgentBuiltinTools } from '@/api/builtin-tools'
import { listAgentHostTools } from '@/api/host-tools'
import { listAgentKnowledgeBases } from '@/api/knowledge'
import { listMcpBindings } from '@/api/mcp-servers'
import { getModelUsageSummary } from '@/api/model-usage'
import { listAgentSkills } from '@/api/skills'
import { Badge } from '@/components/ui/badge'
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import {
  formatNumber,
  getUsageRanges,
  percentChange,
} from './agent-usage-utils'

export function AgentOverviewTab({
  platformId,
  agentId,
}: {
  platformId: number
  agentId: number
}) {
  const enabled = platformId != null
  const agentQuery = useQuery({
    queryKey: ['agent', platformId, agentId],
    queryFn: () => getAgent(platformId, agentId),
    enabled,
  })
  const versionsQuery = useQuery({
    queryKey: ['agent-versions', platformId, agentId],
    queryFn: () => listAgentVersions(platformId, agentId),
    enabled,
  })
  const knowledgeQuery = useQuery({
    queryKey: ['agent-knowledge-bindings', platformId, agentId],
    queryFn: () => listAgentKnowledgeBases(platformId, agentId),
    enabled,
  })
  const skillsQuery = useQuery({
    queryKey: ['agent-skill-bindings', platformId, agentId],
    queryFn: () => listAgentSkills(platformId, agentId),
    enabled,
  })
  const builtinQuery = useQuery({
    queryKey: ['agent-builtin-tools', platformId, agentId],
    queryFn: () => listAgentBuiltinTools(platformId, agentId),
    enabled,
  })
  const mcpQuery = useQuery({
    queryKey: ['agent-mcp-bindings', platformId, agentId],
    queryFn: () => listMcpBindings(platformId, agentId),
    enabled,
  })
  const hostQuery = useQuery({
    queryKey: ['agent-host-tools', platformId, agentId],
    queryFn: () => listAgentHostTools(platformId, agentId),
    enabled,
  })
  const ranges = useMemo(() => getUsageRanges(7), [])
  const currentUsageQuery = useQuery({
    queryKey: [
      'agent-usage-summary',
      platformId,
      agentId,
      ranges.start,
      ranges.end,
    ],
    queryFn: () =>
      getModelUsageSummary(platformId, {
        agent_id: agentId,
        start_date: ranges.start,
        end_date: ranges.end,
      }),
    enabled,
  })
  const previousUsageQuery = useQuery({
    queryKey: [
      'agent-usage-summary',
      platformId,
      agentId,
      ranges.previousStart,
      ranges.previousEnd,
    ],
    queryFn: () =>
      getModelUsageSummary(platformId, {
        agent_id: agentId,
        start_date: ranges.previousStart,
        end_date: ranges.previousEnd,
      }),
    enabled,
  })

  const agent = agentQuery.data
  const counts = {
    knowledge: knowledgeQuery.data?.length ?? 0,
    skills: skillsQuery.data?.length ?? 0,
    builtin:
      builtinQuery.data?.filter((tool) => tool.is_enabled).length ?? 0,
    mcp: mcpQuery.data?.length ?? 0,
    host:
      hostQuery.data?.filter((binding) => binding.is_enabled).length ?? 0,
  }
  const totals = currentUsageQuery.data?.totals
  const previous = previousUsageQuery.data?.totals
  const trend = (currentUsageQuery.data?.by_day ?? []).map((row) => ({
    day: row.day,
    total: row.total_tokens,
  }))
  const recentVersions = (versionsQuery.data ?? []).slice(0, 3)
  const hints: string[] = []
  if (agent && !agent.current_version) {
    hints.push('尚未发布版本，当前对话使用默认模型配置。')
  }
  const capabilityTotal =
    counts.knowledge + counts.skills + counts.builtin + counts.mcp + counts.host
  if (agent && capabilityTotal === 0) {
    hints.push('尚未关联任何知识库、技能或工具。')
  }

  const metrics = [
    {
      label: '调用次数',
      value: totals?.record_count ?? 0,
      previous: previous?.record_count ?? 0,
    },
    {
      label: '输入 token',
      value: totals?.prompt_tokens ?? 0,
      previous: previous?.prompt_tokens ?? 0,
    },
    {
      label: '输出 token',
      value: totals?.completion_tokens ?? 0,
      previous: previous?.completion_tokens ?? 0,
    },
    {
      label: '总 token',
      value: totals?.total_tokens ?? 0,
      previous: previous?.total_tokens ?? 0,
    },
  ]
  const capabilityItems = [
    { label: '知识库', value: counts.knowledge, Icon: Database },
    { label: '技能', value: counts.skills, Icon: FileCode2 },
    { label: '内置工具', value: counts.builtin, Icon: Wrench },
    { label: 'MCP 服务', value: counts.mcp, Icon: Cable },
    { label: '宿主工具', value: counts.host, Icon: Link2 },
  ] as const

  return (
    <div className='grid gap-4'>
      <div className='grid gap-4 md:grid-cols-2'>
        <Card className='rounded-md py-4'>
          <CardHeader className='px-4 pb-0'>
            <CardTitle className='text-xs font-medium tracking-wide text-muted-foreground'>
              运行状态
            </CardTitle>
          </CardHeader>
          <CardContent className='px-4 pt-3 text-sm'>
            {agent ? (
              <div className='space-y-1'>
                <div>
                  状态：{' '}
                  <Badge variant={agent.is_active ? 'default' : 'secondary'}>
                    {agent.is_active ? '启用' : '停用'}
                  </Badge>
                </div>
                <div>
                  当前版本：{' '}
                  {agent.current_version
                    ? `v${agent.current_version.version} · ${agent.current_version.model_name}`
                    : '未发布'}
                </div>
                <div>
                  最近发布：{' '}
                  {agent.current_version?.published_at
                    ? new Date(
                        agent.current_version.published_at
                      ).toLocaleString('zh-CN')
                    : '—'}
                </div>
              </div>
            ) : (
              <Skeleton className='h-16 w-full' />
            )}
          </CardContent>
        </Card>
        <Card className='rounded-md py-4'>
          <CardHeader className='px-4 pb-0'>
            <CardTitle className='text-xs font-medium tracking-wide text-muted-foreground'>
              能力摘要
            </CardTitle>
          </CardHeader>
          <CardContent className='px-4 pt-3'>
            <div className='grid grid-cols-2 gap-2 text-sm sm:grid-cols-5'>
              {capabilityItems.map(({ label, value, Icon }) => (
                <div key={label} className='flex items-center gap-2'>
                  <Icon className='size-4 text-muted-foreground' />
                  <span className='text-muted-foreground'>{label}</span>
                  <span className='font-semibold tabular-nums'>{value}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>

      <div className='grid gap-3 md:grid-cols-4'>
        {metrics.map((metric) => {
          const change =
            metric.previous > 0
              ? percentChange(metric.value, metric.previous)
              : null
          return (
            <Card key={metric.label} className='rounded-md py-4'>
              <CardHeader className='gap-2 px-4 pb-0'>
                <CardTitle className='text-xs font-medium tracking-wide text-muted-foreground'>
                  {metric.label}
                </CardTitle>
              </CardHeader>
              <CardContent className='px-4 pt-2'>
                <div className='text-2xl font-semibold tabular-nums'>
                  {currentUsageQuery.isLoading ? (
                    <Skeleton className='h-8 w-24' />
                  ) : (
                    formatNumber(metric.value)
                  )}
                </div>
                <div className='mt-1 text-xs text-muted-foreground'>
                  {change ? `较前 7 天 ${change}` : '暂无对比'}
                </div>
              </CardContent>
            </Card>
          )
        })}
      </div>

      <div className='grid gap-4 lg:grid-cols-3'>
        <Card className='rounded-md py-0 lg:col-span-2'>
          <CardHeader className='border-b px-4 py-4'>
            <CardTitle className='text-base'>近 7 天 Token 趋势</CardTitle>
          </CardHeader>
          <CardContent className='px-2 pt-4'>
            {trend.length ? (
              <ResponsiveContainer width='100%' height={220}>
                <BarChart data={trend}>
                  <XAxis
                    dataKey='day'
                    stroke='#888888'
                    fontSize={12}
                    tickLine={false}
                    axisLine={false}
                  />
                  <YAxis
                    stroke='#888888'
                    fontSize={12}
                    tickLine={false}
                    axisLine={false}
                    width={56}
                  />
                  <Bar
                    dataKey='total'
                    fill='currentColor'
                    radius={[4, 4, 0, 0]}
                    className='fill-primary'
                  />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className='flex h-44 items-center justify-center text-sm text-muted-foreground'>
                {currentUsageQuery.isLoading
                  ? '加载中...'
                  : '当前范围没有用量数据'}
              </div>
            )}
          </CardContent>
        </Card>
        <Card className='rounded-md py-0'>
          <CardHeader className='border-b px-4 py-4'>
            <CardTitle className='text-base'>最近版本</CardTitle>
          </CardHeader>
          <CardContent className='px-4 pt-3'>
            {recentVersions.length ? (
              <div className='space-y-2 text-sm'>
                {recentVersions.map((version) => (
                  <div
                    key={version.id}
                    className='flex items-center justify-between gap-2'
                  >
                    <span className='font-medium'>v{version.version}</span>
                    <span className='truncate text-muted-foreground'>
                      {version.model_name}
                    </span>
                    <span className='whitespace-nowrap text-xs text-muted-foreground'>
                      {version.published_at
                        ? new Date(version.published_at).toLocaleDateString(
                            'zh-CN'
                          )
                        : '未发布'}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className='flex h-24 items-center justify-center text-sm text-muted-foreground'>
                暂无版本
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {hints.length > 0 && (
        <div className='rounded-md border border-dashed px-4 py-3 text-sm text-muted-foreground'>
          <AlertTriangle className='me-2 inline size-4' />
          {hints.join(' ')}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: 静态检查**

Run: `cd apps/front && pnpm exec eslint src/features/agents/agent-overview-tab.tsx && pnpm exec prettier --check src/features/agents/agent-overview-tab.tsx`
Expected: 退出码 0。

- [ ] **Step 3: 提交**

```bash
git add apps/front/src/features/agents/agent-overview-tab.tsx
git commit -m "feat(agent): 详情页概览标签"
```

## Task 7: 配置标签页（含删除）

**Files:**
- Create: `apps/front/src/features/agents/agent-config-tab.tsx`

- [ ] **Step 1: 实现配置组件**

新建 `apps/front/src/features/agents/agent-config-tab.tsx`：

```tsx
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { AlertTriangle } from 'lucide-react'
import { toast } from 'sonner'
import { deleteAgent, getAgent, updateAgent } from '@/api/agent'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { agentSchema, type AgentForm } from './agent-form-schema'

export function AgentConfigTab({
  platformId,
  agentId,
}: {
  platformId: number
  agentId: number
}) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [deleting, setDeleting] = useState(false)
  const agentQuery = useQuery({
    queryKey: ['agent', platformId, agentId],
    queryFn: () => getAgent(platformId, agentId),
    enabled: platformId != null,
  })
  const agent = agentQuery.data
  const form = useForm<AgentForm>({
    resolver: zodResolver(agentSchema),
    values: {
      name: agent?.name ?? '',
      slug: agent?.slug ?? '',
      description: agent?.description ?? '',
      is_active: agent?.is_active ?? true,
    },
  })
  const saveMutation = useMutation({
    mutationFn: (values: AgentForm) =>
      updateAgent(platformId, agentId, {
        name: values.name,
        slug: values.slug,
        description: values.description,
        is_active: values.is_active,
      }),
    onSuccess: async () => {
      toast.success('配置已保存')
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ['agent', platformId, agentId],
        }),
        queryClient.invalidateQueries({ queryKey: ['agents', platformId] }),
      ])
    },
  })
  const deleteMutation = useMutation({
    mutationFn: () => deleteAgent(platformId, agentId),
    onSuccess: () => {
      toast.success('智能体已删除')
      void navigate({ to: '/ai/bots', search: { platform: platformId } })
    },
  })
  const version = agent?.current_version

  return (
    <div className='grid gap-4'>
      <Card className='rounded-md py-4'>
        <CardHeader className='px-4 pb-0'>
          <CardTitle className='text-base'>基本信息</CardTitle>
          <CardDescription>
            名称、描述与启用状态保存后立即生效。
          </CardDescription>
        </CardHeader>
        <CardContent className='px-4 pt-4'>
          <Form {...form}>
            <form
              id='agent-config-form'
              onSubmit={form.handleSubmit((values) =>
                saveMutation.mutate(values)
              )}
              className='grid gap-4'
            >
              <FormField
                control={form.control}
                name='name'
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>名称</FormLabel>
                    <FormControl>
                      <Input {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name='slug'
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Slug</FormLabel>
                    <FormControl>
                      <Input disabled {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name='description'
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>描述</FormLabel>
                    <FormControl>
                      <Textarea rows={3} {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name='is_active'
                render={({ field }) => (
                  <FormItem className='flex items-center justify-between rounded-md border p-3'>
                    <FormLabel>启用智能体</FormLabel>
                    <FormControl>
                      <Switch
                        checked={field.value}
                        onCheckedChange={field.onChange}
                      />
                    </FormControl>
                  </FormItem>
                )}
              />
              <div className='flex justify-end'>
                <Button
                  type='submit'
                  form='agent-config-form'
                  disabled={saveMutation.isPending}
                >
                  {saveMutation.isPending ? '保存中...' : '保存'}
                </Button>
              </div>
            </form>
          </Form>
        </CardContent>
      </Card>

      <Card className='rounded-md py-4'>
        <CardHeader className='px-4 pb-0'>
          <CardTitle className='text-base'>当前模型配置</CardTitle>
          <CardDescription>
            修改模型与提示词需创建并发布新版本。
          </CardDescription>
        </CardHeader>
        <CardContent className='px-4 pt-3 text-sm'>
          {agentQuery.isLoading ? (
            <Skeleton className='h-20 w-full' />
          ) : version ? (
            <div className='grid gap-1 sm:grid-cols-2'>
              <div>
                版本：<span className='font-medium'>v{version.version}</span>
              </div>
              <div>
                模型：<span className='font-medium'>{version.model_name}</span>
              </div>
              <div>模型地址：{version.model_base_url || '默认'}</div>
              <div>Temperature：{version.temperature}</div>
              <div>API Key：{version.has_api_key ? '已配置' : '未配置'}</div>
              <div>
                发布时间：
                {version.published_at
                  ? new Date(version.published_at).toLocaleString('zh-CN')
                  : '未发布'}
              </div>
            </div>
          ) : (
            <div className='text-muted-foreground'>尚未发布版本。</div>
          )}
        </CardContent>
      </Card>

      <Card className='rounded-md py-4'>
        <CardHeader className='px-4 pb-0'>
          <CardTitle className='text-base'>危险操作</CardTitle>
        </CardHeader>
        <CardContent className='px-4 pt-3'>
          <div className='flex items-center justify-between gap-3 rounded-md border border-destructive/30 px-4 py-3'>
            <div className='text-sm'>
              <div className='font-medium'>删除智能体</div>
              <div className='text-muted-foreground'>
                该智能体及其所有版本将永久删除，无法恢复。
              </div>
            </div>
            <Button
              variant='destructive'
              size='sm'
              onClick={() => setDeleting(true)}
            >
              <AlertTriangle className='me-2 size-4' />
              永久删除
            </Button>
          </div>
        </CardContent>
      </Card>

      <AlertDialog open={deleting} onOpenChange={setDeleting}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>硬删除智能体</AlertDialogTitle>
            <AlertDialogDescription>
              确认删除 {agent?.name ?? '该智能体'}
              ？该智能体及其所有版本将永久删除，无法恢复。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              className='bg-destructive text-destructive-foreground hover:bg-destructive/90'
              onClick={() => deleteMutation.mutate()}
            >
              永久删除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
```

- [ ] **Step 2: 静态检查**

Run: `cd apps/front && pnpm exec eslint src/features/agents/agent-config-tab.tsx && pnpm exec prettier --check src/features/agents/agent-config-tab.tsx`
Expected: 退出码 0。

- [ ] **Step 3: 提交**

```bash
git add apps/front/src/features/agents/agent-config-tab.tsx
git commit -m "feat(agent): 详情页配置标签"
```

## Task 8: 版本标签页与版本表单

**Files:**
- Create: `apps/front/src/features/agents/agent-version-form.tsx`
- Create: `apps/front/src/features/agents/agent-versions-tab.tsx`

- [ ] **Step 1: 迁移版本表单**

新建 `apps/front/src/features/agents/agent-version-form.tsx`（逻辑来自原列表页 `VersionFormDialog`）：

```tsx
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { z } from 'zod'
import { toast } from 'sonner'
import { createAgentVersion, type AgentVersionInput } from '@/api/agent'
import { Button } from '@/components/ui/button'
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'

export const versionSchema = z.object({
  system_prompt: z.string().min(1, '请输入系统提示词'),
  model_name: z.string().min(1, '请输入模型名称').max(120),
  model_base_url: z.string().url('请输入有效 URL').optional().or(z.literal('')),
  api_key: z.string().optional(),
  temperature: z.coerce.number().min(0).max(2),
})

type VersionFormInput = z.input<typeof versionSchema>
type VersionForm = z.output<typeof versionSchema>

export function AgentVersionForm({
  platformId,
  agentId,
  onCreated,
}: {
  platformId: number
  agentId: number
  onCreated: () => void
}) {
  const queryClient = useQueryClient()
  const form = useForm<VersionFormInput, unknown, VersionForm>({
    resolver: zodResolver(versionSchema),
    defaultValues: {
      system_prompt: '',
      model_name: 'gpt-4o-mini',
      model_base_url: '',
      api_key: '',
      temperature: 0.2,
    },
  })
  const mutation = useMutation({
    mutationFn: (values: VersionForm) => {
      const input: AgentVersionInput = {
        ...values,
        api_key: values.api_key || undefined,
        model_base_url: values.model_base_url || undefined,
        model_options: {},
      }
      return createAgentVersion(platformId, agentId, input)
    },
    onSuccess: async () => {
      toast.success('版本已创建')
      form.reset()
      await queryClient.invalidateQueries({
        queryKey: ['agent-versions', platformId, agentId],
      })
      onCreated()
    },
  })
  return (
    <Form {...form}>
      <form
        id='agent-version-form'
        onSubmit={form.handleSubmit((values) => mutation.mutate(values))}
        className='grid gap-4'
      >
        <FormField
          control={form.control}
          name='model_name'
          render={({ field }) => (
            <FormItem>
              <FormLabel>模型名称</FormLabel>
              <FormControl>
                <Input {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name='model_base_url'
          render={({ field }) => (
            <FormItem>
              <FormLabel>模型地址</FormLabel>
              <FormControl>
                <Input
                  placeholder='可选，例如 https://api.openai.com/v1'
                  {...field}
                />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name='api_key'
          render={({ field }) => (
            <FormItem>
              <FormLabel>API Key</FormLabel>
              <FormControl>
                <Input type='password' placeholder='仅本次提交' {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name='temperature'
          render={({ field }) => (
            <FormItem>
              <FormLabel>Temperature</FormLabel>
              <FormControl>
                <Input
                  type='number'
                  min='0'
                  max='2'
                  step='0.1'
                  {...field}
                  value={field.value as string | number | undefined}
                />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name='system_prompt'
          render={({ field }) => (
            <FormItem>
              <FormLabel>系统提示词</FormLabel>
              <FormControl>
                <Textarea rows={6} {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <div className='flex justify-end'>
          <Button
            type='submit'
            form='agent-version-form'
            disabled={mutation.isPending}
          >
            {mutation.isPending ? '保存中...' : '创建版本'}
          </Button>
        </div>
      </form>
    </Form>
  )
}
```

- [ ] **Step 2: 实现版本标签页**

新建 `apps/front/src/features/agents/agent-versions-tab.tsx`：

```tsx
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { History, Plus, Rocket, RotateCcw } from 'lucide-react'
import { toast } from 'sonner'
import {
  getAgent,
  listAgentVersions,
  publishAgentVersion,
  rollbackAgentVersion,
} from '@/api/agent'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { AgentVersionForm } from './agent-version-form'

export function AgentVersionsTab({
  platformId,
  agentId,
}: {
  platformId: number
  agentId: number
}) {
  const queryClient = useQueryClient()
  const [creating, setCreating] = useState(false)
  const agentQuery = useQuery({
    queryKey: ['agent', platformId, agentId],
    queryFn: () => getAgent(platformId, agentId),
    enabled: platformId != null,
  })
  const versionsQuery = useQuery({
    queryKey: ['agent-versions', platformId, agentId],
    queryFn: () => listAgentVersions(platformId, agentId),
    enabled: platformId != null,
  })
  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: ['agent-versions', platformId, agentId],
      }),
      queryClient.invalidateQueries({ queryKey: ['agent', platformId, agentId] }),
    ])
  }
  const publishMutation = useMutation({
    mutationFn: (versionId: number) =>
      publishAgentVersion(platformId, agentId, versionId),
    onSuccess: async () => {
      toast.success('版本已发布')
      await invalidate()
    },
  })
  const rollbackMutation = useMutation({
    mutationFn: (versionId: number) =>
      rollbackAgentVersion(platformId, agentId, versionId),
    onSuccess: async () => {
      toast.success('版本已回滚')
      await invalidate()
    },
  })
  const currentVersionId = agentQuery.data?.default_version_id
  const versions = versionsQuery.data ?? []

  return (
    <Card className='rounded-md py-4'>
      <CardHeader className='border-b px-4 py-4'>
        <div className='flex items-center justify-between gap-2'>
          <div>
            <CardTitle className='text-base'>版本列表</CardTitle>
            <div className='mt-1 text-xs text-muted-foreground'>
              发布版本后立即作用于下一轮对话。
            </div>
          </div>
          <Button size='sm' onClick={() => setCreating((value) => !value)}>
            <Plus className='me-2 size-4' />
            新建版本
          </Button>
        </div>
      </CardHeader>
      <CardContent className='px-0 pt-0'>
        {creating && (
          <div className='border-b px-4 py-4'>
            <AgentVersionForm
              platformId={platformId}
              agentId={agentId}
              onCreated={() => setCreating(false)}
            />
          </div>
        )}
        <div className='overflow-x-auto'>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>版本</TableHead>
                <TableHead>模型</TableHead>
                <TableHead>Temperature</TableHead>
                <TableHead>API Key</TableHead>
                <TableHead>创建 / 发布时间</TableHead>
                <TableHead className='w-44 text-end'>操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {versionsQuery.isLoading ? (
                Array.from({ length: 4 }).map((_, index) => (
                  <TableRow key={index}>
                    <TableCell colSpan={6}>
                      <Skeleton className='h-8 w-full' />
                    </TableCell>
                  </TableRow>
                ))
              ) : versions.length ? (
                versions.map((version) => {
                  const isCurrent = version.id === currentVersionId
                  return (
                    <TableRow key={version.id}>
                      <TableCell>
                        <div className='flex items-center gap-2'>
                          <History className='size-4 text-muted-foreground' />
                          <span className='font-medium'>v{version.version}</span>
                          {isCurrent && <Badge>使用中</Badge>}
                        </div>
                      </TableCell>
                      <TableCell className='font-mono text-xs'>
                        {version.model_name}
                      </TableCell>
                      <TableCell>{version.temperature}</TableCell>
                      <TableCell>
                        {version.has_api_key ? '已配置' : '未配置'}
                      </TableCell>
                      <TableCell className='text-xs text-muted-foreground'>
                        <div>
                          创建 {new Date(version.created_at).toLocaleString('zh-CN')}
                        </div>
                        {version.published_at && (
                          <div>
                            发布{' '}
                            {new Date(version.published_at).toLocaleString('zh-CN')}
                          </div>
                        )}
                      </TableCell>
                      <TableCell className='text-end'>
                        <div className='flex justify-end gap-1'>
                          <Button
                            size='sm'
                            variant='outline'
                            disabled={
                              isCurrent || publishMutation.isPending
                            }
                            onClick={() => publishMutation.mutate(version.id)}
                          >
                            <Rocket className='me-2 size-4' />
                            发布
                          </Button>
                          <Button
                            size='sm'
                            variant='outline'
                            disabled={
                              isCurrent || rollbackMutation.isPending
                            }
                            onClick={() => rollbackMutation.mutate(version.id)}
                          >
                            <RotateCcw className='me-2 size-4' />
                            回滚
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  )
                })
              ) : (
                <TableRow>
                  <TableCell colSpan={6} className='h-24 text-center'>
                    暂无版本
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  )
}
```

- [ ] **Step 3: 静态检查**

Run: `cd apps/front && pnpm exec eslint src/features/agents/agent-version-form.tsx src/features/agents/agent-versions-tab.tsx && pnpm exec prettier --check src/features/agents/agent-version-form.tsx src/features/agents/agent-versions-tab.tsx`
Expected: 退出码 0。

- [ ] **Step 4: 提交**

```bash
git add apps/front/src/features/agents/agent-version-form.tsx apps/front/src/features/agents/agent-versions-tab.tsx
git commit -m "feat(agent): 详情页版本标签"
```

## Task 9: 知识库关联标签页

**Files:**
- Create: `apps/front/src/features/agents/association-toolbar.tsx`
- Create: `apps/front/src/features/agents/agent-knowledge-tab.tsx`

- [ ] **Step 1: 实现共享工具条**

新建 `apps/front/src/features/agents/association-toolbar.tsx`：

```tsx
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

export function AssociationToolbar({
  keyword,
  onKeywordChange,
  status,
  onStatusChange,
}: {
  keyword: string
  onKeywordChange: (value: string) => void
  status: string
  onStatusChange: (value: string) => void
}) {
  return (
    <div className='flex flex-wrap items-center gap-2'>
      <Input
        value={keyword}
        onChange={(event) => onKeywordChange(event.target.value)}
        placeholder='搜索名称或标识'
        className='w-56'
      />
      <Select value={status} onValueChange={onStatusChange}>
        <SelectTrigger className='w-36'>
          <SelectValue placeholder='全部状态' />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value='all'>全部</SelectItem>
          <SelectItem value='bound'>已关联</SelectItem>
          <SelectItem value='unbound'>未关联</SelectItem>
        </SelectContent>
      </Select>
    </div>
  )
}
```

- [ ] **Step 2: 实现知识库关联组件**

新建 `apps/front/src/features/agents/agent-knowledge-tab.tsx`：

```tsx
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Database } from 'lucide-react'
import { toast } from 'sonner'
import {
  bindKnowledgeBaseAgent,
  listAgentKnowledgeBases,
  listKnowledgeBases,
  unbindKnowledgeBaseAgent,
} from '@/api/knowledge'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { AssociationToolbar } from './association-toolbar'

export function AgentKnowledgeTab({
  platformId,
  agentId,
}: {
  platformId: number
  agentId: number
}) {
  const queryClient = useQueryClient()
  const [keyword, setKeyword] = useState('')
  const [status, setStatus] = useState('all')
  const bindingsQuery = useQuery({
    queryKey: ['agent-knowledge-bindings', platformId, agentId],
    queryFn: () => listAgentKnowledgeBases(platformId, agentId),
    enabled: platformId != null,
  })
  const basesQuery = useQuery({
    queryKey: ['knowledge-bases', platformId],
    queryFn: () => listKnowledgeBases(platformId, { pageSize: 100 }),
    enabled: platformId != null,
  })
  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: ['agent-knowledge-bindings', platformId, agentId],
      }),
      queryClient.invalidateQueries({ queryKey: ['agent', platformId, agentId] }),
    ])
  }
  const bindMutation = useMutation({
    mutationFn: (baseId: number) =>
      bindKnowledgeBaseAgent(platformId, baseId, agentId),
    onSuccess: async () => {
      toast.success('知识库已关联')
      await invalidate()
    },
    onError: () => toast.error('关联失败，请重试'),
  })
  const unbindMutation = useMutation({
    mutationFn: (baseId: number) =>
      unbindKnowledgeBaseAgent(platformId, agentId, baseId),
    onSuccess: async () => {
      toast.success('知识库已解除关联')
      await invalidate()
    },
    onError: () => toast.error('解除关联失败，请重试'),
  })
  const rows = useMemo(() => {
    const items = (basesQuery.data?.items ?? []).map((base) => ({
      base,
      binding: bindingsQuery.data?.find(
        (item) => item.knowledge_base_id === base.id
      ),
    }))
    const filtered = keyword
      ? items.filter(
          ({ base }) =>
            base.name.includes(keyword) || base.slug.includes(keyword)
        )
      : items
    if (status === 'bound') return filtered.filter(({ binding }) => binding)
    if (status === 'unbound') return filtered.filter(({ binding }) => !binding)
    return filtered
  }, [basesQuery.data, bindingsQuery.data, keyword, status])
  const busy = bindMutation.isPending || unbindMutation.isPending

  return (
    <div className='space-y-3'>
      <div className='flex flex-wrap items-center justify-between gap-2'>
        <AssociationToolbar
          keyword={keyword}
          onKeywordChange={setKeyword}
          status={status}
          onStatusChange={setStatus}
        />
        <span className='text-sm text-muted-foreground'>
          已关联 {bindingsQuery.data?.length ?? 0} 个知识库 · 变更在下一轮对话生效
        </span>
      </div>
      {basesQuery.isLoading || bindingsQuery.isLoading ? (
        Array.from({ length: 3 }).map((_, index) => (
          <Skeleton key={index} className='h-20 w-full' />
        ))
      ) : rows.length ? (
        rows.map(({ base, binding }) => (
          <div
            key={base.id}
            className='flex items-start justify-between gap-4 rounded-md border p-4'
          >
            <div className='flex min-w-0 gap-3'>
              <div className='flex size-9 shrink-0 items-center justify-center rounded-md bg-muted'>
                <Database className='size-4 text-muted-foreground' />
              </div>
              <div className='min-w-0 space-y-1'>
                <div className='flex flex-wrap items-center gap-2'>
                  <span className='font-medium'>{base.name}</span>
                  <Badge variant='outline'>{base.slug}</Badge>
                </div>
                <p className='text-sm text-muted-foreground'>
                  {base.embedding_model} · 索引版本 {base.active_index_version}
                </p>
              </div>
            </div>
            <div className='flex shrink-0 items-center gap-3'>
              <span className='text-xs text-muted-foreground'>
                {binding ? `${binding.document_count} 文档` : '未关联'}
              </span>
              <Switch
                aria-label={`${binding ? '解除' : '关联'} ${base.name}`}
                checked={!!binding}
                disabled={busy}
                onCheckedChange={(checked) =>
                  checked
                    ? bindMutation.mutate(base.id)
                    : unbindMutation.mutate(base.id)
                }
              />
            </div>
          </div>
        ))
      ) : (
        <div className='flex min-h-32 items-center justify-center rounded-md border border-dashed text-sm text-muted-foreground'>
          暂无知识库，请先到知识库管理创建。
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 3: 静态检查**

Run: `cd apps/front && pnpm exec eslint src/features/agents/association-toolbar.tsx src/features/agents/agent-knowledge-tab.tsx && pnpm exec prettier --check src/features/agents/association-toolbar.tsx src/features/agents/agent-knowledge-tab.tsx`
Expected: 退出码 0。

- [ ] **Step 4: 提交**

```bash
git add apps/front/src/features/agents/association-toolbar.tsx apps/front/src/features/agents/agent-knowledge-tab.tsx
git commit -m "feat(agent): 详情页知识库关联标签"
```

## Task 10: 技能关联标签页

**Files:**
- Create: `apps/front/src/features/agents/agent-skills-tab.tsx`

- [ ] **Step 1: 实现技能关联组件**

新建 `apps/front/src/features/agents/agent-skills-tab.tsx`：

```tsx
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FileCode2 } from 'lucide-react'
import { toast } from 'sonner'
import {
  bindSkill,
  listAgentSkills,
  listSkills,
  unbindSkill,
} from '@/api/skills'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { AssociationToolbar } from './association-toolbar'

export function AgentSkillsTab({
  platformId,
  agentId,
}: {
  platformId: number
  agentId: number
}) {
  const queryClient = useQueryClient()
  const [keyword, setKeyword] = useState('')
  const [status, setStatus] = useState('all')
  const skillsQuery = useQuery({
    queryKey: ['skills', platformId],
    queryFn: () => listSkills(platformId, { pageSize: 100 }),
    enabled: platformId != null,
  })
  const bindingsQuery = useQuery({
    queryKey: ['agent-skill-bindings', platformId, agentId],
    queryFn: () => listAgentSkills(platformId, agentId),
    enabled: platformId != null,
  })
  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: ['agent-skill-bindings', platformId, agentId],
      }),
      queryClient.invalidateQueries({ queryKey: ['agent', platformId, agentId] }),
    ])
  }
  const bindMutation = useMutation({
    mutationFn: (skillId: number) =>
      bindSkill(platformId, agentId, skillId),
    onSuccess: async () => {
      toast.success('技能已关联')
      await invalidate()
    },
    onError: () => toast.error('关联失败，请重试'),
  })
  const unbindMutation = useMutation({
    mutationFn: (skillId: number) =>
      unbindSkill(platformId, agentId, skillId),
    onSuccess: async () => {
      toast.success('技能已解除关联')
      await invalidate()
    },
    onError: () => toast.error('解除关联失败，请重试'),
  })
  const rows = useMemo(() => {
    const items = (skillsQuery.data?.items ?? []).map((skill) => ({
      skill,
      binding: bindingsQuery.data?.find((item) => item.skill_id === skill.id),
    }))
    const filtered = keyword
      ? items.filter(
          ({ skill }) =>
            skill.name.includes(keyword) || skill.slug.includes(keyword)
        )
      : items
    if (status === 'bound') return filtered.filter(({ binding }) => binding)
    if (status === 'unbound') return filtered.filter(({ binding }) => !binding)
    return filtered
  }, [skillsQuery.data, bindingsQuery.data, keyword, status])
  const busy = bindMutation.isPending || unbindMutation.isPending

  return (
    <div className='space-y-3'>
      <div className='flex flex-wrap items-center justify-between gap-2'>
        <AssociationToolbar
          keyword={keyword}
          onKeywordChange={setKeyword}
          status={status}
          onStatusChange={setStatus}
        />
        <span className='text-sm text-muted-foreground'>
          已关联 {bindingsQuery.data?.length ?? 0} 个技能 · 变更在下一轮对话生效
        </span>
      </div>
      {skillsQuery.isLoading || bindingsQuery.isLoading ? (
        Array.from({ length: 3 }).map((_, index) => (
          <Skeleton key={index} className='h-20 w-full' />
        ))
      ) : rows.length ? (
        rows.map(({ skill, binding }) => (
          <div
            key={skill.id}
            className='flex items-start justify-between gap-4 rounded-md border p-4'
          >
            <div className='flex min-w-0 gap-3'>
              <div className='flex size-9 shrink-0 items-center justify-center rounded-md bg-muted'>
                <FileCode2 className='size-4 text-muted-foreground' />
              </div>
              <div className='min-w-0 space-y-1'>
                <div className='flex flex-wrap items-center gap-2'>
                  <span className='font-medium'>{skill.name}</span>
                  <Badge variant={skill.is_active ? 'outline' : 'secondary'}>
                    {skill.is_active ? '启用' : '停用'}
                  </Badge>
                  <Badge variant='outline'>
                    {skill.package_id ? '技能包' : '自定义'}
                  </Badge>
                </div>
                <p className='text-sm text-muted-foreground'>
                  {skill.description || skill.slug}
                </p>
              </div>
            </div>
            <Switch
              aria-label={`${binding ? '解除' : '关联'} ${skill.name}`}
              checked={!!binding}
              disabled={busy}
              onCheckedChange={(checked) =>
                checked
                  ? bindMutation.mutate(skill.id)
                  : unbindMutation.mutate(skill.id)
              }
            />
          </div>
        ))
      ) : (
        <div className='flex min-h-32 items-center justify-center rounded-md border border-dashed text-sm text-muted-foreground'>
          暂无技能，请先到技能管理创建。
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: 静态检查**

Run: `cd apps/front && pnpm exec eslint src/features/agents/agent-skills-tab.tsx && pnpm exec prettier --check src/features/agents/agent-skills-tab.tsx`
Expected: 退出码 0。

- [ ] **Step 3: 提交**

```bash
git add apps/front/src/features/agents/agent-skills-tab.tsx
git commit -m "feat(agent): 详情页技能关联标签"
```

## Task 11: 工具标签页（内置 / MCP / 宿主）

**Files:**
- Create: `apps/front/src/features/agents/agent-tools-tab.tsx`
- Create: `apps/front/src/features/agents/builtin-tools-section.tsx`
- Create: `apps/front/src/features/agents/mcp-tools-section.tsx`
- Create: `apps/front/src/features/agents/host-tools-section.tsx`
- Delete: `apps/front/src/features/agents/builtin-tools-dialog.tsx`

- [ ] **Step 1: 实现内置工具 Section（逻辑迁移自原弹窗）**

新建 `apps/front/src/features/agents/builtin-tools-section.tsx`：

```tsx
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Wrench } from 'lucide-react'
import { toast } from 'sonner'
import {
  listAgentBuiltinTools,
  updateAgentBuiltinTool,
  type AgentBuiltinTool,
} from '@/api/builtin-tools'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'

export function BuiltinToolsSection({
  platformId,
  agentId,
}: {
  platformId: number
  agentId: number
}) {
  const queryClient = useQueryClient()
  const queryKey = ['agent-builtin-tools', platformId, agentId] as const
  const toolsQuery = useQuery({
    queryKey,
    queryFn: () => listAgentBuiltinTools(platformId, agentId),
    enabled: platformId != null,
  })
  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey }),
      queryClient.invalidateQueries({ queryKey: ['agent', platformId, agentId] }),
    ])
  }
  const updateMutation = useMutation({
    mutationFn: (tool: AgentBuiltinTool) =>
      updateAgentBuiltinTool(
        platformId,
        agentId,
        tool.name,
        !tool.is_enabled
      ),
    onSuccess: async () => {
      toast.success('内置工具状态已更新')
      await invalidate()
    },
    onError: () => toast.error('工具状态更新失败'),
  })

  return (
    <div className='space-y-3'>
      <p className='text-sm text-muted-foreground'>
        启用后，智能体可在下一轮对话中调用对应工具。
      </p>
      {toolsQuery.isLoading ? (
        Array.from({ length: 3 }).map((_, index) => (
          <Skeleton key={index} className='h-20 w-full' />
        ))
      ) : toolsQuery.data?.length ? (
        toolsQuery.data.map((tool) => (
          <div
            key={tool.name}
            className='flex items-start justify-between gap-4 rounded-md border p-4'
          >
            <div className='flex min-w-0 gap-3'>
              <div className='flex size-9 shrink-0 items-center justify-center rounded-md bg-muted'>
                <Wrench className='size-4 text-muted-foreground' />
              </div>
              <div className='min-w-0 space-y-1'>
                <div className='flex flex-wrap items-center gap-2'>
                  <span className='font-medium'>{tool.name}</span>
                  <Badge variant='outline'>无副作用</Badge>
                </div>
                <p className='text-sm text-muted-foreground'>
                  {tool.description}
                </p>
              </div>
            </div>
            <Switch
              aria-label={`${tool.is_enabled ? '停用' : '启用'} ${tool.name}`}
              checked={tool.is_enabled}
              disabled={updateMutation.isPending}
              onCheckedChange={() => updateMutation.mutate(tool)}
            />
          </div>
        ))
      ) : (
        <div className='flex min-h-32 items-center justify-center rounded-md border border-dashed text-sm text-muted-foreground'>
          暂无可用的内置工具
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: 实现 MCP 服务 Section**

新建 `apps/front/src/features/agents/mcp-tools-section.tsx`：

```tsx
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Cable, ChevronDown } from 'lucide-react'
import { toast } from 'sonner'
import {
  bindMcpServer,
  listMcpBindings,
  listMcpServerTools,
  listMcpServers,
  unbindMcpServer,
} from '@/api/mcp-servers'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

export function McpToolsSection({
  platformId,
  agentId,
}: {
  platformId: number
  agentId: number
}) {
  const queryClient = useQueryClient()
  const serversQuery = useQuery({
    queryKey: ['mcp-servers', platformId],
    queryFn: () => listMcpServers(platformId, { pageSize: 100 }),
    enabled: platformId != null,
  })
  const bindingsQuery = useQuery({
    queryKey: ['agent-mcp-bindings', platformId, agentId],
    queryFn: () => listMcpBindings(platformId, agentId),
    enabled: platformId != null,
  })
  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: ['agent-mcp-bindings', platformId, agentId],
      }),
      queryClient.invalidateQueries({ queryKey: ['agent', platformId, agentId] }),
    ])
  }
  const bindMutation = useMutation({
    mutationFn: (serverId: number) =>
      bindMcpServer(platformId, agentId, serverId),
    onSuccess: async () => {
      toast.success('MCP 服务已关联')
      await invalidate()
    },
    onError: () => toast.error('关联失败，请重试'),
  })
  const unbindMutation = useMutation({
    mutationFn: (serverId: number) =>
      unbindMcpServer(platformId, agentId, serverId),
    onSuccess: async () => {
      toast.success('MCP 服务已解除关联')
      await invalidate()
    },
    onError: () => toast.error('解除关联失败，请重试'),
  })
  const rows = (serversQuery.data?.items ?? []).map((server) => ({
    server,
    binding: bindingsQuery.data?.find((item) => item.server_id === server.id),
  }))
  const busy = bindMutation.isPending || unbindMutation.isPending

  return (
    <div className='space-y-3'>
      <p className='text-sm text-muted-foreground'>
        按 MCP 服务关联；工具可用性与副作用策略在 MCP 管理页维护。
      </p>
      {serversQuery.isLoading || bindingsQuery.isLoading ? (
        Array.from({ length: 3 }).map((_, index) => (
          <Skeleton key={index} className='h-20 w-full' />
        ))
      ) : rows.length ? (
        rows.map(({ server, binding }) => (
          <McpServerRow
            key={server.id}
            platformId={platformId}
            server={server}
            bound={!!binding}
            busy={busy}
            onToggle={(checked) =>
              checked
                ? bindMutation.mutate(server.id)
                : unbindMutation.mutate(server.id)
            }
          />
        ))
      ) : (
        <div className='flex min-h-32 items-center justify-center rounded-md border border-dashed text-sm text-muted-foreground'>
          暂无 MCP 服务，请先到 MCP 管理创建。
        </div>
      )}
    </div>
  )
}

function McpServerRow({
  platformId,
  server,
  bound,
  busy,
  onToggle,
}: {
  platformId: number
  server: { id: number; name: string; slug: string; is_active: boolean }
  bound: boolean
  busy: boolean
  onToggle: (checked: boolean) => void
}) {
  return (
    <Collapsible>
      <div className='flex items-center justify-between gap-4 rounded-md border p-4'>
        <div className='flex min-w-0 items-center gap-3'>
          <div className='flex size-9 shrink-0 items-center justify-center rounded-md bg-muted'>
            <Cable className='size-4 text-muted-foreground' />
          </div>
          <div className='min-w-0'>
            <div className='flex flex-wrap items-center gap-2'>
              <span className='font-medium'>{server.name}</span>
              <Badge variant={server.is_active ? 'outline' : 'secondary'}>
                {server.is_active ? '启用' : '停用'}
              </Badge>
            </div>
            <div className='truncate text-xs text-muted-foreground'>
              {server.slug}
            </div>
          </div>
        </div>
        <div className='flex shrink-0 items-center gap-2'>
          <CollapsibleTrigger asChild>
            <Button size='sm' variant='ghost'>
              <ChevronDown className='size-4' />
              工具
            </Button>
          </CollapsibleTrigger>
          <Switch
            aria-label={`${bound ? '解除' : '关联'} ${server.name}`}
            checked={bound}
            disabled={busy}
            onCheckedChange={onToggle}
          />
        </div>
      </div>
      <CollapsibleContent>
        <div className='border-x border-b rounded-b-md p-3'>
          <McpServerToolsList platformId={platformId} serverId={server.id} />
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}

function McpServerToolsList({
  platformId,
  serverId,
}: {
  platformId: number
  serverId: number
}) {
  const toolsQuery = useQuery({
    queryKey: ['mcp-server-tools', platformId, serverId],
    queryFn: () => listMcpServerTools(platformId, serverId),
    enabled: platformId != null,
  })
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>工具</TableHead>
          <TableHead>描述</TableHead>
          <TableHead>允许调用</TableHead>
          <TableHead>副作用</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {toolsQuery.isLoading ? (
          <TableRow>
            <TableCell colSpan={4}>
              <Skeleton className='h-8 w-full' />
            </TableCell>
          </TableRow>
        ) : toolsQuery.data?.length ? (
          toolsQuery.data.map((tool) => (
            <TableRow key={tool.id}>
              <TableCell className='font-mono text-xs font-medium'>
                {tool.name}
              </TableCell>
              <TableCell className='max-w-md truncate text-sm text-muted-foreground'>
                {tool.description || '-'}
              </TableCell>
              <TableCell>
                <Badge variant={tool.is_allowed ? 'default' : 'secondary'}>
                  {tool.is_allowed ? '允许' : '禁用'}
                </Badge>
              </TableCell>
              <TableCell className='text-xs'>{tool.side_effect}</TableCell>
            </TableRow>
          ))
        ) : (
          <TableRow>
            <TableCell colSpan={4} className='h-16 text-center text-sm text-muted-foreground'>
              该服务暂无可发现工具
            </TableCell>
          </TableRow>
        )}
      </TableBody>
    </Table>
  )
}
```

- [ ] **Step 3: 实现宿主工具 Section**

新建 `apps/front/src/features/agents/host-tools-section.tsx`：

```tsx
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link2 } from 'lucide-react'
import { toast } from 'sonner'
import {
  bindAgentHostTool,
  listAgentHostTools,
  listHostTools,
  unbindAgentHostTool,
} from '@/api/host-tools'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'

export function HostToolsSection({
  platformId,
  agentId,
}: {
  platformId: number
  agentId: number
}) {
  const queryClient = useQueryClient()
  const policiesQuery = useQuery({
    queryKey: ['host-tools', platformId],
    queryFn: () => listHostTools(platformId),
    enabled: platformId != null,
  })
  const bindingsQuery = useQuery({
    queryKey: ['agent-host-tools', platformId, agentId],
    queryFn: () => listAgentHostTools(platformId, agentId),
    enabled: platformId != null,
  })
  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: ['agent-host-tools', platformId, agentId],
      }),
      queryClient.invalidateQueries({ queryKey: ['agent', platformId, agentId] }),
    ])
  }
  const bindMutation = useMutation({
    mutationFn: (toolId: number) =>
      bindAgentHostTool(platformId, agentId, toolId),
    onSuccess: async () => {
      toast.success('宿主工具已关联')
      await invalidate()
    },
    onError: () => toast.error('关联失败，请重试'),
  })
  const unbindMutation = useMutation({
    mutationFn: (toolId: number) =>
      unbindAgentHostTool(platformId, agentId, toolId),
    onSuccess: async () => {
      toast.success('宿主工具已解除关联')
      await invalidate()
    },
    onError: () => toast.error('解除关联失败，请重试'),
  })
  const rows = (policiesQuery.data ?? []).map((policy) => ({
    policy,
    binding: bindingsQuery.data?.find((item) => item.tool_id === policy.id),
  }))
  const busy = bindMutation.isPending || unbindMutation.isPending

  return (
    <div className='space-y-3'>
      <p className='text-sm text-muted-foreground'>
        按工具关联；全局停用的工具不可启用。
      </p>
      {policiesQuery.isLoading || bindingsQuery.isLoading ? (
        Array.from({ length: 3 }).map((_, index) => (
          <Skeleton key={index} className='h-20 w-full' />
        ))
      ) : rows.length ? (
        rows.map(({ policy, binding }) => (
          <div
            key={policy.id}
            className='flex items-start justify-between gap-4 rounded-md border p-4'
          >
            <div className='flex min-w-0 gap-3'>
              <div className='flex size-9 shrink-0 items-center justify-center rounded-md bg-muted'>
                <Link2 className='size-4 text-muted-foreground' />
              </div>
              <div className='min-w-0 space-y-1'>
                <div className='flex flex-wrap items-center gap-2'>
                  <span className='font-medium'>{policy.name}</span>
                  <Badge variant='outline'>{policy.side_effect}</Badge>
                  {!policy.is_enabled && (
                    <Badge variant='secondary'>全局已停用</Badge>
                  )}
                </div>
                <p className='text-sm text-muted-foreground'>
                  {policy.description}
                </p>
              </div>
            </div>
            <Switch
              aria-label={`${binding?.is_enabled ? '解除' : '关联'} ${policy.name}`}
              checked={binding?.is_enabled ?? false}
              disabled={!policy.is_enabled || busy}
              onCheckedChange={(checked) =>
                checked
                  ? bindMutation.mutate(policy.id)
                  : unbindMutation.mutate(policy.id)
              }
            />
          </div>
        ))
      ) : (
        <div className='flex min-h-32 items-center justify-center rounded-md border border-dashed text-sm text-muted-foreground'>
          暂无宿主工具策略
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 4: 实现工具容器并删除旧弹窗**

新建 `apps/front/src/features/agents/agent-tools-tab.tsx`：

```tsx
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '@/components/ui/tabs'
import { BuiltinToolsSection } from './builtin-tools-section'
import { HostToolsSection } from './host-tools-section'
import { McpToolsSection } from './mcp-tools-section'

export function AgentToolsTab({
  platformId,
  agentId,
}: {
  platformId: number
  agentId: number
}) {
  return (
    <Tabs defaultValue='builtin' className='gap-0'>
      <TabsList className='w-fit'>
        <TabsTrigger value='builtin'>内置工具</TabsTrigger>
        <TabsTrigger value='mcp'>MCP 工具</TabsTrigger>
        <TabsTrigger value='host'>宿主工具</TabsTrigger>
      </TabsList>
      <TabsContent value='builtin'>
        <BuiltinToolsSection platformId={platformId} agentId={agentId} />
      </TabsContent>
      <TabsContent value='mcp'>
        <McpToolsSection platformId={platformId} agentId={agentId} />
      </TabsContent>
      <TabsContent value='host'>
        <HostToolsSection platformId={platformId} agentId={agentId} />
      </TabsContent>
    </Tabs>
  )
}
```

删除旧弹窗：`git rm apps/front/src/features/agents/builtin-tools-dialog.tsx`（其逻辑已迁移到 `builtin-tools-section.tsx`）。

- [ ] **Step 5: 静态检查**

Run: `cd apps/front && pnpm exec eslint src/features/agents/agent-tools-tab.tsx src/features/agents/builtin-tools-section.tsx src/features/agents/mcp-tools-section.tsx src/features/agents/host-tools-section.tsx && pnpm exec prettier --check src/features/agents/agent-tools-tab.tsx src/features/agents/builtin-tools-section.tsx src/features/agents/mcp-tools-section.tsx src/features/agents/host-tools-section.tsx`
Expected: 退出码 0。

- [ ] **Step 6: 提交**

```bash
git add apps/front/src/features/agents/agent-tools-tab.tsx apps/front/src/features/agents/builtin-tools-section.tsx apps/front/src/features/agents/mcp-tools-section.tsx apps/front/src/features/agents/host-tools-section.tsx
git rm apps/front/src/features/agents/builtin-tools-dialog.tsx
git commit -m "feat(agent): 详情页工具标签"
```

## Task 12: 用量标签页与模型用量页筛选

**Files:**
- Create: `apps/front/src/features/agents/agent-usage-tab.tsx`
- Modify: `apps/front/src/routes/_authenticated/ai/model-usage.tsx`
- Modify: `apps/front/src/features/model-usage/index.tsx`

- [ ] **Step 1: 实现用量组件**

新建 `apps/front/src/features/agents/agent-usage-tab.tsx`：

```tsx
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { ExternalLink } from 'lucide-react'
import {
  Bar,
  BarChart,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from 'recharts'
import { getModelUsageSummary, listModelUsage } from '@/api/model-usage'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  formatNumber,
  getUsageRanges,
  percentChange,
} from './agent-usage-utils'

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

export function AgentUsageTab({
  platformId,
  agentId,
}: {
  platformId: number
  agentId: number
}) {
  const [rangeDays, setRangeDays] = useState<7 | 30>(7)
  const ranges = useMemo(() => getUsageRanges(rangeDays), [rangeDays])
  const enabled = platformId != null
  const currentQuery = useQuery({
    queryKey: [
      'agent-usage-summary',
      platformId,
      agentId,
      ranges.start,
      ranges.end,
    ],
    queryFn: () =>
      getModelUsageSummary(platformId, {
        agent_id: agentId,
        start_date: ranges.start,
        end_date: ranges.end,
      }),
    enabled,
  })
  const previousQuery = useQuery({
    queryKey: [
      'agent-usage-summary',
      platformId,
      agentId,
      ranges.previousStart,
      ranges.previousEnd,
    ],
    queryFn: () =>
      getModelUsageSummary(platformId, {
        agent_id: agentId,
        start_date: ranges.previousStart,
        end_date: ranges.previousEnd,
      }),
    enabled,
  })
  const recordsQuery = useQuery({
    queryKey: [
      'agent-usage-records',
      platformId,
      agentId,
      ranges.start,
      ranges.end,
    ],
    queryFn: () =>
      listModelUsage(platformId, {
        agent_id: agentId,
        start_date: ranges.start,
        end_date: ranges.end,
        page: 1,
        page_size: 10,
      }),
    enabled,
  })
  const totals = currentQuery.data?.totals
  const previous = previousQuery.data?.totals
  const trend = (currentQuery.data?.by_day ?? []).map((row) => ({
    day: row.day,
    total: row.total_tokens,
  }))
  const metrics = [
    {
      label: '调用次数',
      value: totals?.record_count ?? 0,
      previous: previous?.record_count ?? 0,
    },
    {
      label: '输入 token',
      value: totals?.prompt_tokens ?? 0,
      previous: previous?.prompt_tokens ?? 0,
    },
    {
      label: '输出 token',
      value: totals?.completion_tokens ?? 0,
      previous: previous?.completion_tokens ?? 0,
    },
    {
      label: '总 token',
      value: totals?.total_tokens ?? 0,
      previous: previous?.total_tokens ?? 0,
    },
  ]

  return (
    <div className='grid gap-4'>
      <div className='flex flex-wrap items-center justify-between gap-2'>
        <div className='flex gap-1'>
          {([7, 30] as const).map((days) => (
            <Button
              key={days}
              size='sm'
              variant={rangeDays === days ? 'default' : 'outline'}
              onClick={() => setRangeDays(days)}
            >
              近 {days} 天
            </Button>
          ))}
        </div>
        <Button asChild variant='outline' size='sm'>
          <Link
            to='/ai/model-usage'
            search={{ platform: platformId, agent: agentId }}
          >
            查看完整用量
            <ExternalLink className='ms-2 size-4' />
          </Link>
        </Button>
      </div>

      <div className='grid gap-3 md:grid-cols-4'>
        {metrics.map((metric) => {
          const change =
            metric.previous > 0
              ? percentChange(metric.value, metric.previous)
              : null
          return (
            <Card key={metric.label} className='rounded-md py-4'>
              <CardHeader className='gap-2 px-4 pb-0'>
                <CardTitle className='text-xs font-medium tracking-wide text-muted-foreground'>
                  {metric.label}
                </CardTitle>
              </CardHeader>
              <CardContent className='px-4 pt-2'>
                <div className='text-2xl font-semibold tabular-nums'>
                  {currentQuery.isLoading ? (
                    <Skeleton className='h-8 w-24' />
                  ) : (
                    formatNumber(metric.value)
                  )}
                </div>
                <div className='mt-1 text-xs text-muted-foreground'>
                  {change ? `较上一周期 ${change}` : '暂无对比'}
                </div>
              </CardContent>
            </Card>
          )
        })}
      </div>

      <Card className='rounded-md py-0'>
        <CardHeader className='border-b px-4 py-4'>
          <CardTitle className='text-base'>Token 趋势</CardTitle>
        </CardHeader>
        <CardContent className='px-2 pt-4'>
          {trend.length ? (
            <ResponsiveContainer width='100%' height={220}>
              <BarChart data={trend}>
                <XAxis
                  dataKey='day'
                  stroke='#888888'
                  fontSize={12}
                  tickLine={false}
                  axisLine={false}
                />
                <YAxis
                  stroke='#888888'
                  fontSize={12}
                  tickLine={false}
                  axisLine={false}
                  width={56}
                />
                <Bar
                  dataKey='total'
                  fill='currentColor'
                  radius={[4, 4, 0, 0]}
                  className='fill-primary'
                />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className='flex h-44 items-center justify-center text-sm text-muted-foreground'>
              {currentQuery.isLoading ? '加载中...' : '当前范围没有用量数据'}
            </div>
          )}
        </CardContent>
      </Card>

      <Card className='rounded-md py-0'>
        <CardHeader className='border-b px-4 py-4'>
          <CardTitle className='text-base'>最近调用</CardTitle>
        </CardHeader>
        <CardContent className='px-0'>
          <div className='overflow-x-auto'>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>时间</TableHead>
                  <TableHead>会话</TableHead>
                  <TableHead>请求 ID</TableHead>
                  <TableHead>模型</TableHead>
                  <TableHead className='text-end'>输入</TableHead>
                  <TableHead className='text-end'>输出</TableHead>
                  <TableHead className='text-end'>总 token</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {recordsQuery.isLoading ? (
                  Array.from({ length: 5 }).map((_, index) => (
                    <TableRow key={index}>
                      <TableCell colSpan={7}>
                        <Skeleton className='h-8 w-full' />
                      </TableCell>
                    </TableRow>
                  ))
                ) : recordsQuery.data?.items.length ? (
                  recordsQuery.data.items.map((record) => (
                    <TableRow key={record.id}>
                      <TableCell className='text-xs whitespace-nowrap text-muted-foreground'>
                        {formatDateTime(record.created_at)}
                      </TableCell>
                      <TableCell>会话 #{record.conversation_id}</TableCell>
                      <TableCell className='max-w-44 truncate font-mono text-xs text-muted-foreground'>
                        {record.request_id || '-'}
                      </TableCell>
                      <TableCell className='font-mono text-xs'>
                        {record.model_name || '-'}
                      </TableCell>
                      <TableCell className='text-end tabular-nums'>
                        {formatNumber(record.prompt_tokens)}
                      </TableCell>
                      <TableCell className='text-end tabular-nums'>
                        {formatNumber(record.completion_tokens)}
                      </TableCell>
                      <TableCell className='text-end font-semibold tabular-nums'>
                        {formatNumber(record.total_tokens)}
                      </TableCell>
                    </TableRow>
                  ))
                ) : (
                  <TableRow>
                    <TableCell colSpan={7}>
                      <div className='flex h-28 items-center justify-center text-sm text-muted-foreground'>
                        当前范围没有用量明细
                      </div>
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
```

- [ ] **Step 2: 模型用量路由支持筛选参数**

`apps/front/src/routes/_authenticated/ai/model-usage.tsx` 整体替换为：

```tsx
import { createFileRoute } from '@tanstack/react-router'
import { z } from 'zod'
import { ModelUsagePage } from '@/features/model-usage'

const modelUsageSearch = z.object({
  platform: z.coerce.number().optional(),
  agent: z.coerce.number().optional(),
})

export const Route = createFileRoute('/_authenticated/ai/model-usage')({
  validateSearch: modelUsageSearch,
  component: () => {
    const search = Route.useSearch()
    return (
      <ModelUsagePage
        initialPlatformId={search.platform}
        initialAgentId={search.agent == null ? undefined : String(search.agent)}
      />
    )
  },
})
```

- [ ] **Step 3: 模型用量页面接受初始筛选**

`apps/front/src/features/model-usage/index.tsx` 修改两处：

1. 函数签名改为：

```tsx
export function ModelUsagePage({
  initialPlatformId,
  initialAgentId,
}: {
  initialPlatformId?: number
  initialAgentId?: string
} = {}) {
```

2. 平台与智能体初始状态改为：

```tsx
const [platformId, setPlatformId] = useState<number | undefined>(
  initialPlatformId
)
const [agentId, setAgentId] = useState<string>(initialAgentId ?? 'all')
```

其余逻辑保持不变。

- [ ] **Step 4: 静态检查**

Run: `cd apps/front && pnpm exec eslint src/features/agents/agent-usage-tab.tsx src/routes/_authenticated/ai/model-usage.tsx src/features/model-usage/index.tsx && pnpm exec prettier --check src/features/agents/agent-usage-tab.tsx src/routes/_authenticated/ai/model-usage.tsx src/features/model-usage/index.tsx`
Expected: 退出码 0。

- [ ] **Step 5: 提交**

```bash
git add apps/front/src/features/agents/agent-usage-tab.tsx apps/front/src/routes/_authenticated/ai/model-usage.tsx apps/front/src/features/model-usage/index.tsx apps/front/src/routeTree.gen.ts
git commit -m "feat(agent): 详情页用量标签与用量页筛选联动"
```

## Task 13: 全量验证与 Harness 收尾

**Files:**
- Modify: `docs/harness/requests/2026-08-11-agent-detail-workbench/verify.md`
- Modify: `docs/harness/requests/2026-08-11-agent-detail-workbench/acceptance.md`
- Modify: `docs/harness/requests/2026-08-11-agent-detail-workbench/meta.json`
- Modify: `docs/harness/requests/2026-08-11-agent-detail-workbench/spec.md`

- [ ] **Step 1: 后端全量定向验证**

Run:

```bash
cd apps/backend && poetry run ruff check app/modules/agent app/modules/knowledge app/__init__.py tests/agent tests/knowledge
cd apps/backend && poetry run pytest tests/agent tests/knowledge tests/model_usage -q
```

Expected: ruff 退出码 0；pytest 全部通过。

- [ ] **Step 2: 前端静态验证与路由树**

Run:

```bash
cd apps/front && pnpm exec tsr generate
cd apps/front && pnpm exec eslint src/api/agent.ts src/api/knowledge.ts src/features/agents src/features/model-usage/index.tsx src/routes/_authenticated/ai/bots.tsx src/routes/_authenticated/ai/model-usage.tsx
cd apps/front && pnpm exec prettier --check src/api/agent.ts src/api/knowledge.ts src/features/agents src/features/model-usage/index.tsx src/routes/_authenticated/ai/bots.tsx src/routes/_authenticated/ai/model-usage.tsx
```

Expected: 退出码 0；`routeTree.gen.ts` 包含 `bots/$agentId`。
若 `tsr` 不存在，启动一次 `pnpm dev --host 127.0.0.1` 后停止，再确认路由树已更新。
说明：仓库既有 `react-hook-form` 类型导出缺失会导致 `pnpm build` 全量构建失败，此失败属于既有基线，不视为本次实现失败；需在 `verify.md` 如实记录。

- [ ] **Step 3: 工具函数测试**

Run:

```bash
cd apps/front && pnpm exec tsc --target es2022 --module commonjs --moduleResolution node --outDir /tmp/agent-usage-utils src/features/agents/agent-usage-utils.ts src/features/agents/agent-usage-utils.test.ts && node /tmp/agent-usage-utils/features/agents/agent-usage-utils.test.js
```

Expected: 无输出且退出码 0。

- [ ] **Step 4: 浏览器联调（环境允许时）**

启动后端与前端后逐项核对：

1. 列表页搜索、状态筛选、进入详情。
2. 详情页七个标签可通过 URL 直达。
3. 知识库、技能、内置工具、MCP 服务、宿主工具均可关联/解除，开关失败时恢复。
4. 概览计数与关联操作同步更新。
5. 用量页切换近 7/30 天，指标、趋势、最近 10 条明细和完整用量跳转正确。
6. 小屏下头部与标签可滚动、无重叠。

- [ ] **Step 5: 更新 Harness 文档**

`verify.md` 写入实际命令与结果；`acceptance.md` 记录验收结论与剩余风险；`meta.json` 按实际阶段更新 `phase`（verify / acceptance）与 `approvalRecords`；`spec.md` 变更记录追加实现结果说明。

- [ ] **Step 6: 提交**

```bash
git add docs/harness/requests/2026-08-11-agent-detail-workbench
git commit -m "docs(agent): 完成智能体详情工作台验证记录"
```

## 回滚说明

- 后端：按提交顺序 `git revert` 对应提交即可；本次无数据库表结构变更，无需迁移回滚。
- 前端：删除详情路由与组件并恢复列表页原弹窗逻辑；`routeTree.gen.ts` 随代码一起回滚。
- 关联变更均为实时生效，回滚后下一轮对话即按原配置执行，无需数据修复。
- 若回滚后残留 `apps/backend/.venv` 等环境目录，属于 gitignore 内容，可单独删除。

## 人工确认点

- 已获确认（2026-08-11）：详情工作台方案、七个一级标签、实时生效语义，以及新增 API 契约（智能体详情读取、知识库按智能体查询与解除关联）。
- 实施过程中若发现需要修改数据模型、权限语义或新增 MCP 工具级关联，必须先停止并向用户回报，获得确认后再继续。

## 测试步骤汇总

- 后端：`cd apps/backend && poetry run pytest tests/agent tests/knowledge tests/model_usage -q`
- 后端静态：`cd apps/backend && poetry run ruff check app/modules/agent app/modules/knowledge app/__init__.py tests/agent tests/knowledge`
- 前端工具函数：先 `tsc` 编译到临时目录，再 `node` 执行编译结果。
- 前端静态：`pnpm exec eslint` 与 `pnpm exec prettier --check` 覆盖 `src/api/agent.ts`、`src/api/knowledge.ts`、`src/features/agents`、`src/features/model-usage/index.tsx`、相关路由文件。
- 路由树：`pnpm exec tsr generate`，不可用则以一次 `pnpm dev` 启动生成。
