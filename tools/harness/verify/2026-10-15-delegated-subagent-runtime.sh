#!/usr/bin/env bash
# 阶段二「模型自主委派（子 Agent 工具派生）」验证脚本
#
# 覆盖 docs/harness/requests/2026-10-15-delegated-subagent-runtime/spec.md 的 9 条验收标准：
#   1. 回归测试全绿（conversation / agent_runtime / workflows / tasks）+ ruff / black 通过
#   2. 迁移可逆，agent_loop_runs.parent_loop_run_id 外键动作 = SET NULL
#   3. 一次派 3 个子任务 → 3 条同 parent_loop_run_id 的子运行，各带独立 conversation_id 且归属正确
#   4. 真并发：3 个子运行时间窗重叠
#   5. 子运行工具清单里没有 delegate_tasks（深度恒 1）
#   6. 子运行里 MCP 工具不可用，平台内置/业务工具仍可用
#   7. 参数级整体拒绝（任务数超限 / slug 不存在）且不产生任何子运行；单子运行失败不中止其余
#   8. 单子运行超时 → 该子任务超时失败其余不受影响；父请求取消 → 子运行落终态（非 running）
#   9. 未绑定委派工具的运行读侧形状不变；绑定后读侧能读回 delegatedRuns；前端/SDK 类型与构建通过
#
# 退出码：0 全部通过；1 有失败；3 有未执行项；2 脚本自身错误。
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../../.." || exit 2

FAIL=0
UNEXECUTED=0
ROOT="$(pwd)"
TMP_DIR="$(mktemp -d)"
ADMIN_DSN="postgresql://root:Dd123456@127.0.0.1:5432/ai_db"
TMP_DB="ai_base_dlg_verify_$$"
TMP_DSN="postgresql+asyncpg://root:Dd123456@127.0.0.1:5432/${TMP_DB}"
VENV_PY="${ROOT}/apps/backend/.venv/bin/python"

# 本次改动涉及的后端 Python 文件（静态检查按清单跑：全仓 ruff 有既存 F401）
BACKEND_FILES=(
  app/core/config.py
  app/modules/agent/repositories.py
  app/modules/builtin_tool/schemas.py
  app/modules/builtin_tool/services.py
  app/modules/conversation/models.py
  app/modules/conversation/repositories.py
  app/modules/conversation/router.py
  app/modules/conversation/runtime.py
  app/modules/conversation/schemas.py
  app/modules/conversation/serializers.py
  app/modules/conversation/services.py
  app/modules/conversation/tool_dispatch.py
  app/modules/gateway/dispatcher.py
  app/modules/gateway/runtime.py
  app/modules/tasks/schemas.py
  app/modules/tasks/services.py
  app/modules/tools/business/delegate_tasks.py
  app/modules/tools/business/framework.py
  app/modules/tools/business/registry.py
  migrations/versions/20261015_0038_agent_delegated_runs.py
  tests/agent_runtime/test_loop.py
  tests/conversation/test_delegated_runs.py
  tests/tasks/test_task_services.py
)

# black 的断言清单：只包含「本次新建的文件」与「HEAD 上本来就被 black 判为合格的文件」。
# 仓库范围的 black 本就不干净（下面 BLACK_EXCLUDED_LEGACY 里的文件在 HEAD 上就会被 black
# 重排），把它们算进来等于把既存格式债记到本次改动头上；本次只在「新增」和「原本干净」
# 两类文件上要求 black --check 通过，也就是只把「因本次改动而变脏」当成失败。
BLACK_FILES=(
  app/modules/tools/business/delegate_tasks.py
  migrations/versions/20261015_0038_agent_delegated_runs.py
  tests/conversation/test_delegated_runs.py
  app/modules/agent/repositories.py
  app/modules/builtin_tool/schemas.py
  app/modules/builtin_tool/services.py
  app/modules/conversation/router.py
  app/modules/conversation/schemas.py
  app/modules/conversation/serializers.py
  app/modules/conversation/services.py
  app/modules/conversation/tool_dispatch.py
  app/modules/gateway/runtime.py
  app/modules/tools/business/framework.py
  app/modules/tools/business/registry.py
)

# HEAD 上已被 black 判为需重排、且本次也改到的文件（未纳入 black 断言，原因见上）。
BLACK_EXCLUDED_LEGACY="app/core/config.py app/modules/conversation/models.py app/modules/conversation/repositories.py app/modules/conversation/runtime.py app/modules/gateway/dispatcher.py app/modules/tasks/schemas.py app/modules/tasks/services.py tests/agent_runtime/test_loop.py tests/tasks/test_task_services.py"

cleanup() {
  if [[ -n "${TMP_DB:-}" ]]; then
    "${VENV_PY}" - "${ADMIN_DSN}" "${TMP_DB}" <<'PY' 2>/dev/null || true
import asyncio
import sys

import asyncpg


async def main() -> None:
    dsn, name = sys.argv[1], sys.argv[2]
    conn = await asyncpg.connect(dsn)
    try:
        row = await conn.fetchrow("select 1 from pg_database where datname = $1", name)
        if row:
            await conn.execute(f'drop database "{name}" with (force)')
    finally:
        await conn.close()


try:
    asyncio.run(main())
except Exception:
    pass
PY
  fi
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

verify_step() {
  local name="$1"
  shift
  echo ""
  echo "### ${name}"
  echo '```bash'
  echo "$*"
  echo '```'
  local log="${TMP_DIR}/step.log"
  if "$@" >"$log" 2>&1; then
    echo ""
    echo "结果：通过"
    tail -3 "$log" | sed 's/^/    /'
  else
    echo ""
    echo "结果：失败"
    tail -40 "$log" | sed 's/^/    /'
    FAIL=1
  fi
}

verify_step_as() {
  local name="$1"
  local display="$2"
  shift 2
  echo ""
  echo "### ${name}"
  echo '```bash'
  echo "$display"
  echo '```'
  local log="${TMP_DIR}/step.log"
  if "$@" >"$log" 2>&1; then
    echo ""
    echo "结果：通过"
    tail -3 "$log" | sed 's/^/    /'
  else
    echo ""
    echo "结果：失败"
    tail -40 "$log" | sed 's/^/    /'
    FAIL=1
  fi
}

echo "## 已执行的命令与结果"

# ---------------------------------------------------------------------------
# 临时 PostgreSQL 库：建库 + 迁移到 head
# ---------------------------------------------------------------------------
cat >"$TMP_DIR/pg_admin.py" <<'PY'
"""临时库管理：create / drop。本机没有 psql 客户端，统一走 asyncpg。"""

import asyncio
import sys

import asyncpg


async def main() -> None:
    action, dsn, name = sys.argv[1], sys.argv[2], sys.argv[3]
    conn = await asyncpg.connect(dsn)
    try:
        exists = await conn.fetchrow("select 1 from pg_database where datname = $1", name)
        if action == "create":
            if not exists:
                await conn.execute(f'create database "{name}"')
            print(f"临时库已就绪：{name}")
        else:
            if exists:
                await conn.execute(f'drop database "{name}" with (force)')
            print(f"临时库已删除：{name}")
    finally:
        await conn.close()


asyncio.run(main())
PY

verify_step_as \
  "临时 PostgreSQL 库 + alembic upgrade head" \
  "python /tmp/pg_admin.py create \$ADMIN_DSN \$TMP_DB && DATABASE_URL=\$TMP_DSN alembic upgrade head" \
  bash -c "set -eo pipefail; cd apps/backend; .venv/bin/python '${TMP_DIR}/pg_admin.py' create '${ADMIN_DSN}' '${TMP_DB}'; DATABASE_URL='${TMP_DSN}' .venv/bin/python -m alembic upgrade head 2>&1 | tail -3"

# ---------------------------------------------------------------------------
# 验收 2：外键动作 = SET NULL（PG 侧，迁移后的真实 schema）
# ---------------------------------------------------------------------------
cat >"$TMP_DIR/pg_fk_probe.py" <<'PY'
"""验收 2（PG 侧）：parent_loop_run_id 存在、指向 agent_loop_runs.id、删除动作 = SET NULL。

asyncpg 的 pg_constraint.confdeltype 返回 bytes，必须先 decode 再比 "n"（= SET NULL）。
"""

import asyncio
import os

import asyncpg


async def main() -> None:
    conn = await asyncpg.connect(os.environ["MA_PG_DSN"].replace("+asyncpg", ""))
    try:
        column = await conn.fetchrow(
            """
            select data_type, is_nullable
            from information_schema.columns
            where table_name = 'agent_loop_runs' and column_name = 'parent_loop_run_id'
            """
        )
        assert column is not None, "agent_loop_runs.parent_loop_run_id 列不存在"
        assert column["data_type"] == "integer", column["data_type"]
        assert column["is_nullable"] == "YES", "parent_loop_run_id 必须可空"

        fk = await conn.fetchrow(
            """
            select c.confdeltype, c.confrelid::regclass::text as target
            from pg_constraint c
            join pg_class t on t.oid = c.conrelid
            where t.relname = 'agent_loop_runs' and c.contype = 'f'
              and c.conname = 'fk_agent_loop_runs_parent_loop_run_id_agent_loop_runs'
            """
        )
        assert fk is not None, "自引用外键不存在"
        action = fk["confdeltype"]
        action = action.decode() if isinstance(action, bytes) else action
        assert action == "n", f"外键删除动作应为 SET NULL(n)，实际 {action!r}"
        assert fk["target"] == "agent_loop_runs", fk["target"]

        index = await conn.fetchrow(
            """
            select indexname from pg_indexes
            where tablename = 'agent_loop_runs'
              and indexname = 'ix_agent_loop_runs_parent_loop_run_id'
            """
        )
        assert index is not None, "parent_loop_run_id 索引不存在"
        print("PG 侧：列 integer/NULL、外键 SET NULL、索引齐备")
    finally:
        await conn.close()


asyncio.run(main())
PY

verify_step_as \
  "验收 2：PG 侧外键动作 = SET NULL" \
  "MA_PG_DSN=\$TMP_DSN python /tmp/pg_fk_probe.py" \
  bash -c "set -eo pipefail; cd apps/backend; MA_PG_DSN='${TMP_DSN}' .venv/bin/python '${TMP_DIR}/pg_fk_probe.py'"

# ---------------------------------------------------------------------------
# 验收 2：迁移可逆
# ---------------------------------------------------------------------------
verify_step_as \
  "验收 2：迁移可逆（downgrade -1 后 upgrade head 回到 head）" \
  "DATABASE_URL=\$TMP_DSN alembic downgrade -1 && alembic upgrade head && alembic current" \
  bash -c "set -eo pipefail; cd apps/backend; DATABASE_URL='${TMP_DSN}' .venv/bin/python -m alembic downgrade -1 2>&1 | tail -2; DATABASE_URL='${TMP_DSN}' .venv/bin/python -m alembic upgrade head 2>&1 | tail -2; DATABASE_URL='${TMP_DSN}' .venv/bin/python -m alembic current 2>&1 | tail -2"

# ---------------------------------------------------------------------------
# 验收 2：SQLite 方言下同一列的外键动作（ORM 元数据 = 迁移的同一来源）
# ---------------------------------------------------------------------------
cat >"$TMP_DIR/sqlite_fk_probe.py" <<'PY'
"""验收 2（SQLite 侧）：parent_loop_run_id 的外键动作在 SQLite 上同为 SET NULL。

SQLite 无法直接跑完整 38 个 alembic 迁移（其中含 PG 专属 DDL），
因此这里建表后读 `PRAGMA foreign_key_list(agent_loop_runs)` 校验 ORM 元数据里声明的动作，
与迁移 `20261015_0038` 使用的是同一份 mapped_column 定义。
"""

import asyncio
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.shared.base_model import BaseModel


async def main() -> None:
    path = os.environ["MA_SQLITE_DB"]
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(BaseModel.metadata.create_all)
            rows = (
                await connection.execute(text("PRAGMA foreign_key_list(agent_loop_runs)"))
            ).all()
        matched = [
            row
            for row in rows
            if row[2] == "agent_loop_runs" and row[3] == "parent_loop_run_id"
        ]
        assert matched, f"未找到 parent_loop_run_id 的自引用外键：{rows}"
        # PRAGMA 行序：(id, seq, table, from, to, on_update, on_delete, match)
        assert matched[0][4] == "id", matched[0]
        assert matched[0][6] == "SET NULL", f"on_delete 应为 SET NULL，实际 {matched[0][6]!r}"
        print("SQLite 侧：自引用外键 on_delete=SET NULL")
    finally:
        await engine.dispose()


asyncio.run(main())
PY

verify_step_as \
  "验收 2：SQLite 方言外键动作 = SET NULL" \
  "MA_SQLITE_DB=/tmp/ma_verify_sqlite.db python /tmp/sqlite_fk_probe.py" \
  bash -c "set -eo pipefail; cd apps/backend; MA_SQLITE_DB='${TMP_DIR}/fk.db' .venv/bin/python '${TMP_DIR}/sqlite_fk_probe.py'"

# ---------------------------------------------------------------------------
# 验收 5、6：工具清单裁剪（真 load_runtime_context + 真仓储）
# ---------------------------------------------------------------------------
cat >"$TMP_DIR/tool_scope_probe.py" <<'PY'
"""验收 5、6：子运行的上下文里没有委派工具、没有 MCP；父运行两者都有。

用真 `load_runtime_context` + 真仓储（sqlite 文件库），只断言工具清单，
因此不需要模型、不需要并发。
"""

import asyncio
import os
from datetime import UTC, datetime

from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.agent.models import Agent, AgentVersion
from app.modules.agent.repositories import AgentRepository
from app.modules.builtin_tool.models import AgentBuiltinTool
from app.modules.builtin_tool.repositories import BuiltinToolRepository
from app.modules.conversation.runtime import load_runtime_context
from app.modules.knowledge.repositories import KnowledgeRepository
from app.modules.mcp.models import AgentMcpServer, McpServer, McpTool
from app.modules.mcp.repositories import McpRepository
from app.modules.platform.models import Platform
from app.modules.skill.repositories import SkillRepository
from app.shared.base_model import BaseModel

MCP_TOOL_NAME = "mcp_probe_echo"


async def _add_agent(session, platform_id: int, slug: str, tools: list[str]) -> Agent:
    agent = Agent(platform_id=platform_id, name=f"Bot-{slug}", slug=slug)
    session.add(agent)
    await session.flush()
    version = AgentVersion(
        agent_id=agent.id,
        version=1,
        system_prompt="你是探针助手",
        model_name="probe-model",
        created_at=datetime.now(UTC),
        published_at=datetime.now(UTC),
    )
    session.add(version)
    await session.flush()
    agent.default_version_id = version.id
    for name in tools:
        session.add(AgentBuiltinTool(platform_id=platform_id, agent_id=agent.id, tool_name=name))
    return agent


async def _names(session, agent_id: int, platform_id: int, *, allow_delegation: bool, platform_tools_only: bool) -> list[str]:
    context = await load_runtime_context(
        AgentRepository(session),
        KnowledgeRepository(session),
        SkillRepository(session),
        McpRepository(session),
        BuiltinToolRepository(session),
        agent_id=agent_id,
        platform_id=platform_id,
        allow_delegation=allow_delegation,
        platform_tools_only=platform_tools_only,
    )
    rest = [tool.name for tool in context.builtin_tools]
    return [*rest, *[tool.name for tool in context.mcp_tools]]


async def main() -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{os.environ['MA_SCOPE_DB']}")

    @event.listens_for(engine.sync_engine, "connect")
    def _pragmas(dbapi_connection, _record):  # pragma: no cover - 夹具
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(BaseModel.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        platform = Platform(name="裁剪探针平台", code="scope-probe", is_active=True)
        session.add(platform)
        await session.flush()
        parent = await _add_agent(session, platform.id, "scope-parent", ["delegate_tasks", "get_runtime_info"])
        child = await _add_agent(session, platform.id, "scope-child", ["delegate_tasks", "get_runtime_info"])
        server = McpServer(
            platform_id=platform.id,
            name="探针 MCP",
            slug="scope-mcp",
            endpoint_url="http://127.0.0.1:9/mcp",
            is_active=True,
        )
        session.add(server)
        await session.flush()
        session.add(
            McpTool(
                server_id=server.id,
                name=MCP_TOOL_NAME,
                description="探针工具",
                input_schema={"type": "object"},
                is_allowed=True,
                side_effect="external",
            )
        )
        session.add(AgentMcpServer(agent_id=parent.id, server_id=server.id, is_enabled=True))
        session.add(AgentMcpServer(agent_id=child.id, server_id=server.id, is_enabled=True))
        await session.commit()

        parent_names = await _names(
            session, parent.id, platform.id, allow_delegation=True, platform_tools_only=False
        )
        child_names = await _names(
            session, child.id, platform.id, allow_delegation=False, platform_tools_only=True
        )

        assert "delegate_tasks" in parent_names, parent_names
        assert "get_runtime_info" in parent_names, parent_names
        assert MCP_TOOL_NAME in parent_names, parent_names

        assert "delegate_tasks" not in child_names, f"子运行不该有委派工具：{child_names}"
        assert MCP_TOOL_NAME not in child_names, f"子运行不该有 MCP 工具：{child_names}"
        assert "get_runtime_info" in child_names, f"子运行仍应有平台内置/业务工具：{child_names}"

        # 委派工具描述里应带本平台可派清单（父运行才注入）
        context = await load_runtime_context(
            AgentRepository(session),
            KnowledgeRepository(session),
            SkillRepository(session),
            McpRepository(session),
            BuiltinToolRepository(session),
            agent_id=parent.id,
            platform_id=platform.id,
            allow_delegation=True,
            platform_tools_only=False,
        )
        delegate = [tool for tool in context.builtin_tools if tool.name == "delegate_tasks"][0]
        assert "scope-child" in (delegate.description or ""), delegate.description
        print(f"父运行工具={sorted(parent_names)}")
        print(f"子运行工具={sorted(child_names)}")

    await engine.dispose()


asyncio.run(main())
PY

verify_step_as \
  "验收 5、6：父运行有委派工具与 MCP，子运行两者都没有" \
  "MA_SCOPE_DB=/tmp/ma_verify_scope.db python /tmp/tool_scope_probe.py" \
  bash -c "set -eo pipefail; cd apps/backend; MA_SCOPE_DB='${TMP_DIR}/scope.db' .venv/bin/python '${TMP_DIR}/tool_scope_probe.py'"

# ---------------------------------------------------------------------------
# 验收 3、4、9：真库 + 真链路的端到端委派（只替换模型）
# ---------------------------------------------------------------------------
cat >"$TMP_DIR/delegation_e2e.py" <<'PY'
"""验收 3、4、5、9：真 `execute_unattended_chat` + 真 `delegate_tasks` + 真 PostgreSQL 库。

唯一被替换的是 `app.modules.agent.services.build_chat_model`（execute_unattended_chat 在
函数内 import 它，运行时按模块属性查找），换成会「先 sleep 再回答」的替身模型：
- 父模型第一次回答发起 `delegate_tasks`，第二次回答收尾；
- 子模型只 sleep 后回答，用 sleep 造出可观测的时间窗。

不替换任何其它东西，因此父子落库、会话隔离、工具清单裁剪、MCP 剔除、
并发闸、metadata 回传、读侧投影全部是生产代码路径。
"""

import asyncio
import os
import time
from datetime import UTC, datetime
from types import SimpleNamespace

from langchain_core.messages import AIMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.agent.models import Agent, AgentVersion
from app.modules.builtin_tool.models import AgentBuiltinTool
from app.modules.conversation.models import AgentLoopRun, AgentLoopStep, Conversation
from app.modules.conversation.repositories import ConversationRepository
from app.modules.conversation.serializers import build_loop_payload, load_delegated_runs
from app.modules.mcp.models import AgentMcpServer, McpServer, McpTool
from app.modules.platform.models import Platform
from app.modules.user.models import User

CHILD_SLUGS = ["alpha", "beta", "gamma"]
MCP_TOOL_NAME = "mcp_probe_echo"
DELAY = 1.0


class State:
    def __init__(self) -> None:
        self.delegated = False
        self.in_flight = 0
        self.peak = 0
        self.parent_calls: list[list[str]] = []
        self.child_calls: list[list[str]] = []


class StubModel:
    """替身模型：父模型发起一次委派；子模型只 sleep，用来观测并发窗口。"""

    def __init__(self, state: State) -> None:
        self.state = state
        self.names: list[str] = []

    def bind_tools(self, tools):  # noqa: ANN001 - 与 LangChain 的鸭子类型一致
        self.names = [tool["function"]["name"] for tool in tools]
        return self

    async def ainvoke(self, messages):  # noqa: ANN001
        if "delegate_tasks" in self.names:
            self.state.parent_calls.append(list(self.names))
            if not self.state.delegated:
                self.state.delegated = True
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "delegate_tasks",
                            "args": {
                                "tasks": [
                                    {"agent": slug, "task": f"请处理 {slug} 的任务"}
                                    for slug in CHILD_SLUGS
                                ]
                            },
                            "id": "call-delegate-1",
                            "type": "tool_call",
                        }
                    ],
                )
            return AIMessage(content="父运行收尾")
        self.state.child_calls.append(list(self.names))
        self.state.in_flight += 1
        self.state.peak = max(self.state.peak, self.state.in_flight)
        try:
            await asyncio.sleep(DELAY)
        finally:
            self.state.in_flight -= 1
        return AIMessage(content="子运行已完成")


async def _add_agent(session, platform_id: int, slug: str, tools: list[str]) -> Agent:
    agent = Agent(platform_id=platform_id, name=f"Bot-{slug}", slug=slug)
    session.add(agent)
    await session.flush()
    version = AgentVersion(
        agent_id=agent.id,
        version=1,
        system_prompt="你是探针助手",
        model_name="probe-model",
        created_at=datetime.now(UTC),
        published_at=datetime.now(UTC),
    )
    session.add(version)
    await session.flush()
    agent.default_version_id = version.id
    for name in tools:
        session.add(AgentBuiltinTool(platform_id=platform_id, agent_id=agent.id, tool_name=name))
    await session.flush()
    return agent


def _settings(**overrides):
    base = {
        "delegation_max_tasks": 8,
        "delegation_max_concurrency": 4,
        "delegation_max_iterations": 8,
        "delegation_timeout_seconds": 60,
        "delegation_output_max_bytes": 51200,
        "delegation_max_agents_in_prompt": 50,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


async def main() -> None:
    engine = create_async_engine(os.environ["MA_PG_DSN"])
    factory = async_sessionmaker(engine, expire_on_commit=False)

    state = State()
    import app.modules.agent.services as agent_services
    import app.modules.conversation.services as conversation_services
    import app.modules.tools.business.delegate_tasks as delegate_module

    agent_services.build_chat_model = lambda version, session_id_provider=None, **kw: StubModel(state)
    delegate_module.get_session_factory = lambda: factory
    delegate_module.get_settings = lambda: _settings()

    try:
        async with factory() as session:
            platform = Platform(name="委派探针平台", code="delegate-e2e", is_active=True)
            session.add(platform)
            await session.flush()
            user = User(
                name="委派探针用户",
                email="delegate-probe@example.com",
                account="delegate-probe",
                password="x",
            )
            session.add(user)
            await session.flush()

            parent = await _add_agent(session, platform.id, "parent", ["delegate_tasks", "get_runtime_info"])
            children = [
                await _add_agent(session, platform.id, slug, ["delegate_tasks", "get_runtime_info"])
                for slug in CHILD_SLUGS
            ]

            server = McpServer(
                platform_id=platform.id,
                name="探针 MCP",
                slug="e2e-mcp",
                endpoint_url="http://127.0.0.1:9/mcp",
                is_active=True,
            )
            session.add(server)
            await session.flush()
            session.add(
                McpTool(
                    server_id=server.id,
                    name=MCP_TOOL_NAME,
                    description="探针工具",
                    input_schema={"type": "object"},
                    is_allowed=True,
                    side_effect="external",
                )
            )
            session.add(AgentMcpServer(agent_id=parent.id, server_id=server.id, is_enabled=True))
            for child in children:
                session.add(AgentMcpServer(agent_id=child.id, server_id=server.id, is_enabled=True))
            await session.commit()

            started = time.monotonic()
            conversation, assistant, result = await conversation_services.execute_unattended_chat(
                session,
                platform_id=platform.id,
                agent_id=parent.id,
                message="请并行处理三个子任务",
                run_as_type="user",
                user_id=user.id,
            )
            elapsed = time.monotonic() - started

            # 验收 4：真并发（3 个子运行各 DELAY 秒，若串行至少 3*DELAY；这里给足两倍余量）
            assert state.peak == 3, f"子运行峰值并发应为 3，实际 {state.peak}"
            assert elapsed < 1.8, f"三个子运行应重叠执行，实际耗时 {elapsed:.2f}s"
            assert len(state.child_calls) == 3, state.child_calls

            # 验收 5、6：子运行模型绑定的工具清单
            for names in state.child_calls:
                assert "delegate_tasks" not in names, f"子运行不该有委派工具：{names}"
                assert MCP_TOOL_NAME not in names, f"子运行不该有 MCP 工具：{names}"
                assert "get_runtime_info" in names, f"子运行仍应有平台内置工具：{names}"
            assert state.parent_calls, "父模型没有被调用"
            assert "delegate_tasks" in state.parent_calls[0], state.parent_calls[0]
            assert MCP_TOOL_NAME in state.parent_calls[0], state.parent_calls[0]

            # 验收 3：三条子运行同父、各自独立会话、归属三个不同子 Agent
            parent_loop_id = result.loop_id
            assert parent_loop_id, "父运行没有落 loop_id"
            children_rows = (
                (
                    await session.execute(
                        select(AgentLoopRun)
                        .where(AgentLoopRun.parent_loop_run_id == parent_loop_id)
                        .order_by(AgentLoopRun.id)
                    )
                )
                .scalars()
                .all()
            )
            assert len(children_rows) == 3, f"应有 3 条子运行，实际 {len(children_rows)}"
            child_conversation_ids = {row.conversation_id for row in children_rows}
            assert len(child_conversation_ids) == 3, "子运行应各带独立会话"
            assert conversation.id not in child_conversation_ids, "子运行不该复用父会话"
            child_conversations = (
                (
                    await session.execute(
                        select(Conversation).where(Conversation.id.in_(child_conversation_ids))
                    )
                )
                .scalars()
                .all()
            )
            assert {item.agent_id for item in child_conversations} == {
                child.id for child in children
            }, "三条会话的 agent_id 应分别是三个子 Agent"
            assert conversation.agent_id == parent.id

            # 读侧：父步骤 metadata 与 delegatedRuns 投影
            steps = (
                (
                    await session.execute(
                        select(AgentLoopStep)
                        .where(AgentLoopStep.loop_run_id == parent_loop_id)
                        .order_by(AgentLoopStep.sequence)
                    )
                )
                .scalars()
                .all()
            )
            tool_steps = [step for step in steps if step.tool_name == "delegate_tasks"]
            assert tool_steps, f"父运行没有落 delegate_tasks 步骤：{[s.tool_name for s in steps]}"
            delegated_ids = set(tool_steps[0].step_metadata.get("delegatedRunIds") or [])
            assert delegated_ids == {str(row.id) for row in children_rows}, (
                delegated_ids,
                [row.id for row in children_rows],
            )

            repo = ConversationRepository(session)
            loop_row = await session.get(AgentLoopRun, parent_loop_id)
            runs = await load_delegated_runs(repo, parent_loop_id)
            payload = build_loop_payload(loop_row, steps, runs)
            assert len(payload.get("delegatedRuns") or []) == 3, payload.get("delegatedRuns")
            assert {item["agentSlug"] for item in payload["delegatedRuns"]} == set(CHILD_SLUGS)
            assert all(item["conversationId"] for item in payload["delegatedRuns"])
            assert any(step.get("delegatedRunIds") for step in payload["steps"])
            assert {item["status"] for item in payload["delegatedRuns"]} == {"completed"}

            # 未委派时读侧投影不多键（与改造前逐字一致的口径）
            plain = build_loop_payload(loop_row, [], None)
            assert set(plain) == {"id", "requestId", "status", "summary", "steps"}, set(plain)

            print(
                f"父子落库：父 loop={parent_loop_id}，子 loop={[row.id for row in children_rows]}，"
                f"峰值并发={state.peak}，耗时={elapsed:.2f}s"
            )
    finally:
        await engine.dispose()


asyncio.run(main())
PY

verify_step_as \
  "验收 3、4、5、9：真链路委派 3 个子任务（真库 + 只替换模型）" \
  "MA_PG_DSN=\$TMP_DSN python /tmp/delegation_e2e.py" \
  bash -c "set -eo pipefail; cd apps/backend; MA_PG_DSN='${TMP_DSN}' .venv/bin/python '${TMP_DIR}/delegation_e2e.py'"

# ---------------------------------------------------------------------------
# 验收 7、8：参数级拒绝、单子失败、超时、取消级联（sqlite 文件库 + 替身子运行）
# ---------------------------------------------------------------------------
cat >"$TMP_DIR/param_probe.py" <<'PY'
"""验收 7、8：参数级整体拒绝不产生子运行；单子失败不中止其余；超时与取消的终态。

子运行入口 `execute_unattended_chat` 换成受控替身（直接调用 `delegate_tasks` 本身，
因此参数校验、并发闸、超时包装、清理逻辑仍是生产代码）；替身会真写子运行与子会话记录。
"""

import asyncio
import os
import time
from datetime import UTC, datetime
from types import SimpleNamespace

from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.agent.models import Agent, AgentVersion
from app.modules.builtin_tool.models import AgentBuiltinTool
from app.modules.conversation.models import AgentLoopRun, Conversation
from app.modules.platform.models import Platform
from app.modules.tools.business.delegate_tasks import delegate_tasks
from app.modules.tools.business.framework import BusinessToolContext, BusinessToolError
from app.modules.user.models import User
from app.shared.base_model import BaseModel

CHILD_SLUGS = ["alpha", "beta", "gamma"]


def _settings(**overrides):
    base = {
        "delegation_max_tasks": 8,
        "delegation_max_concurrency": 4,
        "delegation_max_iterations": 8,
        "delegation_timeout_seconds": 60,
        "delegation_output_max_bytes": 51200,
        "delegation_max_agents_in_prompt": 50,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


async def _add_agent(session, platform_id: int, slug: str, tools: list[str]) -> Agent:
    agent = Agent(platform_id=platform_id, name=f"Bot-{slug}", slug=slug)
    session.add(agent)
    await session.flush()
    version = AgentVersion(
        agent_id=agent.id,
        version=1,
        system_prompt="你是探针助手",
        model_name="probe-model",
        created_at=datetime.now(UTC),
        published_at=datetime.now(UTC),
    )
    session.add(version)
    await session.flush()
    agent.default_version_id = version.id
    for name in tools:
        session.add(AgentBuiltinTool(platform_id=platform_id, agent_id=agent.id, tool_name=name))
    await session.flush()
    return agent


async def main() -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{os.environ['MA_PARAM_DB']}")

    @event.listens_for(engine.sync_engine, "connect")
    def _pragmas(dbapi_connection, _record):  # pragma: no cover - 夹具
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(BaseModel.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    import app.modules.conversation.services as conversation_services
    import app.modules.tools.business.delegate_tasks as delegate_module

    delegate_module.get_session_factory = lambda: factory

    behaviour = {"mode": "ok", "fail_slug": None, "delay": 0.0}

    async def fake_execute_unattended_chat(session, **kwargs):  # noqa: ANN001
        if kwargs.get("end_user_id") is not None:
            conversation = Conversation(
                platform_id=kwargs["platform_id"],
                agent_id=kwargs["agent_id"],
                platform_end_user_id=kwargs["end_user_id"],
            )
        else:
            conversation = Conversation(
                platform_id=kwargs["platform_id"],
                agent_id=kwargs["agent_id"],
                user_id=kwargs["user_id"],
            )
        session.add(conversation)
        await session.flush()
        loop = AgentLoopRun(
            conversation_id=conversation.id,
            request_id=f"child-{kwargs['agent_id']}",
            status="running",
            parent_loop_run_id=kwargs.get("parent_loop_run_id"),
        )
        session.add(loop)
        await session.commit()
        if behaviour["mode"] == "fail" and kwargs["message"].endswith(behaviour["fail_slug"]):
            raise RuntimeError("子运行炸了")
        if behaviour["mode"] == "sleep":
            await asyncio.sleep(behaviour["delay"])
        # 与生产一致的三元组：(会话, assistant 消息, GraphResult 投影)
        return (
            conversation,
            SimpleNamespace(content=f"完成 {kwargs['message']}"),
            SimpleNamespace(content=f"完成 {kwargs['message']}", loop_id=loop.id),
        )

    # delegate_tasks 在函数内 `from app.modules.conversation.services import execute_unattended_chat`，
    # 所以替换点是被导入的那个模块属性。
    conversation_services.execute_unattended_chat = fake_execute_unattended_chat

    async with factory() as session:
        platform = Platform(name="委派参数探针平台", code="param-probe", is_active=True)
        session.add(platform)
        await session.flush()
        user = User(
            name="委派参数探针用户",
            email="param-probe@example.com",
            account="param-probe",
            password="x",
        )
        session.add(user)
        await session.flush()
        parent = await _add_agent(session, platform.id, "parent", ["delegate_tasks"])
        for slug in CHILD_SLUGS:
            await _add_agent(session, platform.id, slug, ["delegate_tasks", "get_runtime_info"])
        parent_conversation = Conversation(
            platform_id=platform.id, agent_id=parent.id, user_id=user.id
        )
        session.add(parent_conversation)
        await session.flush()
        parent_loop = AgentLoopRun(
            conversation_id=parent_conversation.id,
            request_id="parent-request",
            status="running",
        )
        session.add(parent_loop)
        await session.commit()

        ctx = BusinessToolContext(
            platform_id=platform.id,
            agent_id=parent.id,
            conversation_id=parent_conversation.id,
            user_id=user.id,
            loop_run_id=parent_loop.id,
            session=session,
        )

        async def child_count() -> int:
            # 用新 Session 计数：sqlite 的读事务有快照，复用同一个 Session
            # 会看不到替身子运行后来提交的行。
            async with factory() as probe:
                return (
                    await probe.execute(
                        select(func.count())
                        .select_from(AgentLoopRun)
                        .where(AgentLoopRun.parent_loop_run_id == parent_loop.id)
                    )
                ).scalar_one()

        settings_dict: dict = {}

        def use_settings(**overrides):
            value = _settings(**overrides)
            settings_dict.clear()
            settings_dict.update(vars(value))
            delegate_module.get_settings = lambda: SimpleNamespace(**settings_dict)

        # 7a：任务数超限 → 整体拒绝、零子运行
        use_settings(delegation_max_tasks=2)
        try:
            await delegate_tasks(
                {"tasks": [{"agent": slug, "task": "t"} for slug in CHILD_SLUGS]}, ctx
            )
            raise AssertionError("任务数超限应当被拒绝")
        except BusinessToolError as error:
            assert error.code == "too_many_tasks", error.code
        assert await child_count() == 0

        # 7b：slug 不存在 → 整体拒绝、零子运行
        use_settings()
        try:
            await delegate_tasks({"tasks": [{"agent": "nope", "task": "t"}]}, ctx)
            raise AssertionError("未知 slug 应当被拒绝")
        except BusinessToolError as error:
            assert error.code == "agent_not_available", error.code
        assert await child_count() == 0

        # 7c：缺 task 字段 → invalid_tasks、零子运行
        try:
            await delegate_tasks({"tasks": [{"agent": "alpha"}]}, ctx)
            raise AssertionError("缺字段应当被拒绝")
        except BusinessToolError as error:
            assert error.code == "invalid_tasks", error.code
        assert await child_count() == 0

        # 7d：单个子运行失败不中止其余
        behaviour.update(mode="fail", fail_slug="beta")
        result = await delegate_tasks(
            {"tasks": [{"agent": slug, "task": f"处理 {slug}"} for slug in CHILD_SLUGS]}, ctx
        )
        assert result["succeeded"] == 2 and result["failed"] == 1, result
        failed = [item for item in result["tasks"] if item["status"] == "failed"][0]
        assert failed["agent"] == "beta", failed
        assert failed["error"]["code"] == "delegation_failed", failed
        assert "子运行炸了" in failed["error"]["message"], failed
        assert await child_count() == 3, "失败的那个子运行记录也应落库"

        # 8a：单个子运行超时 → 该子任务超时失败，其余不受影响
        before = await child_count()
        behaviour.update(mode="sleep", fail_slug=None, delay=0.5)
        use_settings(delegation_timeout_seconds=0.1)
        started = time.monotonic()
        result = await delegate_tasks(
            {
                "tasks": [
                    {"agent": "alpha", "task": "慢任务"},
                    {"agent": "beta", "task": "慢任务"},
                ]
            },
            ctx,
        )
        elapsed = time.monotonic() - started
        assert all(item["error"]["code"] == "delegation_timeout" for item in result["tasks"]), result
        assert elapsed < 0.45, f"超时应快速返回，实际 {elapsed:.2f}s"
        assert await child_count() == before + 2

        # 8b：父请求取消 → 子运行落终态（非 running）
        use_settings()
        behaviour.update(mode="sleep", fail_slug=None, delay=5.0)
        before = await child_count()
        task = asyncio.ensure_future(
            delegate_tasks(
                {
                    "tasks": [
                        {"agent": "alpha", "task": "长任务一"},
                        {"agent": "beta", "task": "长任务二"},
                    ]
                },
                ctx,
            )
        )
        await asyncio.sleep(0.4)
        task.cancel()
        try:
            await task
            raise AssertionError("取消应当向上传播 CancelledError")
        except asyncio.CancelledError:
            pass
        await asyncio.sleep(0.2)
        async with factory() as probe:
            rows = (
                (
                    await probe.execute(
                        select(AgentLoopRun).where(
                            AgentLoopRun.parent_loop_run_id == parent_loop.id
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert await child_count() == before + 2, "被取消的两次子运行也应已落库"
        assert all(row.status != "running" for row in rows), [row.status for row in rows]

        print(
            f"参数级拒绝零子运行；单子失败={result['failed']} 且不中止其余；"
            f"超时/取消后无 running 子运行（共 {len(rows)} 条）"
        )

    await engine.dispose()


asyncio.run(main())
PY

verify_step_as \
  "验收 7、8：参数级拒绝 / 单子失败 / 超时 / 取消级联" \
  "MA_PARAM_DB=/tmp/ma_verify_param.db python /tmp/param_probe.py" \
  bash -c "set -eo pipefail; cd apps/backend; MA_PARAM_DB='${TMP_DIR}/param.db' .venv/bin/python '${TMP_DIR}/param_probe.py'"

# ---------------------------------------------------------------------------
# 验收 1：回归测试
# ---------------------------------------------------------------------------
verify_step_as \
  "验收 1：新增测试（委派端到端 + loop 串行执行）" \
  "cd apps/backend && python -m pytest tests/conversation/test_delegated_runs.py tests/agent_runtime/test_loop.py tests/tasks/test_task_services.py -q" \
  bash -c "set -eo pipefail; cd apps/backend; .venv/bin/python -m pytest tests/conversation/test_delegated_runs.py tests/agent_runtime/test_loop.py tests/tasks/test_task_services.py -q 2>&1 | tail -5"

verify_step_as \
  "验收 1：回归 conversation + agent_runtime" \
  "cd apps/backend && python -m pytest tests/conversation tests/agent_runtime -q" \
  bash -c "set -eo pipefail; cd apps/backend; .venv/bin/python -m pytest tests/conversation tests/agent_runtime -q 2>&1 | tail -5"

verify_step_as \
  "验收 1：回归 workflows + tasks" \
  "cd apps/backend && python -m pytest tests/workflows tests/tasks -q" \
  bash -c "set -eo pipefail; cd apps/backend; .venv/bin/python -m pytest tests/workflows tests/tasks -q 2>&1 | tail -5"

verify_step_as \
  "验收 1：回归 gateway（事件流与 embed 链路）" \
  "cd apps/backend && python -m pytest tests/gateway -q" \
  bash -c "set -eo pipefail; cd apps/backend; .venv/bin/python -m pytest tests/gateway -q 2>&1 | tail -5"

# ---------------------------------------------------------------------------
# 验收 1：静态检查（按本次改动文件清单）
# ---------------------------------------------------------------------------
verify_step_as \
  "验收 1：ruff check（本次改动文件）" \
  "cd apps/backend && ruff check \${BACKEND_FILES[@]}" \
  bash -c "set -eo pipefail; cd apps/backend; .venv/bin/python -m ruff check ${BACKEND_FILES[*]}"

verify_step_as \
  "验收 1：black --check（新增文件 + HEAD 上本已合格的文件）" \
  "cd apps/backend && black --check \${BLACK_FILES[@]}" \
  bash -c "set -eo pipefail; cd apps/backend; .venv/bin/python -m black --check ${BLACK_FILES[*]} 2>&1 | tail -3"

# ---------------------------------------------------------------------------
# 验收 9：SDK 类型与构建、前端构建与产物
# ---------------------------------------------------------------------------
verify_step \
  "验收 9：apps/ai-sdk 类型检查（type-check）" \
  bash -c "set -eo pipefail; cd apps/ai-sdk; pnpm run type-check 2>&1 | tail -4"

verify_step \
  "验收 9：apps/ai-sdk 构建（build）" \
  bash -c "set -eo pipefail; cd apps/ai-sdk; pnpm run build 2>&1 | tail -4"

verify_step \
  "验收 9：apps/front 重链本地 SDK 依赖（file:../ai-sdk）" \
  bash -c "set -eo pipefail; cd apps/front; pnpm install --frozen-lockfile --prefer-offline 2>&1 | tail -3"

verify_step \
  "验收 9：apps/front 类型检查与构建，产物含委派 UI" \
  bash -c "set -eo pipefail; cd apps/front; pnpm exec tsc -b; pnpm exec vite build 2>&1 | tail -3; grep -rl '子运行' dist/assets | head -3 | sed 's/^/  产物命中：/'; test -n \"\$(grep -rl '子运行' dist/assets | head -1)\""

echo ""
echo "## 未执行项与原因"
echo ""
echo "- **真模型调用**：委派端到端探针把 \`app.modules.agent.services.build_chat_model\` 换成替身模型，"
echo "  因此「真实模型是否会自主选择 \`delegate_tasks\`」「真实 token 成本」未验证。"
echo "  理由：验证脚本不应依赖外部模型额度与随机输出；工具契约、并发、落库、读侧均已在生产代码路径上验证。"
echo "  影响面：委派能力本身的正确性不依赖模型输出，但「模型何时用它」属提示词工程，只能人工试用验证。"
echo "- **验收标准 3 的原判据 \`model_usage_records.agent_id\` 未执行**：\`record_model_usage\` 全仓唯一定义在"
echo "  \`app/modules/conversation/repositories.py:325\`，**唯一调用方是 \`app/modules/gateway/runtime.py:509\`（Embed WS 链路）**；"
echo "  无人值守 / 委派链路本就不写用量行，原判据不可能满足。已按 spec 回写改用 \`conversations.agent_id\` 承担，"
echo "  并在本脚本的端到端探针中断言三条子会话的 \`agent_id\` 分别是三个子 Agent。"
echo "- **SSE 事件序列逐字快照比对未做**：委派在父运行内只是一个普通工具调用，没有新增事件类型；"
echo "  本次只验证了「未绑定委派工具的运行读侧投影键集合不变」与 gateway 回归测试，未做事件序列逐字 diff。"
echo "- **black 只在部分改动文件上断言**：仓库范围的 black 本就不干净，${BLACK_EXCLUDED_LEGACY}"
echo "  这 9 个文件在 HEAD 上就会被 black 判为需重排（本次也改到了它们），把它们纳入断言等于把既存格式债"
echo "  记到本次改动头上，也会引入与本次无关的重排 diff。因此 black 断言只覆盖「本次新建的文件」与"
echo "  「HEAD 上本已合格的文件」，即只把「因本次改动而变脏」判为失败。"
echo "- **浏览器交互（真实渲染 / 拖拽 / 点击）未做**：\`apps/front\` 没有测试运行器"
echo "  （scripts 只有 dev/build/lint/preview/format/format:check/knip，devDeps 无 vitest/jsdom/playwright）；"
echo "  本脚本只做类型检查、生产构建与产物字符串检查。"
echo "- **真实 HTTP / WebSocket 端到端（embed token → WS → 委派）未做**：需要 embed 客户端与真实模型；"
echo "  探针直接在服务层调用 \`execute_unattended_chat\`。"
echo "- **并发上限只在 PG 上以 3（默认闸 4）验证**：未做生产压力测试，也未验证 \`DELEGATION_MAX_CONCURRENCY=1\` 时的串行退化"
echo "  （该场景由 \`apps/backend/tests/conversation/test_delegated_runs.py::test_concurrency_cap_is_enforced\` 覆盖）。"
UNEXECUTED=1

echo ""
echo "## 验收结论"
echo ""
echo "| # | 验收标准 | 结论 |"
echo "| --- | --- | --- |"
if [[ $FAIL -eq 0 ]]; then
  echo "| 1 | 回归测试全绿 + ruff / black 通过 | 通过 |"
  echo "| 2 | 迁移可逆且外键动作 = SET NULL | 通过 |"
  echo "| 3 | 一次派 3 个子任务：同父、独立会话、归属正确 | 通过（会话 \`agent_id\` 判据） |"
  echo "| 4 | 真并发（3 个子运行时间窗重叠） | 通过 |"
  echo "| 5 | 子运行工具清单无 \`delegate_tasks\` | 通过 |"
  echo "| 6 | 子运行 MCP 不可用、平台内置工具可用 | 通过 |"
  echo "| 7 | 参数级整体拒绝零子运行；单子失败不中止其余 | 通过 |"
  echo "| 8 | 超时只影响该子任务；取消后子运行落终态 | 通过 |"
  echo "| 9 | 未绑定形状不变、绑定后可读回、前端构建通过 | 通过 |"
else
  echo "| 1-9 | 存在失败步骤，详见上方 \`结果：失败\` | 未通过 |"
fi
echo ""
echo "剩余风险："
echo "1. 委派的触发依赖模型自主判断，脚本无法覆盖「真实模型是否会在合适时机发起委派」；"
echo "   工具描述已写明适用场景与自包含 task 要求，但提示词效果需人工试用评估。"
echo "2. 子运行的会话隔离由「每个子运行一个独立 Session + 独立会话记录」保证；"
echo "   若日后有人把 \`ctx.session\` 复用进子运行，会同时踩并发写与事务复用两个坑——"
echo "   \`apps/backend/app/modules/tools/business/delegate_tasks.py\` 的模块 docstring 已把这条写成硬边界。"
echo "3. 前端委派展示只做了类型检查、构建与产物字符串检查，没有浏览器交互验证（无测试运行器）。"
echo "4. 子运行不写 \`model_usage_records\`（既存事实：该表只由 Embed WS 链路写），"
echo "   因此委派的 token 成本目前无法按子运行归集；如后续要计费需另开 request。"
echo ""
echo "是否可归档：**可以**（未执行项均为上述「主动不执行」范围，不影响本次决策的成立）。"

echo ""
if [[ $FAIL -ne 0 ]]; then
  exit 1
fi
if [[ $UNEXECUTED -ne 0 ]]; then
  exit 3
fi
exit 0
