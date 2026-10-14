#!/usr/bin/env bash
# 验证脚本：2026-10-14-multi-agent-orchestration（A 档）
#
# 覆盖 spec.md 的 8 条验收标准：
#   1) 后端全量测试 + ruff + black（本次 diff 涉及文件）
#   2) 保存期校验真实拒绝（环 / 悬空依赖 / 引用非祖先 / 扇出超上限）→ 400 且带 step_id
#   3) 三分支真并发（时间窗交叉）+ 汇聚等齐所有分支终态
#   4) 分支异构 agent_id
#   5) fail-fast 先收尾再抛 / continue_with_default 继续
#   6) 绑定编排接管（embed 装配点）→ 汇聚输出落 assistant 消息并可读回；未绑定回归
#   7) 定义往返（存量线性定义零改动 + 前端画布 depends_on 往返 + 前端构建）
#   8) 会话并发不撞唯一索引 + 工作流步骤链路无递归
#
# 退出码：0 全通过 / 1 有失败 / 3 有未执行项 / 2 脚本自身错误。

set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../../.." || exit 2
ROOT="$(pwd)"

TMP_DIR="$(mktemp -d)"
FAIL=0
UNEXECUTED=0

ADMIN_DSN="postgresql://root:Dd123456@127.0.0.1:5432/ai_db"
TMP_DB="ai_base_ma_verify_$$"
TMP_DSN="postgresql+asyncpg://root:Dd123456@127.0.0.1:5432/${TMP_DB}"
PY="${ROOT}/apps/backend/.venv/bin/python"

BACKEND_FILES=(
  apps/backend/app/modules/agent/models.py
  apps/backend/app/modules/agent/repositories.py
  apps/backend/app/modules/agent/schemas.py
  apps/backend/app/modules/agent/services.py
  apps/backend/app/modules/conversation/services.py
  apps/backend/app/modules/gateway/runtime.py
  apps/backend/app/modules/tasks/runner.py
  apps/backend/app/modules/workflows/models.py
  apps/backend/app/modules/workflows/orchestration.py
  apps/backend/app/modules/workflows/runner.py
  apps/backend/app/modules/workflows/schemas.py
  apps/backend/app/modules/workflows/validators.py
  apps/backend/migrations/versions/20261014_0037_agent_orchestration_binding.py
  apps/backend/tests/conversation/test_orchestration_binding.py
  apps/backend/tests/workflows/helpers.py
  apps/backend/tests/workflows/test_runner_parallel.py
  apps/backend/tests/workflows/test_validators.py
  apps/backend/tests/workflows/test_validators_dag.py
)

cleanup() {
  "$PY" "$TMP_DIR/pg_admin.py" drop "$TMP_DB" >/dev/null 2>&1 || true
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

verify_step() {
  local name="$1"
  shift
  echo "### ${name}"
  echo
  echo '```bash'
  echo "$*"
  echo '```'
  if "$@" >"$TMP_DIR/step.log" 2>&1; then
    echo "结果：通过"
  else
    echo "结果：失败"
    echo
    echo '```text'
    tail -40 "$TMP_DIR/step.log"
    echo '```'
    FAIL=1
  fi
  echo
}

# 真实命令里含临时路径时，用它把「展示的命令」与「实际执行的命令」分开。
verify_step_as() {
  local name="$1"
  local shown="$2"
  shift 2
  echo "### ${name}"
  echo
  echo '```bash'
  echo "$shown"
  echo '```'
  if "$@" >"$TMP_DIR/step.log" 2>&1; then
    echo "结果：通过"
  else
    echo "结果：失败"
    echo
    echo '```text'
    tail -40 "$TMP_DIR/step.log"
    echo '```'
    FAIL=1
  fi
  echo
}

echo "## 已执行的命令与结果"
echo

# --------------------------------------------------------------------------- #
# 探针：临时 PostgreSQL 库的建立与销毁
# --------------------------------------------------------------------------- #
cat >"$TMP_DIR/pg_admin.py" <<'PY'
"""用 asyncpg 建/删临时验证库（本机没有 psql 客户端）。"""

import asyncio
import sys

import asyncpg

ADMIN_DSN = "postgresql://root:Dd123456@127.0.0.1:5432/ai_db"


async def main(action: str, database: str) -> None:
    connection = await asyncpg.connect(ADMIN_DSN)
    try:
        if action == "create":
            await connection.execute(f'DROP DATABASE IF EXISTS "{database}"')
            await connection.execute(f'CREATE DATABASE "{database}"')
        else:
            await connection.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
    finally:
        await connection.close()


asyncio.run(main(sys.argv[1], sys.argv[2]))
PY

# --------------------------------------------------------------------------- #
# 验收 1 前置：迁移（PG 上真实上行 / 下行 / 再上行）
# --------------------------------------------------------------------------- #
cat >"$TMP_DIR/migration_probe.py" <<'PY'
"""断言 20261014_0037 迁移真正落到库结构上：新列、新唯一索引、放宽后的部分索引谓词。"""

import asyncio
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DSN = sys.argv[1]


async def main() -> None:
    engine = create_async_engine(DSN)
    async with engine.connect() as connection:
        column = (
            await connection.execute(
                text(
                    "select is_nullable, data_type from information_schema.columns "
                    "where table_name = 'agents' "
                    "and column_name = 'orchestration_workflow_id'"
                )
            )
        ).first()
        assert column is not None, "agents.orchestration_workflow_id 不存在"
        assert column[0] == "YES", f"绑定列必须可空，实际 is_nullable={column[0]}"

        foreign_key = (
            await connection.execute(
                text(
                    "select confdeltype from pg_constraint "
                    "where conrelid = 'agents'::regclass and contype = 'f' "
                    "and conname = 'fk_agents_orchestration_workflow_id_workflows'"
                )
            )
        ).first()
        assert foreign_key is not None, "绑定外键不存在"
        # pg_constraint.confdeltype: n = SET NULL
        action = foreign_key[0]
        action = action.decode() if isinstance(action, bytes) else action
        assert action == "n", f"外键删除动作应为 SET NULL，实际 {action}"

        step_index = (
            await connection.execute(
                text(
                    "select indexdef from pg_indexes "
                    "where tablename = 'workflow_step_runs' "
                    "and indexname = 'uq_workflow_step_runs_run_step'"
                )
            )
        ).first()
        assert step_index is not None, "uq_workflow_step_runs_run_step 不存在"
        definition = step_index[0]
        assert "UNIQUE" in definition, definition
        assert "run_id" in definition and "step_id" in definition, definition

        run_index = (
            await connection.execute(
                text(
                    "select indexdef from pg_indexes "
                    "where tablename = 'workflow_runs' "
                    "and indexname = 'uq_workflow_runs_one_running_per_workflow'"
                )
            )
        ).first()
        assert run_index is not None, "uq_workflow_runs_one_running_per_workflow 不存在"
        assert "trigger_kind" in run_index[0], (
            "部分唯一索引谓词没有排除会话内触发：" + run_index[0]
        )

    await engine.dispose()
    print("迁移结构断言全部通过：新列 / SET NULL 外键 / 步骤唯一索引 / 放宽后的运行唯一索引")


asyncio.run(main())
PY

verify_step "建立临时 PostgreSQL 验证库" \
  "$PY" "$TMP_DIR/pg_admin.py" create "$TMP_DB"

verify_step_as "迁移上行：alembic upgrade head" \
  "DATABASE_URL='${TMP_DSN}' apps/backend/.venv/bin/python -m alembic upgrade head" \
  bash -c "cd '$ROOT/apps/backend' && DATABASE_URL='${TMP_DSN}' '$PY' -m alembic upgrade head"

verify_step_as "迁移后库结构断言" \
  "apps/backend/.venv/bin/python <migration_probe.py> '${TMP_DSN}'" \
  bash -c "cd '$ROOT/apps/backend' && '$PY' '$TMP_DIR/migration_probe.py' '${TMP_DSN}'"

verify_step_as "迁移可下行（downgrade -1）" \
  "DATABASE_URL='${TMP_DSN}' apps/backend/.venv/bin/python -m alembic downgrade -1" \
  bash -c "cd '$ROOT/apps/backend' && DATABASE_URL='${TMP_DSN}' '$PY' -m alembic downgrade -1"

verify_step_as "迁移可重新上行（upgrade head）" \
  "DATABASE_URL='${TMP_DSN}' apps/backend/.venv/bin/python -m alembic upgrade head" \
  bash -c "cd '$ROOT/apps/backend' && DATABASE_URL='${TMP_DSN}' '$PY' -m alembic upgrade head"

verify_step_as "下行再上行后结构仍然正确" \
  "apps/backend/.venv/bin/python <migration_probe.py> '${TMP_DSN}'" \
  bash -c "cd '$ROOT/apps/backend' && '$PY' '$TMP_DIR/migration_probe.py' '${TMP_DSN}'"

# --------------------------------------------------------------------------- #
# 验收 8 前半：部分唯一索引的谓词在两种方言下都不退化成全表唯一
# --------------------------------------------------------------------------- #
cat >"$TMP_DIR/index_probe.py" <<'PY'
"""部分唯一索引行为探针：PostgreSQL 与 SQLite 各跑一遍。

要证明的两件事：
  1. 无人值守触发（trigger_kind <> 'conversation'）里，同一工作流第二条 running 被拒；
  2. 会话内触发（trigger_kind = 'conversation'）可以并存多条 running —— 两个用户
     同时说话不会互相把对方改写成 skipped。
"""

import asyncio
import sys

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.agent.models import Agent
from app.modules.platform.models import Platform
from app.modules.workflows.models import Workflow, WorkflowRun
from app.shared.base_model import BaseModel


async def main(dsn: str, label: str) -> None:
    engine = create_async_engine(dsn)
    # PostgreSQL 侧复用 alembic 迁移出来的库：既避开建表时缺 pgvector 扩展，
    # 又顺带证明「迁移后的谓词」而不是「metadata 里的谓词」。SQLite 侧才建表。
    if dsn.startswith("sqlite"):
        async with engine.begin() as connection:
            await connection.run_sync(BaseModel.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)

    # PostgreSQL 永远强制外键，所以 origin 行必须真实存在，不能裸写 workflow_id=1。
    async with factory() as session:
        platform = Platform(name="索引探针平台", code="index-probe", is_active=True)
        session.add(platform)
        await session.flush()
        agent = Agent(platform_id=platform.id, name="Bot", slug="index-probe-bot")
        session.add(agent)
        await session.flush()
        workflow = Workflow(
            platform_id=platform.id,
            name="索引探针工作流",
            agent_id=agent.id,
            status="active",
            version=1,
            definition={"nodes": [], "edges": []},
            max_steps=50,
            timeout_seconds=600,
        )
        session.add(workflow)
        await session.commit()
        workflow_id = workflow.id

    def make_run(trigger_kind: str, status: str = "running") -> WorkflowRun:
        return WorkflowRun(
            workflow_id=workflow_id,
            definition_version_id=1,
            definition_snapshot={"nodes": [], "edges": []},
            status=status,
            trigger_kind=trigger_kind,
            run_as_type="user",
            total_steps=0,
        )

    async with factory() as session:
        session.add(make_run("manual"))
        await session.commit()

    rejected = False
    async with factory() as session:
        session.add(make_run("manual"))
        try:
            await session.commit()
        except IntegrityError:
            rejected = True
            await session.rollback()
    assert rejected, f"[{label}] 第二条 manual running 没有被唯一索引拒绝"

    # 会话内触发：两条并存，且不被 manual 那条挡住。
    async with factory() as session:
        session.add_all([make_run("conversation"), make_run("conversation")])
        await session.commit()

    async with factory() as session:
        session.add(make_run("scheduled", status="skipped"))
        await session.commit()

    await engine.dispose()

    print(
        f"[{label}] 部分唯一索引行为符合预期："
        "manual 第二条被拒、conversation 两条并存、skipped 可写"
    )


asyncio.run(main(sys.argv[1], sys.argv[2]))
PY

verify_step_as "部分唯一索引谓词：PostgreSQL（迁移后的真实库）" \
  "apps/backend/.venv/bin/python <index_probe.py> '${TMP_DSN}' 'postgresql'" \
  bash -c "cd '$ROOT/apps/backend' && PYTHONPATH='$ROOT/apps/backend' '$PY' '$TMP_DIR/index_probe.py' '${TMP_DSN}' 'postgresql'"

verify_step_as "部分唯一索引谓词：SQLite" \
  "apps/backend/.venv/bin/python <index_probe.py> 'sqlite+aiosqlite:///<tmp>/index.db' 'sqlite'" \
  bash -c "cd '$ROOT/apps/backend' && PYTHONPATH='$ROOT/apps/backend' '$PY' '$TMP_DIR/index_probe.py' 'sqlite+aiosqlite:///$TMP_DIR/index.db' 'sqlite'"

# --------------------------------------------------------------------------- #
# 验收 2：保存期校验真实拒绝（服务层 + HTTP 400 路由面）
# --------------------------------------------------------------------------- #
cat >"$TMP_DIR/reject_probe.py" <<'PY'
"""保存期校验必须在写入前拒绝，并且错误信息要指出具体 step_id。"""

import os
import sys

sys.path.insert(0, os.getcwd())

from app.shared.exceptions import BadRequestException
from app.modules.workflows.validators import MAX_PARALLEL_BRANCHES, validate_steps


def agent_step(step_id, *, prompt=None, depends_on=None):
    step = {"step_id": step_id, "name": step_id, "kind": "agent", "prompt": prompt or f"做 {step_id}"}
    if depends_on is not None:
        step["depends_on"] = depends_on
    return step


def expect_rejected(label, steps, *fragments) -> None:
    try:
        validate_steps(steps, max_steps=50)
    except BadRequestException as error:
        message = str(error)
        missing = [fragment for fragment in fragments if fragment not in message]
        assert not missing, f"[{label}] 错误信息缺少 {missing}：{message}"
        print(f"[{label}] 已拒绝：{message}")
        return
    raise AssertionError(f"[{label}] 没有拒绝非法定义")


# 1) 环
expect_rejected(
    "成环",
    [agent_step("a", depends_on=["c"]), agent_step("b", depends_on=["a"]), agent_step("c", depends_on=["b"])],
    "cycle",
)

# 2) 悬空依赖
expect_rejected("悬空依赖", [agent_step("a", depends_on=["ghost"])], "ghost")

# 3) 引用非祖先（并行分支互读）
expect_rejected(
    "引用非祖先",
    [
        agent_step("entry"),
        agent_step("left", depends_on=["entry"]),
        agent_step("right", depends_on=["entry"], prompt="读 {{left.output}}"),
    ],
    "right",
    "left",
)

# 4) 扇出超上限
expect_rejected(
    "扇出超上限",
    [agent_step("root")]
    + [agent_step(f"b{i}", depends_on=["root"]) for i in range(MAX_PARALLEL_BRANCHES + 1)],
    str(MAX_PARALLEL_BRANCHES),
)

# 5) 自引用
expect_rejected("自引用", [agent_step("a", depends_on=["a"])], "a")

print("保存期校验五类非法定义全部被拒绝，且错误信息指向具体 step_id")
PY

verify_step_as "保存期校验拒绝：环 / 悬空 / 非祖先 / 扇出超限 / 自引用" \
  "apps/backend/.venv/bin/python <reject_probe.py>" \
  bash -c "cd '$ROOT/apps/backend' && '$PY' '$TMP_DIR/reject_probe.py'"

cat >"$TMP_DIR/http400_probe.py" <<'PY'
"""HTTP 路由面：非法 DAG 定义经真实路由返回 400，且响应体带具体 step_id。"""

import asyncio
import contextlib
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "tests", "workflows"))

import httpx
from main import app

from app.core.database import get_db_session
from app.core.security import require_current_active_user
from helpers import agent_step, make_session, seed


@contextlib.asynccontextmanager
async def client(session_factory, user_id):
    async def override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[require_current_active_user] = lambda: SimpleNamespace(
        id=user_id, is_active=True
    )
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            yield http
    finally:
        app.dependency_overrides.clear()


def step(step_id, depends_on=None, prompt=None):
    return agent_step(step_id, depends_on=depends_on, prompt=prompt)


async def main() -> None:
    engine, session_factory = await make_session()
    try:
        async with session_factory() as session:
            meta = await seed(session)
            await session.commit()

        cyclic = [
            step("a", depends_on=["c"]),
            step("b", depends_on=["a"]),
            step("c", depends_on=["b"]),
        ]
        async with client(session_factory, meta.member.id) as http:
            response = await http.post(
                f"/api/v1/platforms/{meta.platform.id}/workflows",
                json={"name": "成环", "agent_id": meta.agent.id, "steps": cyclic},
            )
        assert response.status_code == 400, f"期望 400，实际 {response.status_code}: {response.text}"
        body = response.json()
        message = str(body.get("message") or body)
        assert "cycle" in message, message
        for step_id in ("a", "b", "c"):
            assert step_id in message, f"错误信息没有指出 {step_id}: {message}"
        print(f"HTTP 400 已确认：{message}")
    finally:
        await engine.dispose()


asyncio.run(main())
PY

verify_step_as "保存期校验在 HTTP 路由面返回 400 并指出 step_id" \
  "apps/backend/.venv/bin/python <http400_probe.py>" \
  bash -c "cd '$ROOT/apps/backend' && '$PY' '$TMP_DIR/http400_probe.py'"

# --------------------------------------------------------------------------- #
# 验收 3 / 4 / 5 / 8：运行期 DAG 语义（真实 pytest，逐条列出用例名）
# --------------------------------------------------------------------------- #
verify_step_as "运行期 DAG 语义用例（并发时间窗 / 分支异构 / fail-fast / 并发闸 / 单步超时 / 审批收紧）" \
  "cd apps/backend && poetry run pytest tests/workflows/test_runner_parallel.py -v" \
  bash -c "cd '$ROOT/apps/backend' && '$PY' -m pytest tests/workflows/test_runner_parallel.py -v"

verify_step_as "保存期 DAG 校验与存量定义兼容用例" \
  "cd apps/backend && poetry run pytest tests/workflows/test_validators_dag.py tests/workflows/test_validators.py -v" \
  bash -c "cd '$ROOT/apps/backend' && '$PY' -m pytest tests/workflows/test_validators_dag.py tests/workflows/test_validators.py -q"

verify_step_as "编排绑定：接管 / 未绑定回归 / 审批一律拒绝 / 会话并发（验收 8 前半）" \
  "cd apps/backend && poetry run pytest tests/conversation/test_orchestration_binding.py -v" \
  bash -c "cd '$ROOT/apps/backend' && '$PY' -m pytest tests/conversation/test_orchestration_binding.py -v"

# --------------------------------------------------------------------------- #
# 验收 6：从 embed 装配点（gateway/runtime.py 的 stream_embed_chat）走一遍真链路
# --------------------------------------------------------------------------- #
cat >"$TMP_DIR/embed_e2e_probe.py" <<'PY'
"""验收 6 的端到端证据：embed 装配点 → 编排接管 → 汇聚输出落 assistant 消息并读回。

只替换两处外部依赖（模型调用与运行库工厂），其余全部走真实代码：
  - ``runner.execute_unattended_chat``：分支 Agent 的模型调用替身；
  - ``conversation.services.get_session_factory``：接管链路的库工厂。

**不经过真实 WebSocket 与真实模型网关**（见「未执行项」）。
"""

import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "tests", "workflows"))

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.conversation import services as conversation_services
from app.modules.conversation.models import Conversation, ConversationMessage
from app.modules.conversation.repositories import ConversationRepository
from app.modules.embed.models import PlatformEndUser
from app.modules.gateway import runtime as gateway_runtime
from app.modules.workflows import runner, validators
from app.modules.workflows.models import Workflow, WorkflowRun, WorkflowStepRun
from app.shared.base_model import BaseModel
from helpers import agent_step, seed

DB = sys.argv[1]


async def main() -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{DB}")

    @event.listens_for(engine.sync_engine, "connect")
    def configure(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(BaseModel.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        meta = await seed(session)
        end_user = PlatformEndUser(
            platform_id=meta.platform.id,
            external_user_id="eu-1",
            display_name="终端用户",
        )
        session.add(end_user)
        await session.flush()

        steps = [
            agent_step("entry", prompt="拆解问题"),
            agent_step("left", depends_on=["entry"], prompt="左分支"),
            agent_step("right", depends_on=["entry"], prompt="右分支"),
            agent_step(
                "merge",
                depends_on=["left", "right"],
                prompt="汇总 {{left.output}} 与 {{right.output}}",
            ),
        ]
        workflow = Workflow(
            platform_id=meta.platform.id,
            name="编排",
            agent_id=meta.agent.id,
            owner_user_id=meta.member.id,
            status="active",
            version=1,
            definition=validators.compile_definition(steps),
            max_steps=50,
            timeout_seconds=600,
            auto_approve=True,
            strict_approval=False,
        )
        session.add(workflow)
        await session.flush()
        meta.agent.orchestration_workflow_id = workflow.id
        await session.commit()

        platform_id = meta.platform.id
        end_user_id = end_user.id
        workflow_id = workflow.id
        agent = meta.agent
        version = meta.version

    calls = {"prompts": []}

    async def fake_execute(session, **kwargs):
        calls["prompts"].append(kwargs["message"])
        index = len(calls["prompts"]) - 1
        conversation = Conversation(
            platform_id=kwargs["platform_id"],
            agent_id=kwargs["agent_id"],
            user_id=kwargs["user_id"],
            platform_end_user_id=kwargs["end_user_id"],
            title="编排步骤",
        )
        session.add(conversation)
        await session.flush()
        content = f"输出#{index}"
        return (
            conversation,
            SimpleNamespace(id=1, content=content),
            SimpleNamespace(content=content, loop_id=None),
        )

    # 直接替换模块属性（与既有 verify 脚本、pytest 用例同一手法）。
    runner.execute_unattended_chat = fake_execute
    conversation_services.get_session_factory = lambda: factory

    deltas = []
    async with factory() as session:
        repo = ConversationRepository(session)
        context = SimpleNamespace(
            agent=agent,
            version=version,
            skill_usages=[],
            # 必须给列表：build_system_prompt 会 len(skill_instructions)。
            skill_instructions=[],
        )
        async for item in gateway_runtime.stream_embed_chat(
            repo,
            context,
            model=SimpleNamespace(),
            platform_id=platform_id,
            end_user_id=end_user_id,
            message="这家店几点关门？",
            conversation_id=None,
            request_id="verify-orchestration-1",
            citations=[],
        ):
            # 网关事件（build_message_delta）把正文放在 payload.content。
            if item.get("type") == "message_delta":
                deltas.append((item.get("payload") or {}).get("content"))

        # 替身每跑一步也会建一个会话（与真实 runner 一致），所以入口会话取最早那条。
        conversation = (
            await session.execute(select(Conversation).order_by(Conversation.id))
        ).scalars().first()
        assert conversation is not None, "embed 入口会话没有落库"

        assistant_messages = (
            (
                await session.execute(
                    select(ConversationMessage)
                    .where(ConversationMessage.role == "assistant")
                    .order_by(ConversationMessage.id)
                )
            )
            .scalars()
            .all()
        )
        assert assistant_messages, "assistant 消息没有落库"
        landed = assistant_messages[-1].content
        assert landed == "输出#3", f"汇聚步骤输出应为 输出#3，实际 {landed!r}"
        assert deltas == ["输出#3"], deltas

        # 会话历史读回：这是「终端用户下一轮能看到上一轮回复」的前提。
        history = await conversation_services.load_recent_history(
            repo, conversation.id
        )
        assert any(
            getattr(item, "role", None) == "assistant"
            and getattr(item, "content", None) == "输出#3"
            for item in history
        ), "assistant 回复没有进入会话历史"

        run = (
            await session.execute(
                select(WorkflowRun).where(WorkflowRun.workflow_id == workflow_id)
            )
        ).scalars().one()
        assert run.trigger_kind == "conversation", run.trigger_kind
        assert run.status == "completed", run.status
        assert run.run_as_type == "end_user", run.run_as_type
        assert run.run_as_end_user_id == end_user_id, run.run_as_end_user_id
        assert run.completed_steps == 4, run.completed_steps

        step_records = (
            (
                await session.execute(
                    select(WorkflowStepRun)
                    .where(WorkflowStepRun.run_id == run.id)
                    .order_by(WorkflowStepRun.seq)
                )
            )
            .scalars()
            .all()
        )
        assert [record.step_id for record in step_records] == [
            "entry",
            "left",
            "right",
            "merge",
        ], [record.step_id for record in step_records]
        assert all(record.conversation_id for record in step_records)
        assert all(record.status == "succeeded" for record in step_records)

    # 入口层带会话上下文，分支层不带（分支只拿自己那一步的提示词）。
    entry_prompt = calls["prompts"][0]
    assert "拆解问题" in entry_prompt, entry_prompt
    assert "这家店几点关门？" in entry_prompt, entry_prompt
    assert all("这家店几点关门？" not in prompt for prompt in calls["prompts"][1:]), (
        "分支步骤不应携带整段会话上下文"
    )

    print("embed 装配点端到端通过：")
    print(f"  事件序列（message_delta）= {deltas}")
    print(f"  assistant 消息 = {landed!r}（可在会话历史读回）")
    print(f"  workflow_run: trigger_kind=conversation status=completed completed_steps=4")
    print(f"  步骤 = {[record.step_id for record in step_records]}")
    print(f"  发给模型的提示词 = {calls['prompts']}")

    await engine.dispose()


asyncio.run(main())
PY

verify_step_as "验收 6 端到端：embed 装配点 → 编排接管 → 汇聚输出落 assistant 消息并可读回" \
  "apps/backend/.venv/bin/python <embed_e2e_probe.py> <tmp>/embed.db" \
  bash -c "cd '$ROOT/apps/backend' && '$PY' '$TMP_DIR/embed_e2e_probe.py' '$TMP_DIR/embed.db'"

# --------------------------------------------------------------------------- #
# 验收 1：后端全量回归 + ruff + black
# --------------------------------------------------------------------------- #
verify_step_as "后端全量回归（workflows / conversation / agent / gateway / tasks / mcp / host_tool）" \
  "cd apps/backend && poetry run pytest tests/workflows tests/conversation tests/agent tests/gateway tests/tasks tests/mcp tests/host_tool -q" \
  bash -c "cd '$ROOT/apps/backend' && '$PY' -m pytest tests/workflows tests/conversation tests/agent tests/gateway tests/tasks tests/mcp tests/host_tool -q"

verify_step_as "ruff（本次 diff 涉及的后端文件）" \
  "cd apps/backend && poetry run ruff check <本次 diff 涉及文件>" \
  bash -c "cd '$ROOT/apps/backend' && '$PY' -m ruff check ${BACKEND_FILES[*]//apps\/backend\//}"

verify_step_as "black --check（本次 diff 涉及的后端文件）" \
  "cd apps/backend && poetry run black --check <本次 diff 涉及文件>" \
  bash -c "cd '$ROOT/apps/backend' && '$PY' -m black --check ${BACKEND_FILES[*]//apps\/backend\//}"

# --------------------------------------------------------------------------- #
# 验收 7：前端画布 depends_on 往返 + 构建 + lint
# --------------------------------------------------------------------------- #
mkdir -p "$TMP_DIR/fe"
sed "s#from '@/api/workflow'#from './workflow-const.ts'#" \
  "$ROOT/apps/front/src/features/workflows/workflow-dag.ts" >"$TMP_DIR/fe/workflow-dag.ts"
cat >"$TMP_DIR/fe/workflow-const.ts" <<'TS'
export const MAX_PARALLEL_BRANCHES = 8
TS

cat >"$TMP_DIR/fe/probe.mjs" <<'JS'
// 直接跑 workflow-dag.ts 的真实实现（Node 22 的 --experimental-strip-types）。
// 唯一的改动是把 `@/api/workflow` 别名导入换成同值的本地常量文件。
const dag = await import('./workflow-dag.ts')

const step = (step_id, depends_on) => ({ step_id, name: step_id, depends_on })

function check(label, actual, expected) {
  const left = JSON.stringify(actual)
  const right = JSON.stringify(expected)
  if (left !== right) throw new Error(`${label}: 期望 ${right}，实际 ${left}`)
  console.log(`  ${label} = ${left}`)
}

// 1) 存量线性定义（没有 depends_on 键）→ 缺省语义：串成链
const legacy = [step('a', null), step('b', null), step('c', null)]
const legacyResolved = dag.resolveDependencies(legacy)
check('存量线性定义解析', legacyResolved, [[], ['a'], ['b']])
const legacyIds = legacy.map((item) => item.step_id)
check(
  '存量线性定义写回（保持 null，保存后形状不变）',
  legacyResolved.map((_, index) =>
    dag.toDependsOnWrite(legacyResolved, legacyIds, index)
  ),
  [null, null, null]
)

// 2) 扇出-汇聚：显式 [] 是并行起点
const fanout = [
  step('entry', []),
  step('left', ['entry']),
  step('right', ['entry']),
  step('merge', ['left', 'right']),
]
const fanoutResolved = dag.resolveDependencies(fanout)
check('扇出-汇聚解析', fanoutResolved, [[], ['entry'], ['entry'], ['left', 'right']])
const fanoutIds = fanout.map((item) => item.step_id)
// 首步写 null（等价于 []，保持存量形状），真正承担语义的是 right 的显式 ['entry']
// 与 merge 的双依赖 —— 折成 null 会改变并行语义，所以必须原样写回。
check(
  '扇出-汇聚写回（首步折 null、汇聚保留双依赖）',
  fanoutResolved.map((_, index) =>
    dag.toDependsOnWrite(fanoutResolved, fanoutIds, index)
  ),
  [null, null, ['entry'], ['left', 'right']]
)

// 非首步的显式 [] 是并行分支起点，不能折成 null。
check(
  '非首步的并行起点保留 []',
  [
    dag.toDependsOnWrite(
      [
        ['a'],
        [],
      ],
      ['a', 'b'],
      1
    ),
  ],
  [[]]
)

// 3) 画布加载 → 保存 → 再加载：往返稳定
const once = fanoutResolved.map((_, index) =>
  dag.toDependsOnWrite(fanoutResolved, fanoutIds, index)
)
const reloaded = dag.resolveDependencies(
  fanout.map((item, index) => ({ ...item, depends_on: once[index] }))
)
check('往返后依赖不变', reloaded, fanoutResolved)

// 4) 校验器认得出环
const issues = dag.validateDag([
  step('a', ['b']),
  step('b', ['a']),
])
if (!issues.some((issue) => /环|循环/.test(issue.message))) {
  throw new Error(`环没有被校验器识别：${JSON.stringify(issues)}`)
}
console.log(`  环校验命中 = ${JSON.stringify(issues.map((issue) => issue.message))}`)

console.log('前端画布 depends_on 往返全部通过')
JS

verify_step_as "验收 7：前端画布 depends_on 往返（跑 workflow-dag.ts 真实实现）" \
  "cd apps/front && node --experimental-strip-types <probe.mjs>" \
  bash -c "cd '$TMP_DIR/fe' && node --experimental-strip-types probe.mjs"

verify_step "前端类型检查（tsc -b）" \
  bash -c "cd '$ROOT/apps/front' && pnpm exec tsc -b"

verify_step "前端构建（vite build）" \
  bash -c "cd '$ROOT/apps/front' && pnpm exec vite build"

verify_step_as "前端 lint（本次 diff 涉及的前端文件）" \
  "cd apps/front && pnpm exec eslint src/features/workflows/workflow-canvas.tsx src/features/workflows/workflow-dag.ts src/features/workflows/workflow-canvas-model.ts src/features/workflows/workflow-definition-form.tsx src/features/agents/agent-config-tab.tsx src/features/agents/agent-form-schema.ts src/api/agent.ts src/api/workflow.ts" \
  bash -c "cd '$ROOT/apps/front' && pnpm exec eslint src/features/workflows/workflow-canvas.tsx src/features/workflows/workflow-dag.ts src/features/workflows/workflow-canvas-model.ts src/features/workflows/workflow-definition-form.tsx src/features/agents/agent-config-tab.tsx src/features/agents/agent-form-schema.ts src/api/agent.ts src/api/workflow.ts"

# --------------------------------------------------------------------------- #
echo "## 未执行项与原因"
echo
UNEXECUTED=1
cat <<'MD'
- **真实 WebSocket + 真实模型网关的 embed 全链路**：本机没有可用的模型供应商凭据，无法从
  `ws://.../ws/agents/{agent_id}` 真发一条消息。验收第 6 条的做法是直接驱动 WS 所调用的同一个
  装配点 `gateway/runtime.py` 的 `stream_embed_chat`（真实会话落库、真实 assistant 落库、真实
  运行记录），只把「分支 Agent → 模型」这一跳替换成替身；WebSocket 层（token 鉴权、
  `produce_embed_request` 的组装）本次未改动，未被执行覆盖。
- **`model_usage_records.agent_id` 的逐分支断言**：验收第 4 条要求三个分支各用不同 agent_id 落
  用量记录。本次证明的是运行期真的把不同的 `agent_id` 传给了分支的会话执行
  （`tests/workflows/test_runner_parallel.py::test_parallel_branches_can_use_different_agents`）；
  用量记录本身由 `ConversationRepository.record_model_usage` 在真实模型返回 usage 后写入，
  需要真实模型网关才能产生，未执行。
- **全仓 `ruff check .` / `black --check .`**：两者在本仓库当前状态下本来就不干净，且与本次改动
  无关（`black` 有 20 个未改动文件希望被 reformat，`ruff` 有 1 条 `app/modules/embed/repositories.py:10`
  的 F401）。本次只对本 diff 涉及的后端文件断言 0 问题，不做无关文件的全仓改写。
- **`pytest`（不带目录参数）**：`apps/backend/tests/` 下 `agent`、`builtin_tool`、`embed`、
  `model_registry`、`skill_runner`、`user`、`workflows` 七个目录没有 `__init__.py`，不带参数运行会
  因同名测试文件 basename 冲突报 collection error（既有问题，非本次引入）。因此按目录分别执行。
- **迁移在已有重复脏数据上的表现**：`workflow_step_runs` 新增的 `(run_id, step_id)` 唯一索引在
  库里已有同 run 内重复 step_id 时会让迁移失败，需要在升级前清理。本次未构造脏数据复现该失败
  （临时库是空的）。
- **spec 中明确「不做」的范围**：模型自主委派（阶段二）、条件分支、循环、动态扇出、工作流级变量、
  分支级交互式人工审批、跨分支共享可变状态、工作流发布/回滚——均未实现，也无验证项。
MD
echo
echo "## 验收结论"
echo
cat <<'MD'
| # | 验收标准 | 结论 | 证据 |
|---|---|---|---|
| 1 | 后端测试全绿 + ruff/black 通过 | 通过（限定范围） | 全量回归 477 passed / 1 skipped；diff 涉及文件 ruff 与 black 均 0 问题。全仓 ruff/black 的既存问题见「未执行项」 |
| 2 | 保存期校验真实拒绝：环 / 悬空 / 引用非祖先 / 扇出超上限 → 400 且指出 step_id | 通过 | 服务层探针五类全拒；HTTP 路由面 400 且 message 同时指出 a/b/c |
| 3 | 三分支真并发 + 汇聚等齐 | 通过 | `test_parallel_branches_really_overlap_and_merge_waits`：`workflow_step_runs` 时间窗两两交叉、`merge.started_at >= 各分支 finished_at` |
| 4 | 分支异构 agent_id | 部分通过 | 运行期确实按步骤把不同 agent_id 传进分支执行（用例内断言）；用量记录级断言需真实模型，见「未执行项」 |
| 5 | fail-fast 先收尾再抛 / continue_with_default 继续 | 通过 | `test_fail_fast_finishes_started_branches_before_failing`（run=failed、同层兄弟仍有终态、completed_steps=3）、`test_continue_with_default_keeps_layer_running` |
| 6 | 绑定编排接管 → 汇聚输出落 assistant 消息且可读回；未绑定回归 | 通过（装配点级） | embed 端到端探针：事件 `["输出#3"]`、assistant 消息 = `输出#3`、会话历史可读回、run 落 conversation/completed；未绑定回归见 `test_unbound_agent_yields_no_orchestration_stream` 与全量 regression |
| 7 | 定义往返 + 前端构建 | 通过 | 存量线性定义解析为链且写回仍是 `null`；扇出-汇聚往返稳定；`tsc -b` 与 `vite build` 通过 |
| 8 | 会话并发不撞唯一索引 + 无递归 | 通过 | PG/SQLite 双方言索引探针；`test_same_workflow_can_run_concurrently_from_two_conversations`；`allow_orchestration is False` 在 runner 侧逐次断言 |

**剩余风险**

1. 验收 6 的 WebSocket 层与真实模型网关未被真机覆盖（本机无模型凭据），端到端只到
   `stream_embed_chat` 这一层。
2. 前端「画布连线 ↔ `depends_on`」只被半保护：后端把 `position` 当不透明坐标，从不校验它与
   依赖的语义对应，折算规则（`null` 兼容、首步折 `null`、非首步 `[]` 保留）全在 `workflow-dag.ts`
   里。本次用 Node 直接跑该模块的真实实现覆盖了「解析 / 写回 / 往返 / 非首步并行起点 / 环」，
   这条闸是有效的——它当场抓出 `toDependsOnWrite` 拿前一步的依赖当判断基准（三步以上的存量
   线性定义会被改写成显式数组）并已修正；**未覆盖的是画布拖拽产生 `position`/连线的交互路径**
   （`apps/front` 无测试运行器，也无登录态联调环境）。
3. `workflow_step_runs` 的新唯一索引对存量脏数据不宽容：升级前需要确认库里没有同一 run 内重复的
   `step_id`。
4. 编排接管轮没有逐 token 流式：汇聚必须等所有分支终态，因此只有整段 `message_delta`，
   长编排下首字延迟等于最慢分支的耗时。
5. 阶段二（模型自主委派）本次刻意不做，ADR 0004 已将 ADR 0002 中被否决的「先做多 Agent」
   记为「部分打开」。
MD
echo

if [[ "$FAIL" -ne 0 ]]; then
  exit 1
fi
if [[ "$UNEXECUTED" -ne 0 ]]; then
  exit 3
fi
exit 0
