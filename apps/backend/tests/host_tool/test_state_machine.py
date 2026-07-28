from app.modules.host_tool.services import redact_sensitive, validate_arguments


def test_sensitive_fields_are_redacted_recursively():
    assert redact_sensitive({"token": "secret", "items": [{"password": "x", "ok": 1}]}) == {
        "token": "[REDACTED]",
        "items": [{"password": "[REDACTED]", "ok": 1}],
    }


def test_json_schema_rejects_wrong_tool_arguments():
    try:
        validate_arguments({"type": "object", "required": ["orderId"]}, {})
    except ValueError as error:
        assert str(error) == "host tool arguments are invalid"
    else:
        raise AssertionError("expected schema validation failure")
