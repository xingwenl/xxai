#!/usr/bin/env bash
# 子智能体绑定（agent_subagents）验证脚本
#
# 覆盖 docs/harness/requests/2026-10-21-subagent-bindings/spec.md 的 7 条验收标准：
#   1. 迁移 up/down 往返，唯一约束 / CASCADE / 索引在真实 PG schema 上生效
#   2. 绑定接口：管理员可读写；自指 / 重复 / 跨平台 / 不存在的绑定被拒且不落库
#   3. 候选收窄：有绑定只列绑定内「已发布 + 启用」子 Agent；非候选 slug 整体拒绝并回可用清单；
#      无绑定回退全平台已发布（排除自己）
#   4. 自克隆：省略 agent 时用父 Agent 的配置跑子运行（新会话），role 进子运行系统提示，
#      delegatedRuns 里 mode="self"
#   5. 每个委派子运行恰好 1 条 model_usage_records，delegatedRuns.usage 与其三项 token 一致
#   6. 回归：子运行仍无 delegate_tasks / MCP，绑定收窄不改变深度恒 1 与工具裁剪
#   7. 本脚本退出码 = 0
#
# 退出码：0 全部通过；1 有失败；3 有未执行项；2 脚本自身错误。
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../../.." || exit 2

FAIL=0
UNEXECUTED=0
ROOT="$(pwd)"
TMP_DIR="$(mktemp -d)"
ADMIN_DSN="postgresql://root:Dd123456@127.0.0.1:5432/postgres"
TMP_DB="ai_base_subagent_verify_$$"
TMP_DSN="postgresql+asyncpg://root:Dd123456@127.0.0.1:5432/${TMP_DB}"
VENV_PY="${ROOT}/apps/backend/.venv/bin/python"

# 本次改动涉及的后端 Python 文件（静态检查按清单跑：全仓 ruff 有既存 F401）
BACKEND_FILES=(
  app/modules/agent/models.py
  app/modules/agent/repositories.py
  app/modules/agent/router.py
  app/modules/agent/schemas.py
  app/modules/agent/services.py
  app/modules/conversation/repositories.py
  app/modules/conversation/runtime.py
  app/modules/conversation/serializers.py
  app/modules/conversation/services.py
  app/modules/tasks/schemas.py
  app/modules/tools/business/delegate_tasks.py
  migrations/versions/20261021_0045_agent_subagents.py
  tests/agent/test_subagent_bindings.py
  tests/conversation/test_delegated_runs.py
  tests/tasks/test_task_services.py
)

FRONT_FILES=(
  src/api/agent.ts
  src/features/agents/agent-subagents-tab.tsx
  src/features/agents/agent-detail-page.tsx
)

cleanup() {
  cat >"$TMP_DIR/pg_drop.py" <<'PY' 2>/dev/null
import asyncio
import os

import asyncpg


async def main() -> None:
    conn = await asyncpg.connect(os.environ["ADMIN_DSN"])
    try:
        exists = await conn.fetchrow(
            "select 1 from pg_database where datname = $1", os.environ["TMP_DB"]
        )
        if exists:
            await conn.execute(f'drop database "{os.environ["TMP_DB"]}" with (force)')
    finally:
        await conn.close()


asyncio.run(main())
PY
  ADMIN_DSN="$ADMIN_DSN" TMP_DB="$TMP_DB" "$VENV_PY" "$TMP_DIR/pg_drop.py" >/dev/null 2>&1 || true
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
# 验收 1、2、3、4、5、6（静态与单测部分）：ruff + 相关测试
# ---------------------------------------------------------------------------
verify_step_as \
  "后端静态检查（本次改动文件）" \
  "apps/backend/.venv/bin/python -m ruff check <改动文件清单>" \
  bash -c "set -eo pipefail; cd apps/backend; .venv/bin/python -m ruff check ${BACKEND_FILES[*]}"

verify_step_as \
  "后端测试（agent / conversation / tasks / builtin_tool）" \
  "apps/backend/.venv/bin/python -m pytest tests/agent tests/conversation tests/tasks tests/builtin_tool -q" \
  bash -c "set -eo pipefail; cd apps/backend; .venv/bin/python -m pytest tests/agent tests/conversation tests/tasks tests/builtin_tool -q 2>&1 | tail -5"

# ---------------------------------------------------------------------------
# 临时 PostgreSQL 库：建库 + 迁移到 head
# ---------------------------------------------------------------------------
cat >"$TMP_DIR/pg_admin.py" <<'PY'
"""临时库管理：本机没有 psql 客户端，统一走 asyncpg。"""

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
# 验收 1：agent_subagents 在 PG 上的真实 schema：唯一约束、两个 CASCADE 外键、两个索引
# ---------------------------------------------------------------------------
cat >"$TMP_DIR/schema_probe.py" <<'PY'
"""验收 1：迁移后的 agent_subagents 约束/外键动作/索引都真实存在。"""

import asyncio
import os

import asyncpg


async def main() -> None:
    conn = await asyncpg.connect(os.environ["MA_PG_DSN"].replace("+asyncpg", ""))
    try:
        columns = await conn.fetch(
            """
            select column_name, is_nullable
            from information_schema.columns
            where table_name = 'agent_subagents'
            order by ordinal_position
            """
        )
        names = [row["column_name"] for row in columns]
        assert names[:5] == [
            "id",
            "parent_agent_id",
            "child_agent_id",
            "sort_order",
            "enabled",
        ], names
        nullable = {row["column_name"]: row["is_nullable"] for row in columns}
        assert nullable["parent_agent_id"] == "NO"
        assert nullable["child_agent_id"] == "NO"

        unique = await conn.fetch(
            """
            select conname, pg_get_constraintdef(oid) as definition
            from pg_constraint
            where conrelid = 'agent_subagents'::regclass and contype = 'u'
            """
        )
        assert any(
            "parent_agent_id" in row["definition"] and "child_agent_id" in row["definition"]
            for row in unique
        ), [row["definition"] for row in unique]

        fks = await conn.fetch(
            """
            select conname, pg_get_constraintdef(oid) as definition
            from pg_constraint
            where conrelid = 'agent_subagents'::regclass and contype = 'f'
            """
        )
        definitions = [row["definition"] for row in fks]
        assert len(definitions) == 2, definitions
        for definition in definitions:
            assert "agents(id)" in definition, definition
            assert "ON DELETE CASCADE" in definition, definition

        indexes = await conn.fetch(
            "select indexname from pg_indexes where tablename = 'agent_subagents'"
        )
        index_names = {row["indexname"] for row in indexes}
        assert "ix_agent_subagents_parent_agent_id" in index_names, index_names
        assert "ix_agent_subagents_child_agent_id" in index_names, index_names
        print(f"schema OK：columns={names}，fks={len(definitions)}，indexes={sorted(index_names)}")
    finally:
        await conn.close()


asyncio.run(main())
PY

verify_step_as \
  "验收 1：agent_subagents 唯一约束 / CASCADE 外键 / 索引（真实 PG schema）" \
  "MA_PG_DSN=\$TMP_DSN python /tmp/schema_probe.py" \
  bash -c "set -eo pipefail; cd apps/backend; MA_PG_DSN='${TMP_DSN}' .venv/bin/python '${TMP_DIR}/schema_probe.py'"

verify_step_as \
  "验收 1：迁移往返（downgrade -1 → upgrade head → current）" \
  "alembic downgrade -1 && alembic upgrade head && alembic current" \
  bash -c "set -eo pipefail; cd apps/backend; DATABASE_URL='${TMP_DSN}' .venv/bin/python -m alembic downgrade -1 2>&1 | tail -2; DATABASE_URL='${TMP_DSN}' .venv/bin/python -m alembic upgrade head 2>&1 | tail -2; DATABASE_URL='${TMP_DSN}' .venv/bin/python -m alembic current 2>&1 | tail -2"

# ---------------------------------------------------------------------------
# 验收 3、4、5、6：真库 + 真链路（只替换模型），绑定收窄 + 自克隆 + 用量 + 工具裁剪
# ---------------------------------------------------------------------------
cat >"$TMP_DIR/subagent_e2e.py" <<'PY'
"""验收 3、4、5、6：真 execute_unattended_chat + 真 delegate_tasks + 真 PostgreSQL。

唯一被替换的是 app.modules.agent.services.build_chat_model（函数内延迟 import，
运行时按模块属性查找）。替身模型：

- 父模型第一轮发起一次 delegate_tasks：一条派给绑定子 Agent alpha，一条省略 agent
  并要求 role（= 自克隆）；第二轮收尾。两轮都带 usage_metadata，便于校验落库用量；
- 子模型只回复固定内容，并记录自己拿到的工具清单与系统提示。

不替换其它任何东西：候选收窄、绑定校验、子运行落库、会话隔离、工具裁剪、用量
记账、delegatedRuns 读侧投影全部走生产代码。
"""

import asyncio
import os
from datetime import UTC, datetime

from langchain_core.messages import AIMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.agent.models import Agent, AgentVersion, SubagentBinding
from app.modules.builtin_tool.models import AgentBuiltinTool
from app.modules.conversation.models import (
    AgentLoopRun,
    AgentLoopStep,
    Conversation,
    ModelUsageRecord,
)
from app.modules.conversation.repositories import ConversationRepository
from app.modules.conversation.serializers import build_loop_payload, load_delegated_runs
from app.modules.platform.models import Platform
from app.modules.tool_approval.contracts import (
    INHERITABLE_DECIDER_ATTR,
    ConfirmationDecision,
)
from app.modules.tools.business.framework import BusinessToolError
from app.modules.user.models import User

CHILD_USAGE = {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18}
ROLE_TEXT = "只负责核对金额"


def build_auto_decider():
    """与「任务到点运行」同形的无人值守裁决器：立刻批准并标记可被子运行继承。

    生产代码里这个裁决器由 app/modules/tasks/unattended.py 构造；这里就地构造
    是为了避免把任务模块整包 import 进来（它牵动与本次验收无关的模块）。
    """

    async def decide(tool, outcome):  # noqa: ANN001, ANN201
        return ConfirmationDecision(approved=True, reason="auto_approved")

    setattr(decide, INHERITABLE_DECIDER_ATTR, True)
    return decide


class State:
    def __init__(self) -> None:
        self.delegated = False
        self.in_flight = 0
        self.peak = 0
        self.parent_calls: list[list[str]] = []
        self.child_tools: list[list[str]] = []
        self.child_systems: list[str] = []


class StubModel:
    """替身模型：带 delegate_tasks 的是父模型，否则是子模型。"""

    model_name = "stub-model"

    def __init__(self, state: State) -> None:
        self.state = state
        self.names: list[str] = []

    def bind_tools(self, tools):  # noqa: ANN001, ANN201
        self.names = [tool["function"]["name"] for tool in tools]
        return self

    async def ainvoke(self, messages):  # noqa: ANN001, ANN201
        if "delegate_tasks" in self.names:
            self.state.parent_calls.append(list(self.names))
            if not self.state.delegated:
                self.state.delegated = True
                return AIMessage(
                    content="",
                    usage_metadata=CHILD_USAGE,
                    tool_calls=[
                        {
                            "name": "delegate_tasks",
                            "args": {
                                "tasks": [
                                    {"agent": "alpha", "task": "请处理退款工单"},
                                    {"task": "核对金额", "role": ROLE_TEXT},
                                ]
                            },
                            "id": "call-delegate-1",
                            "type": "tool_call",
                        }
                    ],
                )
            return AIMessage(content="父运行收尾", usage_metadata=CHILD_USAGE)

        self.state.child_tools.append(list(self.names))
        self.state.child_systems.append(str(messages[0].content))
        self.state.in_flight += 1
        self.state.peak = max(self.state.peak, self.state.in_flight)
        try:
            await asyncio.sleep(0.3)
        finally:
            self.state.in_flight -= 1
        return AIMessage(content="子运行已完成", usage_metadata=CHILD_USAGE)


async def _add_agent(session, platform_id: int, slug: str, tools: list[str]) -> Agent:
    agent = Agent(platform_id=platform_id, name=f"Bot-{slug}", slug=slug)
    session.add(agent)
    await session.flush()
    version = AgentVersion(
        agent_id=agent.id,
        version=1,
        system_prompt=f"你是 {slug} 智能体",
        temperature=0.2,
        model_options={},
        created_at=datetime.now(UTC),
        published_at=datetime.now(UTC),
    )
    session.add(version)
    await session.flush()
    agent.default_version_id = version.id
    for name in tools:
        session.add(
            AgentBuiltinTool(platform_id=platform_id, agent_id=agent.id, tool_name=name)
        )
    await session.flush()
    return agent


async def main() -> None:
    engine = create_async_engine(os.environ["MA_PG_DSN"])
    factory = async_sessionmaker(engine, expire_on_commit=False)

    state = State()
    import app.modules.agent.services as agent_services
    import app.modules.conversation.services as conversation_services
    import app.modules.tools.business.delegate_tasks as delegate_module

    agent_services.build_chat_model = lambda version, **kw: StubModel(state)
    delegate_module.get_session_factory = lambda: factory

    try:
        async with factory() as session:
            platform = Platform(name="子智能体探针平台", code="subagent-e2e", is_active=True)
            session.add(platform)
            await session.flush()
            user = User(
                name="子智能体探针用户",
                email="subagent-probe@example.com",
                account="subagent-probe",
                password="x",
            )
            session.add(user)
            await session.flush()

            tools = ["delegate_tasks", "get_runtime_info"]
            parent = await _add_agent(session, platform.id, "parent", tools)
            alpha = await _add_agent(session, platform.id, "alpha", tools)
            await _add_agent(session, platform.id, "ghost", tools)
            plain = await _add_agent(session, platform.id, "plain", tools)
            session.add(SubagentBinding(parent_agent_id=parent.id, child_agent_id=alpha.id))
            await session.commit()

            # ---------- 验收 3、4、5、6：一次真实委派 ----------
            # delegate_tasks 声明了 side_effect=write：没有裁决器会被「无确认通道」
            # 拒绝，所以按任务链路的做法注入一个可继承的自动批准裁决器。
            conversation, _assistant, result = await conversation_services.execute_unattended_chat(
                session,
                platform_id=platform.id,
                agent_id=parent.id,
                message="请并行处理绑定子智能体与自克隆子任务",
                run_as_type="user",
                user_id=user.id,
                confirmation_decider=build_auto_decider(),
            )

            parent_loop_id = result.loop_id
            assert parent_loop_id, "父运行没有落 loop_id"
            assert state.parent_calls, "父模型没有被调用"
            assert state.peak == 2, f"两个子运行应并发，峰值 {state.peak}"
            assert len(state.child_tools) == 2, state.child_tools

            # 验收 6：子运行工具清单里没有 delegate_tasks（深度恒 1），平台内置工具仍在
            for names in state.child_tools:
                assert "delegate_tasks" not in names, names
                assert "get_runtime_info" in names, names

            children = (
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
            assert len(children) == 2, f"应有 2 条子运行，实际 {len(children)}"
            child_conversations = (
                (
                    await session.execute(
                        select(Conversation).where(
                            Conversation.id.in_({row.conversation_id for row in children})
                        )
                    )
                )
                .scalars()
                .all()
            )
            by_conversation = {item.id: item for item in child_conversations}
            assert len(child_conversations) == 2, "子运行应各带独立会话"
            assert conversation.id not in by_conversation, "子运行不该复用父会话"

            # 验收 3：绑定子运行归 alpha，自克隆子运行归父 Agent 自己
            agent_ids = {item.agent_id for item in child_conversations}
            assert agent_ids == {alpha.id, parent.id}, agent_ids
            modes = {row.run_metadata.get("delegationMode") for row in children}
            assert modes == {"bound", "self"}, modes

            # 验收 4：role 只进自克隆子运行的系统提示，绑定子 Agent 保持自身人格
            self_system = next(
                system
                for system in state.child_systems
                if "你是 parent 智能体" in system
            )
            bound_system = next(
                system
                for system in state.child_systems
                if "你是 alpha 智能体" in system
            )
            assert ROLE_TEXT in self_system, self_system
            assert ROLE_TEXT not in bound_system, bound_system

            # 验收 5：每个子运行恰好 1 条用量记录，且 token 与 usage 一致
            usage_rows = (
                (
                    await session.execute(
                        select(ModelUsageRecord).where(
                            ModelUsageRecord.conversation_id.in_(
                                {row.conversation_id for row in children}
                            )
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(usage_rows) == 2, f"应有 2 条子运行用量，实际 {len(usage_rows)}"
            usage_by_conversation = {row.conversation_id: row for row in usage_rows}
            for row in children:
                record = usage_by_conversation[row.conversation_id]
                assert record.prompt_tokens == 11, record.prompt_tokens
                assert record.completion_tokens == 7, record.completion_tokens
                assert record.total_tokens == 18, record.total_tokens
                assert record.agent_id == by_conversation[row.conversation_id].agent_id
                assert (record.request_id or "").startswith("loop-"), record.request_id
                assert record.model_name == "stub-model", record.model_name

            # 读侧投影：usage / mode 出现在 delegatedRuns 上
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
            repo = ConversationRepository(session)
            loop_row = await session.get(AgentLoopRun, parent_loop_id)
            runs = await load_delegated_runs(repo, parent_loop_id)
            payload = build_loop_payload(loop_row, steps, runs)
            delegated = payload.get("delegatedRuns") or []
            assert len(delegated) == 2, delegated
            assert {item["mode"] for item in delegated} == {"bound", "self"}, delegated
            assert {item["agentSlug"] for item in delegated} == {"alpha", "parent"}, delegated
            for item in delegated:
                assert item["usage"] == {
                    "promptTokens": 11,
                    "completionTokens": 7,
                    "totalTokens": 18,
                }, item["usage"]

            # ---------- 验收 3：候选收窄 / 非候选拒绝 / 无绑定回退 ----------
            tasks = delegate_module._validate_arguments(
                {"tasks": [{"agent": "ghost", "task": "x"}]}, max_tasks=8
            )
            try:
                await delegate_module._resolve_agents(
                    session,
                    platform_id=platform.id,
                    parent_agent_id=parent.id,
                    tasks=tasks,
                )
                raise AssertionError("绑定收窄后 ghost 不应被派出")
            except BusinessToolError as error:
                assert error.code == "agent_not_available", error.code
                assert "ghost" in error.message and "alpha" in error.message, error.message

            from app.modules.agent.repositories import AgentRepository

            repo_agents = AgentRepository(session)
            bound_candidates = await repo_agents.list_delegatable_agents(
                platform.id, parent.id
            )
            assert [agent.slug for agent in bound_candidates] == ["alpha"], bound_candidates
            fallback_candidates = await repo_agents.list_delegatable_agents(
                platform.id, plain.id
            )
            fallback_slugs = [agent.slug for agent in fallback_candidates]
            assert "ghost" in fallback_slugs and "plain" not in fallback_slugs, fallback_slugs

            print(
                f"e2e OK：父 loop={parent_loop_id}，子 loop={[row.id for row in children]}，"
                f"模式={sorted(modes)}，峰值并发={state.peak}，用量记录={len(usage_rows)} 条"
            )
    finally:
        await engine.dispose()


asyncio.run(main())
PY

verify_step_as \
  "验收 3、4、5、6：真链路委派（绑定子 Agent + 自克隆 + 用量 + 读侧 usage/mode）" \
  "MA_PG_DSN=\$TMP_DSN python /tmp/subagent_e2e.py" \
  bash -c "set -eo pipefail; cd apps/backend; MA_PG_DSN='${TMP_DSN}' .venv/bin/python '${TMP_DIR}/subagent_e2e.py'"

# ---------------------------------------------------------------------------
# 前端：api 契约、tab 页面、路由 tab 枚举的静态检查与类型检查
# ---------------------------------------------------------------------------
verify_step_as \
  "前端 prettier 检查（本次改动文件）" \
  "pnpm --dir apps/front exec prettier --check src/api/agent.ts src/features/agents/agent-subagents-tab.tsx src/features/agents/agent-detail-page.tsx 'src/routes/_authenticated/ai/bots/\$agentId.tsx'" \
  bash -c "cd apps/front; pnpm exec prettier --check src/api/agent.ts src/features/agents/agent-subagents-tab.tsx src/features/agents/agent-detail-page.tsx 'src/routes/_authenticated/ai/bots/\$agentId.tsx' 2>&1 | tail -5"

verify_step_as \
  "前端 eslint 检查（本次改动文件）" \
  "pnpm --dir apps/front exec eslint src/api/agent.ts src/features/agents/agent-subagents-tab.tsx src/features/agents/agent-detail-page.tsx 'src/routes/_authenticated/ai/bots/\$agentId.tsx'" \
  bash -c "cd apps/front; pnpm exec eslint src/api/agent.ts src/features/agents/agent-subagents-tab.tsx src/features/agents/agent-detail-page.tsx 'src/routes/_authenticated/ai/bots/\$agentId.tsx' 2>&1 | tail -5"

verify_step_as \
  "前端类型检查（tsc -b，过滤仓库既存的 node:assert 基线错误）" \
  "pnpm --dir apps/front exec tsc -b --noEmit --force 2>&1 | grep -v 'node:assert' | grep -v 'type definitions for node'" \
  bash -c "cd apps/front; out=\$(pnpm exec tsc -b --noEmit --force 2>&1 || true); rest=\$(printf '%s\n' \"\$out\" | grep -E 'error TS' | grep -v 'node:assert' | grep -v 'type definitions for node' || true); if [ -n \"\$rest\" ]; then printf '%s\n' \"\$rest\"; exit 1; fi; printf '%s\n' \"\$out\" | grep -c 'error TS' | sed 's/^/基线错误条数（均为 node:assert 测试文件既存问题）：/'"

verify_step_as \
  "ai-sdk 类型检查（DelegatedRun usage/mode 与卡片展示）" \
  "pnpm --filter xxai-agent run type-check" \
  bash -c "pnpm --filter xxai-agent run type-check 2>&1 | tail -5"

echo ""
echo "## 未执行项与原因"
echo ""
echo "无。"
echo ""
echo "## 验收结论"
echo ""
if [[ "$FAIL" -eq 0 && "$UNEXECUTED" -eq 0 ]]; then
  echo "7 条验收标准全部有真实输出佐证：迁移 schema 与往返、绑定接口校验与候选收窄、"
  echo "自克隆 role、子运行用量与读侧 usage/mode、子运行工具裁剪、前端与 SDK 类型检查。"
else
  echo "存在失败或未执行项（FAIL=${FAIL}，UNEXECUTED=${UNEXECUTED}），见上方步骤输出。"
fi

echo ""
if [[ "$FAIL" -ne 0 ]]; then
  exit 1
fi
if [[ "$UNEXECUTED" -ne 0 ]]; then
  exit 3
fi
exit 0
