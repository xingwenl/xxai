"""任务接口注册与鉴权测试。

沿用仓库既有范式：路由级测试只读 ``app.openapi()`` 断言路径与安全声明，
不真实发请求；业务规则由 service 层测试覆盖。
"""

from __future__ import annotations

from main import app

PREFIX = "/api/v1/platforms/{platform_id}/tasks"


def test_task_routes_are_registered() -> None:
    """七个接口全部注册在平台作用域前缀下。"""

    paths = app.openapi()["paths"]
    assert PREFIX in paths
    assert f"{PREFIX}/{{task_id}}" in paths
    assert f"{PREFIX}/{{task_id}}/run" in paths
    assert f"{PREFIX}/{{task_id}}/runs" in paths

    assert set(paths[PREFIX]) == {"get", "post"}
    assert set(paths[f"{PREFIX}/{{task_id}}"]) == {"get", "patch", "delete"}
    assert set(paths[f"{PREFIX}/{{task_id}}/run"]) == {"post"}
    assert set(paths[f"{PREFIX}/{{task_id}}/runs"]) == {"get"}


def test_task_routes_require_bearer_authentication() -> None:
    """全部接口都要求 Bearer 鉴权，不对外开放匿名访问。"""

    openapi = app.openapi()
    paths = openapi["paths"]
    for path in (
        PREFIX,
        f"{PREFIX}/{{task_id}}",
        f"{PREFIX}/{{task_id}}/run",
        f"{PREFIX}/{{task_id}}/runs",
    ):
        for method, operation in paths[path].items():
            assert operation["security"] == [{"HTTPBearer": []}], (
                f"{method.upper()} {path} 必须要求 Bearer 鉴权"
            )


def test_create_task_returns_201() -> None:
    """创建任务返回 201，与仓库其他创建接口一致。"""

    operation = app.openapi()["paths"][PREFIX]["post"]
    assert "201" in operation["responses"]


def test_task_create_schema_does_not_accept_owner() -> None:
    """创建请求不接受归属字段，避免越权把任务挂到别人名下。"""

    schemas = app.openapi()["components"]["schemas"]
    props = schemas["TaskCreate"]["properties"]
    assert "owner_user_id" not in props
    assert "run_as_user_id" not in props
    assert "created_by_type" not in props


def test_task_read_schema_exposes_required_fields() -> None:
    """响应模型暴露前端需要的字段，包括下次运行时间与执行身份。"""

    schemas = app.openapi()["components"]["schemas"]
    props = schemas["TaskRead"]["properties"]
    for field in (
        "id",
        "platform_id",
        "agent_id",
        "owner_user_id",
        "name",
        "prompt",
        "trigger_type",
        "cron_expression",
        "run_at",
        "timezone",
        "status",
        "next_run_at",
        "last_run_at",
        "created_by_type",
        "run_as_type",
        "auto_approve",
        "strict_approval",
        "timeout_seconds",
    ):
        assert field in props, f"TaskRead 缺少字段 {field}"


def test_task_run_read_schema_exposes_traceability_fields() -> None:
    """执行记录暴露可追溯字段：会话、运行记录、跳过原因与自动批准次数。"""

    schemas = app.openapi()["components"]["schemas"]
    props = schemas["TaskRunRead"]["properties"]
    for field in (
        "id",
        "task_id",
        "status",
        "trigger_kind",
        "planned_at",
        "started_at",
        "finished_at",
        "conversation_id",
        "agent_loop_run_id",
        "error_message",
        "skip_reason",
        "auto_approved_count",
    ):
        assert field in props, f"TaskRunRead 缺少字段 {field}"


def test_run_detail_endpoint_is_registered() -> None:
    """执行过程详情接口已注册且要求鉴权。"""

    openapi = app.openapi()
    path = f"{PREFIX}/{{task_id}}/runs/{{run_id}}/detail"
    assert path in openapi["paths"]
    assert "get" in openapi["paths"][path]
    assert openapi["paths"][path]["get"]["security"] == [{"HTTPBearer": []}]


def test_run_detail_schema_exposes_steps() -> None:
    """详情响应暴露步骤清单与每步的过程字段。"""

    schemas = app.openapi()["components"]["schemas"]
    detail = schemas["TaskRunDetail"]["properties"]
    for field in ("run", "loop_id", "loop_status", "loop_summary", "steps"):
        assert field in detail, f"TaskRunDetail 缺少字段 {field}"

    step = schemas["TaskRunStepRead"]["properties"]
    for field in (
        "sequence",
        "step_type",
        "title",
        "status",
        "output_summary",
        "thinking_text",
        "tool_name",
        "skill_name",
        "error",
    ):
        assert field in step, f"TaskRunStepRead 缺少字段 {field}"
