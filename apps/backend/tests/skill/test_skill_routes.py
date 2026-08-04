from main import app
from app.modules.skill.schemas import SkillPackageUpdate


def test_skill_management_routes_are_registered() -> None:
    paths = app.openapi()["paths"]

    assert "/api/v1/platforms/{platform_id}/skills" in paths
    assert "/api/v1/platforms/{platform_id}/skills/import" in paths
    assert "/api/v1/platforms/{platform_id}/skill-packages" in paths
    assert "/api/v1/platforms/{platform_id}/skill-packages/{package_id}" in paths
    assert "/api/v1/platforms/{platform_id}/skill-script-executions" in paths
    assert "/api/v1/platforms/{platform_id}/skills/{skill_id}" in paths
    assert "/api/v1/platforms/{platform_id}/agents/{agent_id}/skills" in paths
    assert (
        "/api/v1/platforms/{platform_id}/agents/{agent_id}/skills/{skill_id}"
        in paths
    )
    assert "get" in paths["/api/v1/platforms/{platform_id}/skills"]
    assert "post" in paths["/api/v1/platforms/{platform_id}/skills/import"]
    assert "get" in paths["/api/v1/platforms/{platform_id}/skill-packages"]
    assert "patch" in paths["/api/v1/platforms/{platform_id}/skill-packages/{package_id}"]
    assert "get" in paths[
        "/api/v1/platforms/{platform_id}/skill-script-executions"
    ]
    assert "patch" in paths["/api/v1/platforms/{platform_id}/skills/{skill_id}"]
    assert "delete" in paths["/api/v1/platforms/{platform_id}/skills/{skill_id}"]
    assert "delete" in paths[
        "/api/v1/platforms/{platform_id}/agents/{agent_id}/skills/{skill_id}"
    ]


def test_skill_management_routes_require_bearer_authentication() -> None:
    openapi = app.openapi()

    assert openapi["paths"]["/api/v1/platforms/{platform_id}/skills"]["get"][
        "security"
    ] == [{"HTTPBearer": []}]
    assert openapi["paths"]["/api/v1/platforms/{platform_id}/skills/import"][
        "post"
    ]["security"] == [{"HTTPBearer": []}]
    assert openapi["paths"][
        "/api/v1/platforms/{platform_id}/skill-script-executions"
    ]["get"]["security"] == [{"HTTPBearer": []}]


def test_skill_package_update_accepts_boolean_false() -> None:
    assert SkillPackageUpdate(allow_script_execution=False).model_dump(
        exclude_unset=True
    ) == {"allow_script_execution": False}
