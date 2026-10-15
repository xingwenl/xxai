"""技能来源导入的两个新路由：注册情况、鉴权与响应契约（不依赖数据库）。"""

from __future__ import annotations

import asyncio

from app.modules.platform.repositories import PlatformRepository
from app.modules.skill import router as skill_router
from app.modules.skill.schemas import (
    SkillSourceImportRequest,
    SkillSourcePreviewRequest,
)
from app.shared.exceptions import NotFoundException
from main import app

PREVIEW_PATH = "/api/v1/platforms/{platform_id}/skill-packages/source-skills"
IMPORT_PATH = "/api/v1/platforms/{platform_id}/skill-packages/import-source"


class FakeCurrentUser:
    id = 7


def test_skill_source_routes_are_registered() -> None:
    paths = app.openapi()["paths"]

    assert PREVIEW_PATH in paths
    assert IMPORT_PATH in paths
    assert "post" in paths[PREVIEW_PATH]
    assert "post" in paths[IMPORT_PATH]


def test_skill_source_routes_require_bearer_authentication() -> None:
    openapi = app.openapi()["paths"]

    assert openapi[PREVIEW_PATH]["post"]["security"] == [{"HTTPBearer": []}]
    assert openapi[IMPORT_PATH]["post"]["security"] == [{"HTTPBearer": []}]


def test_import_source_route_returns_201() -> None:
    operation = app.openapi()["paths"][IMPORT_PATH]["post"]

    assert "201" in operation["responses"]


def test_preview_route_takes_platform_id_as_path_parameter() -> None:
    """platform_id 必须是路径参数——它决定走哪个平台的鉴权校验。"""
    operation = app.openapi()["paths"][PREVIEW_PATH]["post"]

    parameters = {item["name"]: item["in"] for item in operation.get("parameters", [])}
    assert parameters["platform_id"] == "path"


def test_non_platform_admin_is_rejected_before_any_source_work(
    monkeypatch,
) -> None:
    """非本平台管理员两个接口都应 404，且不会触碰解析器（即零出网）。"""

    async def no_platform(self, platform_id: int, user_id: int):
        return None

    monkeypatch.setattr(PlatformRepository, "get_by_id_for_user", no_platform)

    touched: list[str] = []

    async def fake_preview(source: str):
        touched.append(source)
        raise AssertionError("非管理员不应触发来源解析")

    async def fake_import(repository, platform_id: int, payload):
        touched.append(payload.source)
        raise AssertionError("非管理员不应触发来源导入")

    monkeypatch.setattr(skill_router, "preview_source_skills", fake_preview)
    monkeypatch.setattr(skill_router, "import_skill_package_from_source", fake_import)

    async def run() -> None:
        for coroutine in (
            skill_router.preview_skill_source_endpoint(
                platform_id=1,
                payload=SkillSourcePreviewRequest(source="travisjneuman/.claude"),
                current_user=FakeCurrentUser(),
                session=None,
            ),
            skill_router.import_skill_source_endpoint(
                platform_id=1,
                payload=SkillSourceImportRequest(
                    source="travisjneuman/.claude", skills=["agent-cli-developer"]
                ),
                current_user=FakeCurrentUser(),
                session=None,
            ),
        ):
            try:
                await coroutine
            except NotFoundException as exc:
                assert exc.status_code == 404
            else:
                raise AssertionError("非本平台管理员应当收到 404")

    asyncio.run(run())
    assert touched == []
