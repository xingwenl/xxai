from app.modules.agent_runtime.error_codes import ErrorCode
from app.shared.exceptions import AppException, BadRequestException, register_exception_handlers
from app.shared.responses import ResponseMeta, error_response, success_response


def test_success_response_uses_fixed_envelope() -> None:
    response = success_response(data={"id": 1}, message="created")

    assert response.success is True
    assert response.message == "created"
    assert response.data == {"id": 1}
    assert response.meta is None
    # 成功响应不带业务错误码。
    assert response.error_code is None


def test_success_response_supports_meta() -> None:
    meta = ResponseMeta(request_id="req-1")
    response = success_response(data={"ok": True}, meta=meta)

    assert response.meta is not None
    assert response.meta.request_id == "req-1"


def test_error_response_carries_business_error_code_alongside_http_code() -> None:
    """``code`` 仍是 HTTP 状态码，业务码走新增的 ``error_code``，两者并存。"""

    response = error_response(
        message="对话模型不可用",
        code=409,
        error_code=ErrorCode.CHAT_MODEL_UNAVAILABLE,
    )

    assert response.success is False
    assert response.code == 409
    assert response.error_code == "chat_model_unavailable"


def test_error_response_defaults_to_null_error_code() -> None:
    response = error_response(message="boom", code=500)

    assert response.error_code is None


def test_app_exception_keeps_error_code_for_the_rest_handler() -> None:
    exc = AppException("x", status_code=409, error_code=ErrorCode.CHAT_MODEL_UNAVAILABLE)

    assert exc.error_code == "chat_model_unavailable"
    assert exc.status_code == 409


def test_app_exception_defaults_to_no_error_code() -> None:
    assert BadRequestException("bad").error_code is None


def test_exception_handler_serializes_error_code():
    """REST 兜底 handler 必须把 error_code 透出，否则非流式通路仍拿不到稳定码。"""

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom() -> None:
        raise AppException(
            "对话模型不可用",
            status_code=409,
            error_code=ErrorCode.CHAT_MODEL_UNAVAILABLE,
        )

    response = TestClient(app).get("/boom")

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == 409
    assert body["error_code"] == "chat_model_unavailable"
    assert body["success"] is False

