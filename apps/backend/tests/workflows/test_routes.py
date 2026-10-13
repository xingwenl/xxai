"""工作流 HTTP 接口的用例（spec 验收第 2、4、5 条的路由面）。

仓库既有的路由测试只读 ``app.openapi()`` 断言路径注册，不建测试 app、也不覆盖
依赖（见 ``tests/tasks/test_task_routes.py``）。那套写法断言不到状态码、响应外壳
与请求体注入，所以这里用 ``httpx.ASGITransport`` 走真实路由 + 覆盖
``get_db_session`` / ``require_current_active_user``——lifespan 不会被
ASGITransport 触发，不覆盖 ``get_db_session`` 会去连真实数据库。

响应外壳是 ``{"success", "message", "data", "meta", "code"}``：成功 ``code=0``，
失败走全局异常处理器，``code`` 即 HTTP 状态码、``success=false``。
"""

from __future__ import annotations

import asyncio
import contextlib
from types import SimpleNamespace

import httpx
from main import app

from app.core.database import get_db_session
from app.core.security import require_current_active_user
from app.modules.platform.models import PlatformAdmin
from app.modules.workflows import services, validators
from app.modules.workflows.repositories import WorkflowStepRunRepository
from app.modules.workflows.schemas import WorkflowCreate
from helpers import agent_step, make_session, seed


def _prefix(platform_id: int) -> str:
    return f"/api/v1/platforms/{platform_id}/workflows"


def _payload(agent_id: int, *, name: str = "接口工作流", steps=None, **overrides) -> dict:
    data = {
        "name": name,
        "agent_id": agent_id,
        "description": None,
        "steps": steps if steps is not None else [agent_step("first")],
        "max_steps": 50,
        "timeout_seconds": 600,
        "auto_approve": True,
        "strict_approval": False,
    }
    data.update(overrides)
    return data


@contextlib.asynccontextmanager
async def _client(session_factory, user_id: int):
    """以 ``user_id`` 的身份访问测试 app，退出时清理依赖覆盖。"""

    async def override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[require_current_active_user] = lambda: SimpleNamespace(
        id=user_id, is_active=True
    )
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


async def _direct_workflow(session, meta, *, name="直建工作流", steps=None, **overrides):
    """不经过 HTTP 直接落一条工作流，供详情/删除/运行类用例做前置数据。"""

    payload = WorkflowCreate(
        name=name,
        agent_id=meta.agent.id,
        steps=[agent_step("first")] if steps is None else steps,
        **overrides,
    )
    return await services.create_workflow(
        session,
        platform_id=meta.platform.id,
        payload=payload,
        owner_user_id=meta.member.id,
        created_by_user_id=meta.member.id,
    )


def test_list_workflows_envelope_and_items() -> None:
    """锁：列表接口 200、外壳 code=0，data 里带分页字段与创建出来的工作流。"""

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                workflow = await _direct_workflow(session, meta, name="列表里的工作流")
                await session.commit()
                platform_id, user_id, workflow_id = (
                    meta.platform.id,
                    meta.admin.id,
                    workflow.id,
                )

            async with _client(session_factory, user_id) as client:
                response = await client.get(_prefix(platform_id))
                assert response.status_code == 200
                body = response.json()
                assert body["code"] == 0
                assert body["success"] is True
                assert body["message"] == "workflows listed"
                data = body["data"]
                assert (data["page_no"], data["page_size"], data["total"]) == (1, 20, 1)
                assert [item["id"] for item in data["items"]] == [workflow_id]
                assert data["items"][0]["name"] == "列表里的工作流"
                assert data["items"][0]["version"] == 1
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_create_workflow_returns_201_and_ignores_injected_fields() -> None:
    """锁（验收 2、4）：创建 201；``workflow_id`` / ``owner_user_id`` / ``platform_id``
    不允许由请求体注入——归属与平台取自路径与当前用户，否则任何人都能把工作流
    挂到别人的名下或别的平台。"""

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                other = await seed(session)
                await session.commit()
                platform_id = meta.platform.id
                user_id = meta.member.id
                agent_id = meta.agent.id
                foreign_user_id = other.member.id
                foreign_platform_id = other.platform.id

            payload = _payload(
                agent_id,
                name="注入尝试",
                workflow_id=987654,
                owner_user_id=foreign_user_id,
                platform_id=foreign_platform_id,
                created_by_user_id=foreign_user_id,
            )

            async with _client(session_factory, user_id) as client:
                response = await client.post(_prefix(platform_id), json=payload)
                assert response.status_code == 201
                body = response.json()
                assert body["code"] == 0
                assert body["message"] == "workflow created"
                data = body["data"]
                assert data["id"] != 987654
                assert data["platform_id"] == platform_id
                # 归属与创建人都来自 current_user，不是请求体。
                assert data["owner_user_id"] == user_id
                assert data["created_by_user_id"] == user_id
                assert data["name"] == "注入尝试"
                assert data["version"] == 1
                assert data["status"] == "active"
                assert [node["step_id"] for node in data["definition"]["nodes"]] == [
                    "first"
                ]
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_get_detail_returns_workflow_and_404_across_platforms() -> None:
    """锁：详情 200 带关键字段；跨平台取不到，按「不存在」回答 404。"""

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                other = await seed(session)
                # 让当前用户同时是另一个平台的成员：平台作用域检查会放行，
                # 这样才能单独验证「工作流不属于该平台 → workflow not found」。
                session.add(
                    PlatformAdmin(platform_id=other.platform.id, user_id=meta.admin.id)
                )
                workflow = await _direct_workflow(session, meta, name="详情工作流")
                await session.commit()
                platform_id = meta.platform.id
                user_id = meta.admin.id
                workflow_id = workflow.id
                foreign_platform_id = other.platform.id

            async with _client(session_factory, user_id) as client:
                response = await client.get(f"{_prefix(platform_id)}/{workflow_id}")
                assert response.status_code == 200
                body = response.json()
                assert body["code"] == 0
                assert body["message"] == "workflow detail"
                assert body["data"]["id"] == workflow_id
                assert body["data"]["name"] == "详情工作流"

                # 同一个 id 放到别的平台前缀下：按不存在回答。
                cross = await client.get(
                    f"{_prefix(foreign_platform_id)}/{workflow_id}"
                )
                assert cross.status_code == 404
                assert cross.json()["code"] == 404
                assert cross.json()["success"] is False
                assert cross.json()["message"] == "workflow not found"
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_update_workflow_bumps_version_when_definition_saved() -> None:
    """锁（ADR 版本语义）：PATCH 只改名字不动版本；传 steps 保存新定义则 version+1。"""

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                workflow = await _direct_workflow(session, meta, name="旧名字")
                await session.commit()
                platform_id, user_id, workflow_id = (
                    meta.platform.id,
                    meta.admin.id,
                    workflow.id,
                )

            async with _client(session_factory, user_id) as client:
                renamed = await client.patch(
                    f"{_prefix(platform_id)}/{workflow_id}",
                    json={"name": "新名字"},
                )
                assert renamed.status_code == 200
                assert renamed.json()["message"] == "workflow updated"
                assert renamed.json()["data"]["name"] == "新名字"
                assert renamed.json()["data"]["version"] == 1

                saved = await client.patch(
                    f"{_prefix(platform_id)}/{workflow_id}",
                    json={"steps": [agent_step("renamed")]},
                )
                assert saved.status_code == 200
                assert saved.json()["data"]["version"] == 2
                assert [
                    node["step_id"]
                    for node in saved.json()["data"]["definition"]["nodes"]
                ] == ["renamed"]

                paused = await client.patch(
                    f"{_prefix(platform_id)}/{workflow_id}",
                    json={"status": "paused"},
                )
                assert paused.status_code == 200
                assert paused.json()["data"]["status"] == "paused"
                assert paused.json()["data"]["version"] == 2
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_delete_workflow_returns_deleted_flag_and_then_404() -> None:
    """锁：删除返回 ``data={"deleted": id}``，之后再取同一 id 是 404。"""

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                workflow = await _direct_workflow(session, meta)
                await session.commit()
                platform_id, user_id, workflow_id = (
                    meta.platform.id,
                    meta.admin.id,
                    workflow.id,
                )

            async with _client(session_factory, user_id) as client:
                response = await client.delete(f"{_prefix(platform_id)}/{workflow_id}")
                assert response.status_code == 200
                assert response.json()["message"] == "workflow deleted"
                assert response.json()["data"] == {"deleted": workflow_id}

                gone = await client.get(f"{_prefix(platform_id)}/{workflow_id}")
                assert gone.status_code == 404
                assert gone.json()["message"] == "workflow not found"
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_manual_run_accepts_then_reports_overlap() -> None:
    """锁（验收 5）：手动运行接口只排队（run.status=running、started_at 为空）并回
    「已开始执行」；已有 running 时第二次回「已跳过」且 skip_reason=overlapped。"""

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                workflow = await _direct_workflow(
                    session, meta, steps=[agent_step("first"), agent_step("second")]
                )
                await session.commit()
                platform_id, user_id, workflow_id = (
                    meta.platform.id,
                    meta.admin.id,
                    workflow.id,
                )

            async with _client(session_factory, user_id) as client:
                first = await client.post(f"{_prefix(platform_id)}/{workflow_id}/run")
                assert first.status_code == 200
                assert first.json()["message"] == "已开始执行"
                data = first.json()["data"]
                assert data["message"] == "已开始执行"
                assert data["run"]["status"] == "running"
                assert data["run"]["started_at"] is None
                assert data["run"]["trigger_kind"] == "manual"
                assert data["run"]["total_steps"] == 2

                second = await client.post(f"{_prefix(platform_id)}/{workflow_id}/run")
                assert second.status_code == 200
                assert second.json()["message"] == "该工作流正在运行，本次已跳过"
                assert second.json()["data"]["run"]["status"] == "skipped"
                assert second.json()["data"]["run"]["skip_reason"] == "overlapped"
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_list_runs_and_run_detail() -> None:
    """锁：运行列表与运行详情两个端点都能读到已排队的运行，
    详情额外带 ``definition_snapshot`` 与 ``steps`` 数组。"""

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                workflow = await _direct_workflow(session, meta)
                await session.commit()
                platform_id, user_id, workflow_id = (
                    meta.platform.id,
                    meta.admin.id,
                    workflow.id,
                )

            async with _client(session_factory, user_id) as client:
                created = await client.post(f"{_prefix(platform_id)}/{workflow_id}/run")
                run_id = created.json()["data"]["run"]["id"]

                listed = await client.get(f"{_prefix(platform_id)}/{workflow_id}/runs")
                assert listed.status_code == 200
                assert listed.json()["message"] == "workflow runs listed"
                assert listed.json()["data"]["total"] == 1
                assert [item["id"] for item in listed.json()["data"]["items"]] == [
                    run_id
                ]

                detail = await client.get(
                    f"{_prefix(platform_id)}/{workflow_id}/runs/{run_id}"
                )
                assert detail.status_code == 200
                assert detail.json()["message"] == "workflow run detail"
                assert detail.json()["data"]["run"]["id"] == run_id
                assert detail.json()["data"]["definition_snapshot"]["nodes"][0][
                    "step_id"
                ] == "first"
                assert detail.json()["data"]["steps"] == []

                # 运行属于另一个工作流时按不存在回答。
                other = await _direct_workflow(session, meta, name="另一个工作流")
                await session.commit()
                crossed = await client.get(
                    f"{_prefix(platform_id)}/{other.id}/runs/{run_id}"
                )
                assert crossed.status_code == 404
                assert crossed.json()["message"] == "workflow run not found"
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_run_detail_exposes_computed_output_size_fields() -> None:
    """锁：运行详情的 JSON 里必须带 ``raw_output_size`` / ``output_truncated``。

    前端靠这两个字段显示「已截断 + 完整多少字节」。它们由 schema 计算得出
    （不落库），一旦改名或漏序列化，界面只会显示 undefined——而类型检查看不出来，
    因为前端接口层的类型是手写的。
    """

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                workflow = await _direct_workflow(session, meta)
                await session.commit()
                platform_id, user_id, workflow_id = (
                    meta.platform.id,
                    meta.admin.id,
                    workflow.id,
                )

            long_text = "字" * (validators.MAX_VISIBLE_OUTPUT_BYTES // 3 + 100)
            visible = validators.truncate_output(long_text)

            async with _client(session_factory, user_id) as client:
                created = await client.post(f"{_prefix(platform_id)}/{workflow_id}/run")
                run_id = created.json()["data"]["run"]["id"]

                # 直接落一条「已截断」的步骤记录，再按接口读回来。
                async with session_factory() as session:
                    repo = WorkflowStepRunRepository(session)
                    step = await repo.create_step_run(
                        run_id=run_id, step_id="first", seq=0, node_type="agent"
                    )
                    await repo.finish_step_run(
                        step,
                        status="succeeded",
                        model_visible_output=visible,
                        raw_output=long_text,
                        retry_count=1,
                    )
                    await session.commit()

                detail = await client.get(
                    f"{_prefix(platform_id)}/{workflow_id}/runs/{run_id}"
                )
                assert detail.status_code == 200
                step_payload = detail.json()["data"]["steps"][0]
                assert step_payload["raw_output_size"] == len(
                    long_text.encode("utf-8")
                )
                assert step_payload["output_truncated"] is True
                assert step_payload["model_visible_output"] == visible
                assert step_payload["retry_count"] == 1
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_non_platform_member_gets_404() -> None:
    """锁：非本平台成员访问平台作用域下的任何端点都按「平台不存在」回答 404。"""

    async def run() -> None:
        engine, session_factory = await make_session()
        try:
            async with session_factory() as session:
                meta = await seed(session)
                other = await seed(session)
                workflow = await _direct_workflow(session, meta)
                await session.commit()
                # other.member 只是 other 平台的成员，不属于 meta.platform。
                platform_id = meta.platform.id
                outsider_id = other.member.id
                workflow_id = workflow.id

            async with _client(session_factory, outsider_id) as client:
                listed = await client.get(_prefix(platform_id))
                assert listed.status_code == 404
                assert listed.json()["code"] == 404
                assert listed.json()["message"] == "platform not found"

                detail = await client.get(f"{_prefix(platform_id)}/{workflow_id}")
                assert detail.status_code == 404
                assert detail.json()["message"] == "platform not found"
        finally:
            await engine.dispose()

    asyncio.run(run())
