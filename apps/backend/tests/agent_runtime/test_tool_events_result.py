from app.modules.agent_runtime.tool_events import tool_result_content


def test_builtin_result_has_larger_but_bounded_context_limit():
    tool = type("Tool", (), {"kind": "builtin"})()
    outcome = type("Outcome", (), {"result": {"value": "x" * 120_000}})()

    assert len(tool_result_content(tool, outcome)) <= 100_000


def test_failed_outcome_without_result_renders_error_summary():
    """只有 error 没有 result 的失败工具结果，文本回填必须包含失败原因。"""

    tool = type("Tool", (), {"kind": "host_tool"})()
    outcome = type(
        "Outcome",
        (),
        {
            "status": "failed",
            "result": None,
            "error": {
                "code": "tool_not_found",
                "message": "工具 ghost 未注册",
            },
        },
    )()

    content = tool_result_content(tool, outcome)

    assert "tool_not_found" in content
    assert "工具 ghost 未注册" in content
    assert "None" != content
