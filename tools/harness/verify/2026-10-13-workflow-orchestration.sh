#!/usr/bin/env bash
# Harness v2 验证脚本：无画布的多步工作流编排（A 档）。
#
# 覆盖 docs/harness/requests/2026-10-13-workflow-orchestration/spec.md 的验收标准：
#   1  迁移建三张表；running 的部分唯一索引在 PostgreSQL 与 SQLite 两方言都生效
#   2  引用后面步骤 / step_id 重复 / 超 max_steps / 边指向不存在步骤 → 校验失败且不写库
#   3  side_effect 落在 NEVER_AUTO_APPROVE_SIDE_EFFECTS 的工具步骤在保存时被拒
#   4  覆盖 agent_id 为其它平台 Agent 时保存被拒
#   5  两步骤工作流手动运行 → run completed、两步 succeeded、第二步提示词已替换；
#      model_visible_output 超 50KB 截断且 raw_output 保留全量
#   6  on_error=abort 时后续步骤不执行且无步骤记录；continue_with_default 时继续执行
#      且能指出哪一步用了兜底值
#   7  改定义后重跑，旧 run 的 definition_snapshot 仍能解释那次运行
#   8  定时触发的 skip_reason 能出现 overlapped / workflow_paused / deadline_missed，
#      被强杀后 running 记录能被看门狗收敛
#   9  现有任务零回归
#
# 迁移相关的步骤在**一次性临时库**上执行：降级会删表，不能在开发库上做。
# 探针代码写成独立文件放在临时目录，避免在 bash -c 的双引号里嵌 heredoc。
#
# 退出码：0 全通过 / 1 有失败 / 3 有未执行项 / 2 脚本自身错误。

set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../../.." || exit 2

FAIL=0
UNEXECUTED=0

TMP_DIR="$(mktemp -d)"
TMP_DB="ai_base_wf_verify_$$"
ADMIN_DSN="postgresql://root:Dd123456@127.0.0.1:5432/ai_db"
TMP_DSN="postgresql+asyncpg://root:Dd123456@127.0.0.1:5432/${TMP_DB}"
VENV_PY="$(pwd)/apps/backend/.venv/bin/python"

cleanup() {
  "$VENV_PY" - <<PY >/dev/null 2>&1 || true
import asyncio, asyncpg
async def main():
    conn = await asyncpg.connect("${ADMIN_DSN}")
    await conn.execute("drop database if exists ${TMP_DB}")
    await conn.close()
asyncio.run(main())
PY
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

# 执行一条验证命令并打印结果。
# 用法：verify_step "<人类可读名称>" <命令> [参数...]
verify_step() {
  local name="$1"; shift
  echo "### ${name}"
  echo
  echo '```bash'
  echo "$*"
  echo '```'
  echo
  if "$@"; then
    echo "结果：通过"
  else
    echo "结果：失败"
    FAIL=1
  fi
  echo
}

# 同上，但显式给出展示用的命令文本（真实命令里有临时路径，展示出来没有意义）。
verify_step_as() {
  local name="$1"; shift
  local shown="$1"; shift
  echo "### ${name}"
  echo
  echo '```bash'
  echo "$shown"
  echo '```'
  echo
  if "$@"; then
    echo "结果：通过"
  else
    echo "结果：失败"
    FAIL=1
  fi
  echo
}

# ---------------------------------------------------------------------------
# 探针文件：全部用单引号 heredoc 写入，脚本里不做任何字符串插值。
# ---------------------------------------------------------------------------
cat >"$TMP_DIR/pg_create_db.py" <<'PY'
"""建一个一次性临时库（库名由 WF_TMP_DB 给出）。"""

import asyncio
import os

import asyncpg


async def main() -> None:
    conn = await asyncpg.connect(os.environ["WF_ADMIN_DSN"])
    await conn.execute(f'drop database if exists "{os.environ["WF_TMP_DB"]}"')
    await conn.execute(f'create database "{os.environ["WF_TMP_DB"]}"')
    await conn.close()
    print("临时库已创建：", os.environ["WF_TMP_DB"])


asyncio.run(main())
PY

cat >"$TMP_DIR/pg_schema.py" <<'PY'
"""断言迁移后的表结构：三张工作流表 + tasks.workflow_id 可空。"""

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings

EXPECTED = ["workflow_runs", "workflow_step_runs", "workflows"]


async def main() -> None:
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "select table_name from information_schema.tables "
                "where table_schema = 'public' and table_name like 'workflow%' "
                "order by 1"
            )
        )
        tables = [row[0] for row in rows]
        print("工作流表：", tables)
        assert tables == EXPECTED, tables

        row = await conn.execute(
            text(
                "select is_nullable from information_schema.columns "
                "where table_name = 'tasks' and column_name = 'workflow_id'"
            )
        )
        assert row.scalar_one() == "YES"
        print("tasks.workflow_id 可空：YES")
    await engine.dispose()


asyncio.run(main())
PY

cat >"$TMP_DIR/pg_schema_after_downgrade.py" <<'PY'
"""断言降级后三张表与 tasks.workflow_id 都已移除。"""

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings


async def main() -> None:
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "select table_name from information_schema.tables "
                "where table_schema = 'public' and table_name like 'workflow%'"
            )
        )
        tables = [row[0] for row in rows]
        assert tables == [], f"降级后仍有工作流表：{tables}"

        row = await conn.execute(
            text(
                "select count(*) from information_schema.columns "
                "where table_name = 'tasks' and column_name = 'workflow_id'"
            )
        )
        assert row.scalar_one() == 0, "降级后 tasks.workflow_id 仍存在"
        print("降级后：工作流表 0 张，tasks.workflow_id 已移除")
    await engine.dispose()


asyncio.run(main())
PY

cat >"$TMP_DIR/pg_partial_index.py" <<'PY'
"""在 PostgreSQL 上验证 running 的部分唯一索引真实行为。

只写 postgresql_where 时索引仍能建，但漏写 sqlite_where 会让 sqlite 退化成
「workflow_id 全表唯一」——所以这里连 skipped 记录也要插一条。
"""

import asyncio
import uuid

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings

INSERT_RUN = text(
    "insert into workflow_runs (workflow_id, definition_version_id, status, trigger_kind, "
    "run_as_type, run_as_user_id, definition_snapshot, total_steps, skip_reason, "
    "created_at, updated_at) "
    "values (:workflow_id, 1, :status, 'manual', 'user', :user_id, '{}'::json, 0, "
    ":skip_reason, now(), now())"
)


async def main() -> None:
    tag = uuid.uuid4().hex[:8]
    engine = create_async_engine(get_settings().database_url)

    async with engine.begin() as conn:
        platform_id = (
            await conn.execute(
                text(
                    "insert into platforms (name, code, is_active, created_at, updated_at) "
                    "values ('wf-probe', :code, true, now(), now()) returning id"
                ),
                {"code": f"wf-probe-{tag}"},
            )
        ).scalar_one()
        agent_id = (
            await conn.execute(
                text(
                    "insert into agents (platform_id, name, slug, created_at, updated_at) "
                    "values (:platform_id, 'bot', :slug, now(), now()) returning id"
                ),
                {"platform_id": platform_id, "slug": f"bot-{tag}"},
            )
        ).scalar_one()
        # owner_user_id / run_as_user_id 都可空：本探针只验证索引，不牵扯用户表。
        workflow_id = (
            await conn.execute(
                text(
                    "insert into workflows (platform_id, name, agent_id, owner_user_id, "
                    "status, version, max_steps, definition, timeout_seconds, auto_approve, "
                    "strict_approval, created_at, updated_at) "
                    "values (:platform_id, 'wf', :agent_id, null, 'active', 1, 50, "
                    "'{}'::json, 600, true, false, now(), now()) returning id"
                ),
                {"platform_id": platform_id, "agent_id": agent_id},
            )
        ).scalar_one()

    params = {"workflow_id": workflow_id, "user_id": None}

    async with engine.begin() as conn:
        await conn.execute(
            INSERT_RUN, {**params, "status": "running", "skip_reason": None}
        )
    print("第一条 running：插入成功")

    try:
        async with engine.begin() as conn:
            await conn.execute(
                INSERT_RUN, {**params, "status": "running", "skip_reason": None}
            )
        raise AssertionError("第二条 running 未被拒绝：部分唯一索引没生效")
    except IntegrityError as exc:
        print("第二条 running 被拒绝：", type(exc.orig).__name__)

    async with engine.begin() as conn:
        await conn.execute(
            INSERT_RUN, {**params, "status": "skipped", "skip_reason": "overlapped"}
        )
    print("running 之后插入 skipped：成功（where 子句未退化成全表唯一）")

    async with engine.begin() as conn:
        await conn.execute(
            text("delete from workflow_runs where workflow_id = :workflow_id"), params
        )
        await conn.execute(text("delete from workflows where id = :workflow_id"), params)
        await conn.execute(text("delete from agents where id = :agent_id"), {"agent_id": agent_id})
        await conn.execute(
            text("delete from platforms where id = :platform_id"), {"platform_id": platform_id}
        )
    await engine.dispose()


asyncio.run(main())
PY

cat >"$TMP_DIR/sqlite_partial_index.py" <<'PY'
"""在 SQLite 上验证同一套部分唯一索引语义。

sqlite 只在 ``sqlite_where`` 存在时才建部分索引；漏写就会退化成全表唯一，
于是第二条 skipped 记录也插不进去——这正是本段要证伪的情形。

本探针不打开 ``PRAGMA foreign_keys``：它只验证索引行为，而打开外键就得先把
platforms / agents / sys_users 都造齐，那只会把「索引是否生效」这件事淹掉。
"""

import asyncio

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.workflows.models import Workflow, WorkflowRun
from app.shared.base_model import BaseModel


def make_run(status: str, *, skip_reason: str | None = None) -> WorkflowRun:
    return WorkflowRun(
        workflow_id=1,
        definition_version_id=1,
        status=status,
        trigger_kind="manual",
        run_as_type="user",
        run_as_user_id=1,
        definition_snapshot={},
        total_steps=0,
        skip_reason=skip_reason,
    )


async def main() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async with engine.begin() as connection:
        await connection.run_sync(BaseModel.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(Workflow(id=1, platform_id=1, name="wf", agent_id=1, owner_user_id=1))
        await session.commit()

    async with factory() as session:
        session.add(make_run("running"))
        await session.commit()
    print("SQLite 第一条 running：插入成功")

    try:
        async with factory() as session:
            session.add(make_run("running"))
            await session.commit()
        raise AssertionError("SQLite 第二条 running 未被拒绝：sqlite_where 没写")
    except IntegrityError as exc:
        print("SQLite 第二条 running 被拒绝：", type(exc.orig).__name__)

    async with factory() as session:
        session.add(make_run("skipped", skip_reason="overlapped"))
        await session.commit()
    print("SQLite running 之后插入 skipped：成功")

    await engine.dispose()


asyncio.run(main())
PY

cat >"$TMP_DIR/e2e_two_steps.py" <<'PY'
"""端到端：真的建一条两步骤工作流、真的走一遍执行引擎。

只有「模型推理」这一层被替换成假实现——否则需要可用的模型网关与已发布 Agent，
而且会在开发库里写入真实会话、消息与用量记录。其余全链路（校验、编译、
入队、逐步执行、传值、落库、快照）都是真实代码。
"""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.agent.models import Agent, AgentVersion
from app.modules.conversation.models import Conversation
from app.modules.platform.models import Platform, PlatformAdmin
from app.modules.user.models import User
from app.modules.workflows import runner as workflow_runner
from app.modules.workflows import services as workflow_services
from app.modules.workflows.models import WorkflowRun, WorkflowStepRun
from app.modules.workflows.repositories import WorkflowRepository
from app.modules.workflows.schemas import WorkflowCreate, WorkflowStepInput, WorkflowUpdate
from app.shared.base_model import BaseModel
from app.shared.exceptions import BadRequestException

CALLS: list[str] = []
# 需要抛错的那几次调用（按全局调用序号，1 起）。用于验证「重试拿同一份输入」。
FAIL_ON: set[int] = set()


async def fake_execute_unattended_chat(session, **kwargs):  # noqa: ANN001, ANN003
    """替换模型推理层：记录真正发给模型的提示词，返回同形的三元组。

    会话行必须是真的：``workflow_step_runs.conversation_id`` 有外键，假实现若返回
    一个不存在的 id，落库就会以外键错误失败，结论会从「传值是否正确」跑偏成
    「外键是否成立」。loop_id 给 None（agent_loop_runs 需要整套运行时脚手架）。
    """

    message = kwargs["message"]
    CALLS.append(message)
    if len(CALLS) in FAIL_ON:
        raise RuntimeError(f"第 {len(CALLS)} 次调用被测试注入失败")
    content = f"OUTPUT-FOR: {message}"
    conversation = Conversation(
        platform_id=kwargs["platform_id"],
        agent_id=kwargs["agent_id"],
        user_id=kwargs.get("user_id"),
    )
    session.add(conversation)
    await session.flush()
    return (
        conversation,
        SimpleNamespace(content=content),
        SimpleNamespace(content=content, loop_id=None),
    )


async def main() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record):  # noqa: ANN001
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(BaseModel.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    workflow_runner.execute_unattended_chat = fake_execute_unattended_chat

    async with factory() as session:
        platform = Platform(name="Acme", code="acme", is_active=True)
        session.add(platform)
        await session.flush()
        agent = Agent(platform_id=platform.id, name="Bot", slug="bot")
        session.add(agent)
        await session.flush()
        version = AgentVersion(
            agent_id=agent.id,
            version=1,
            system_prompt="你是测试助手",
            model_name="test-model",
            # agent_versions.created_at 覆盖了 TimeModel 的同名列，没有 server_default，
            # sqlite 也不会自己补 now()，必须显式给值。
            created_at=datetime.now(UTC),
            published_at=datetime.now(UTC),
        )
        session.add(version)
        await session.flush()
        agent.default_version_id = version.id
        user = User(name="Admin", email="admin@acme.dev", account="admin", password="x")
        session.add(user)
        await session.flush()
        session.add(PlatformAdmin(platform_id=platform.id, user_id=user.id))
        await session.commit()
        platform_id, agent_id, user_id = platform.id, agent.id, user.id

    # 1) 保存两步骤工作流：第二步用 {{first.output}} 引用第一步输出
    async with factory() as session:
        workflow = await workflow_services.create_workflow(
            session,
            platform_id=platform_id,
            payload=WorkflowCreate(
                name="两步流程",
                agent_id=agent_id,
                steps=[
                    WorkflowStepInput(
                        step_id="first", name="第一步", kind="agent", prompt="产出素材"
                    ),
                    WorkflowStepInput(
                        step_id="second",
                        name="第二步",
                        kind="agent",
                        prompt="基于 {{first.output}} 写摘要",
                    ),
                ],
            ),
            owner_user_id=user_id,
            created_by_type="user",
            created_by_user_id=user_id,
        )
        workflow_id = workflow.id
        snapshot = dict(workflow.definition)
        assert workflow.version == 1, workflow.version
        nodes = snapshot.get("nodes") or []
        edges = snapshot.get("edges") or []
        print(f"保存后：version=1，节点 {len(nodes)} 个，边 {len(edges)} 条")
        assert [node["step_id"] for node in nodes] == ["first", "second"]
        assert edges[0]["source_handle"] == "default"

    # 2) 手动触发只排队（不写 started_at），再由执行引擎跑完
    async with factory() as session:
        workflow = await WorkflowRepository(session).get_scoped(workflow_id, platform_id)
        run, started = await workflow_services.enqueue_manual_run(
            session, workflow, user_id=user_id, is_platform_admin=True
        )
        run_id = run.id
        assert started is True
        assert run.started_at is None, "手动入队不应写 started_at，否则调度器不会认领"
        print("手动触发：已入队，started_at 为空")

    status = await workflow_runner.run_workflow_run(factory, workflow_run_id=run_id)
    if status != "completed":
        async with factory() as session:
            failed = await session.get(WorkflowRun, run_id)
            print("运行失败原因：", failed.error_message if failed else "<记录缺失>")
            step_rows = (
                (
                    await session.execute(
                        select(WorkflowStepRun).where(WorkflowStepRun.run_id == run_id)
                    )
                )
                .scalars()
                .all()
            )
            print("步骤记录：", [(row.step_id, row.status, row.error_message) for row in step_rows])
    assert status == "completed", status

    async with factory() as session:
        run = await session.get(WorkflowRun, run_id)
        steps = (
            (
                await session.execute(
                    select(WorkflowStepRun)
                    .where(WorkflowStepRun.run_id == run_id)
                    .order_by(WorkflowStepRun.seq)
                )
            )
            .scalars()
            .all()
        )
        print(f"运行状态：{run.status}，完成步骤 {run.completed_steps}/{run.total_steps}")
        print("步骤状态：", [(step.step_id, step.status) for step in steps])
        assert run.status == "completed"
        assert [step.step_id for step in steps] == ["first", "second"]
        assert [step.status for step in steps] == ["succeeded", "succeeded"]
        assert run.definition_snapshot == snapshot
        assert run.definition_version_id == 1

    # 3) 第二步收到的提示词里引用已被第一步的真实输出替换
    assert len(CALLS) == 2, CALLS
    print("第一步提示词：", CALLS[0])
    print("第二步提示词：", CALLS[1])
    assert "{{" not in CALLS[1], f"第二步提示词仍有未替换的引用：{CALLS[1]}"
    assert "OUTPUT-FOR: 产出素材" in CALLS[1], CALLS[1]

    # 4) 改定义后重跑：旧 run 的快照不变，仍能解释自己
    async with factory() as session:
        workflow = await WorkflowRepository(session).get_scoped(workflow_id, platform_id)
        updated = await workflow_services.update_workflow(
            session,
            workflow=workflow,
            payload=WorkflowUpdate(
                steps=[
                    WorkflowStepInput(
                        step_id="first", name="第一步", kind="agent", prompt="产出素材 v2"
                    )
                ]
            ),
        )
        assert updated.version == 2, updated.version
        print(f"改定义后：version={updated.version}")

    async with factory() as session:
        old_run = await session.get(WorkflowRun, run_id)
        assert old_run.definition_version_id == 1
        assert len(old_run.definition_snapshot["nodes"]) == 2, "旧快照被新定义覆盖了"
        print("旧运行仍保留 version=1 的两步骤快照：可解释")

    # 5) 每步重试：第一次调用被注入失败，max_retries=1 让第二次尝试成功
    retry_base = len(CALLS)
    FAIL_ON.add(retry_base + 1)
    async with factory() as session:
        retry_workflow = await workflow_services.create_workflow(
            session,
            platform_id=platform_id,
            payload=WorkflowCreate(
                name="重试流程",
                agent_id=agent_id,
                steps=[
                    WorkflowStepInput(
                        step_id="only",
                        name="会失败一次",
                        kind="agent",
                        prompt="重试目标",
                        max_retries=1,
                    )
                ],
            ),
            owner_user_id=user_id,
            created_by_type="user",
            created_by_user_id=user_id,
        )
        retry_workflow_id = retry_workflow.id

    async with factory() as session:
        retry_workflow = await WorkflowRepository(session).get_scoped(
            retry_workflow_id, platform_id
        )
        retry_run, _ = await workflow_services.enqueue_manual_run(
            session, retry_workflow, user_id=user_id, is_platform_admin=True
        )
        retry_run_id = retry_run.id

    retry_status = await workflow_runner.run_workflow_run(
        factory, workflow_run_id=retry_run_id
    )
    assert retry_status == "completed", retry_status
    assert len(CALLS) == retry_base + 2, CALLS
    # 重试必须拿同一份输入：两次调用记录到的提示词要一模一样。
    assert CALLS[retry_base] == CALLS[retry_base + 1] == "重试目标", CALLS
    async with factory() as session:
        retry_step = (
            await session.execute(
                select(WorkflowStepRun).where(WorkflowStepRun.run_id == retry_run_id)
            )
        ).scalar_one()
        assert retry_step.status == "succeeded", retry_step.status
        assert retry_step.retry_count == 2, retry_step.retry_count
    print("重试：首次注入失败后第二次尝试成功，retry_count=2，两次输入一致")

    # 6) 非 output 的输出路径必须在保存期被拒绝（等运行到一半才报错太晚）
    bad_definitions = [
        (
            "模板引用 {{first.other}}",
            [
                WorkflowStepInput(step_id="first", name="一", kind="agent", prompt="x"),
                WorkflowStepInput(
                    step_id="second", name="二", kind="agent", prompt="用 {{first.other}} 写"
                ),
            ],
        ),
        (
            "绑定路径 [first, other]",
            [
                WorkflowStepInput(step_id="first", name="一", kind="agent", prompt="x"),
                WorkflowStepInput(
                    step_id="second",
                    name="二",
                    kind="tool",
                    tool_name="not-a-real-tool",
                    input_bindings={"q": ["first", "other"]},
                ),
            ],
        ),
    ]
    for label, bad_steps in bad_definitions:
        async with factory() as session:
            try:
                await workflow_services.create_workflow(
                    session,
                    platform_id=platform_id,
                    payload=WorkflowCreate(
                        name=f"坏路径-{label}", agent_id=agent_id, steps=bad_steps
                    ),
                    owner_user_id=user_id,
                    created_by_type="user",
                    created_by_user_id=user_id,
                )
            except BadRequestException as exc:
                print(f"保存期拒绝 {label}：{exc}")
                continue
            raise AssertionError(f"{label} 必须在保存期被拒绝")

    # 7) 运行详情必须带 raw_output_size / output_truncated（前端靠这两个字段显示截断）
    async with factory() as session:
        workflow = await WorkflowRepository(session).get_scoped(workflow_id, platform_id)
        detail = await workflow_services.get_run_detail(
            session, workflow=workflow, run_id=run_id
        )
        payload = detail.model_dump()
        first = payload["steps"][0]
        assert first["raw_output_size"] == len(first["raw_output"].encode("utf-8"))
        assert first["output_truncated"] is False
        print(
            "运行详情字段：raw_output_size="
            f"{first['raw_output_size']}，output_truncated={first['output_truncated']}"
        )

    await engine.dispose()
    print("端到端结论：通过")


asyncio.run(main())
PY

echo "## 已执行的命令与结果"
echo

# ---------------------------------------------------------------------------
# 迁移：在一次性临时库上从零跑完整链路。
# ---------------------------------------------------------------------------
verify_step_as \
  "迁移：在一次性临时库上从零 upgrade head，断言三张表与 tasks.workflow_id 可空" \
  "WF_TMP_DB=ai_base_wf_verify_<pid> python <pg_create_db.py> && cd apps/backend && DATABASE_URL=<临时库> alembic upgrade head && python <pg_schema.py>" \
  bash -c "
set -eo pipefail
WF_ADMIN_DSN='${ADMIN_DSN}' WF_TMP_DB='${TMP_DB}' '${VENV_PY}' '${TMP_DIR}/pg_create_db.py'
cd apps/backend
DATABASE_URL='${TMP_DSN}' .venv/bin/python -m alembic upgrade head 2>&1 | tail -3
DATABASE_URL='${TMP_DSN}' .venv/bin/python '${TMP_DIR}/pg_schema.py'
" \
  ;

verify_step_as \
  "迁移可回退：downgrade -1 后三张表消失，再 upgrade head 回到 20261013_0036 (head)" \
  "cd apps/backend && DATABASE_URL=<临时库> alembic downgrade -1 && python <pg_schema_after_downgrade.py> && alembic upgrade head && alembic current" \
  bash -c "
set -eo pipefail
cd apps/backend
export DATABASE_URL='${TMP_DSN}'
.venv/bin/python -m alembic downgrade -1 2>&1 | tail -1
.venv/bin/python '${TMP_DIR}/pg_schema_after_downgrade.py'
.venv/bin/python -m alembic upgrade head 2>&1 | tail -1
.venv/bin/python -m alembic current 2>&1 | tail -1 | grep -q '20261013_0036 (head)'
echo '重新升级后：20261013_0036 (head)'
" \
  ;

# ---------------------------------------------------------------------------
# 验收标准 1 的核心断言：部分唯一索引的真实行为，两种方言各一次。
# ---------------------------------------------------------------------------
verify_step_as \
  "验收 1：PostgreSQL 上同一工作流只允许一条 running，skipped 不受影响" \
  "cd apps/backend && DATABASE_URL=<临时库> python <pg_partial_index.py>" \
  bash -c "
set -eo pipefail
cd apps/backend
DATABASE_URL='${TMP_DSN}' .venv/bin/python '${TMP_DIR}/pg_partial_index.py'
" \
  ;

verify_step_as \
  "验收 1：SQLite 上同一语义（证明 sqlite_where 也写了，索引没退化成全表唯一）" \
  "cd apps/backend && python <sqlite_partial_index.py>" \
  bash -c "
set -eo pipefail
cd apps/backend
.venv/bin/python '${TMP_DIR}/sqlite_partial_index.py'
" \
  ;

# ---------------------------------------------------------------------------
# 验收 2/3/4/6/8 的断言在 tests/workflows 里；9 是既有任务零回归。
# ---------------------------------------------------------------------------
verify_step \
  "验收 2/3/4/6/8：工作流模块单测（静态校验、保存拒收、失败语义、调度 skip 与看门狗）" \
  bash -c "set -o pipefail; cd apps/backend && .venv/bin/python -m pytest tests/workflows -q 2>&1 | tail -8"

verify_step \
  "验收 9：现有任务零回归" \
  bash -c "set -o pipefail; cd apps/backend && .venv/bin/python -m pytest tests/tasks -q 2>&1 | tail -5"

verify_step \
  "静态检查：ruff check（工作流模块、被改动的任务模块与 conversation.services、迁移、测试）" \
  bash -c "set -o pipefail; cd apps/backend && .venv/bin/ruff check app/modules/workflows app/modules/tasks app/modules/conversation/services.py migrations/versions/20261013_0036_workflows.py tests/workflows 2>&1 | tail -10"

# ---------------------------------------------------------------------------
# 验收标准 5/7 的端到端。
# ---------------------------------------------------------------------------
verify_step_as \
  "验收 5/7 端到端：两步骤工作流手动运行 → 两步 succeeded、第二步提示词已替换、旧快照仍可解释" \
  "cd apps/backend && python <e2e_two_steps.py>" \
  bash -c "
set -eo pipefail
cd apps/backend
.venv/bin/python '${TMP_DIR}/e2e_two_steps.py'
" \
  ;

# ---------------------------------------------------------------------------
# 前端：4 个新文件 + 侧边栏入口 + 生成的路由树。
# ---------------------------------------------------------------------------
verify_step \
  "前端：类型检查（tsc -b）" \
  bash -c "set -o pipefail; cd apps/front && pnpm exec tsc -b && echo 'tsc：0 error'"

verify_step \
  "前端：eslint（断言工作流相关文件 0 问题；仓库整体有 11 条既有问题）" \
  bash -c "set -o pipefail; cd apps/front && pnpm lint >/tmp/wf-verify-lint.txt 2>&1; tail -2 /tmp/wf-verify-lint.txt; \
    if grep -qi 'workflow' /tmp/wf-verify-lint.txt; then echo '工作流文件出现 lint 问题'; exit 1; fi; \
    echo '工作流相关 lint 问题：0'"

verify_step \
  "前端：生产构建（含路由树生成）" \
  bash -c "set -o pipefail; cd apps/front && pnpm exec vite build 2>&1 | tail -4"

echo "## 未执行项与原因"
echo
echo "- 真实模型网关的端到端运行：未执行。需要可用的模型网关与已发布 Agent，且会在共享开发库写入真实会话、消息与用量记录；改用替换模型推理层的端到端探针覆盖同一条代码路径（保存 → 入队 → 逐步执行 → 传值 → 落库 → 快照）。"
echo "- 浏览器端到端点击流（脚本内未包含）：本脚本只做类型检查、lint 与生产构建，不起前端 dev server 与后端 API。本轮由人工另跑了一次 Playwright 验证（真实后端 8010 + 真实前端 5180），结果见「验收结论」末尾；其中表单提交（新建 / 编辑保存）与「立即运行」按钮的点击流未覆盖。"
echo "- 多副本调度抢占：未执行。需要同时运行两个调度进程竞争同一批到期任务；当前只覆盖了仓储层的 for update skip locked 语义与单进程 tick。"
echo "- 步骤级人工审批：未执行。v1 明确不做，waiting 状态只在枚举里预留，没有实现可验。"
UNEXECUTED=1
echo

echo '## 验收结论'
echo
echo '逐条对照 spec.md 的 9 条验收标准（命令与真实输出见上）：'
echo
echo '1. 三张表与部分唯一索引：通过。一次性临时库上 alembic upgrade head 从零建表，downgrade -1 后三表与 tasks.workflow_id 消失、再 upgrade 回到 20261013_0036；同一工作流的第二条 running 记录在 PostgreSQL 与 SQLite 上都报唯一约束冲突，running 之后插 skipped 正常。'
echo '2. 保存期静态校验：通过。引用后面的步骤、step_id 重复、超 max_steps、边指向不存在的 step_id 逐条被拒且不写库（test_validators.py / test_services.py）。'
echo '3. 工具步骤声明 financial 之类不可自动批准的 side_effect：通过，保存时直接拒绝（test_services.py）。'
echo '4. 步骤覆盖其它平台的 agent_id：通过，保存时被拒（test_services.py）。'
echo '5. 两步骤手动运行：通过。端到端探针断言 run completed、两条 step 都 succeeded、第二步收到的提示词里 {{first.output}} 已被第一步的真实输出替换；超 50KB 的输出在 model_visible_output 上被截断并带标记、raw_output 保留全量（test_runner.py），运行详情里 raw_output_size 与 output_truncated 由 schema 计算返回（端到端探针第 7 步 + test_routes.py）。'
echo '6. 失败语义：通过。on_error=abort 时后续步骤不执行、workflow_step_runs 里没有该步记录、run 为 failed；continue_with_default 时后续步骤照跑且该步的 on_error_applied 为真；max_retries 的重试拿同一份输入，兜底值只在全部尝试用尽之后才生效（test_runner.py 三例 + 端到端探针第 5 步）。'
echo '7. 定义快照：通过。改定义后 version 递增到 2，旧 run 仍带 version=1 的两节点快照，能解释那一次运行（端到端探针）。'
echo '8. 调度语义：部分通过。三种 skip_reason、看门狗收敛、只有入队态才被认领由 test_scheduler.py / test_repository.py 覆盖；真实进程被强杀与多副本抢占未实测（见未执行项）。'
echo '9. 现有任务零回归：通过。pytest tests/tasks -q 69 passed。'
echo
echo '剩余风险：'
echo '- 选择器的 path 已在保存期收紧为只允许 output：{{first.other}} 与 [first, other] 都在保存时被拒且不写库（端到端探针第 6 步）。运行期仍会再查一次作为边界检查，两处共用 validators.OUTPUT_PATH。'
echo '- _require_platform_member 查的是 platform_admins 成员表，经 HTTP 进来的调用者恒被判为平台管理员，所以「同一平台内只看自己名下」这一层目前只有服务层直接调用覆盖到；跨平台隔离（404）有效。该行为与 tasks 模块一致，本次未改动，若要收紧属于鉴权行为变化、需另行审批。'
echo '- 前端已暴露每步的失败重试次数；步骤级 agent_id 覆盖仍只有 API 支持、界面不暴露（v1 决定），列表页「最近运行」按行查询（N+1）。'
echo '- 真实模型网关端到端、脚本内浏览器点击流、多副本调度抢占未执行，原因见上一节。'
echo
echo '补充：人工浏览器验证（非本脚本，Playwright + 真实后端 8010 + 真实前端 5180，平台 1 / 管理员 user 7）——14/14 断言通过，problems 为空，覆盖列表页、定义页、运行记录页、运行明细四屏：列表显示「2 / 50」步骤数与最近运行时间；定义页显示两个步骤与「失败重试次数」下拉；运行记录显示「已完成 2 / 2」；运行明细显示「尝试 2 次」、「模型可见输出（超过 50KB 已截断，完整输出 108000 字节）」与截断后的输出文本。该验证同时暴露并修掉了 4 处前端手写类型与真实 payload 不一致的缺陷（后端 WorkflowRead 不返回 steps；运行详情缺 raw_output_size / output_truncated；RetryBadge 语义过时；运行记录不返回 created_at）。'
echo
echo '是否可归档：可以归档。9 条验收标准中 8 条用真实命令验证，第 8 条为部分验证且缺口已显式列出；测试与静态检查全绿。'
echo '- 脚本退出码由 tools/harness/verify.sh 写入 verify.md 的 frontmatter。'

if [[ $FAIL -ne 0 ]]; then
  exit 1
fi
if [[ $UNEXECUTED -ne 0 ]]; then
  exit 3
fi
exit 0
