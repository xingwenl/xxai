from app.shared.responses import ResponseMeta, success_response


def test_success_response_uses_fixed_envelope() -> None:
    response = success_response(data={"id": 1}, message="created")

    assert response.success is True
    assert response.message == "created"
    assert response.data == {"id": 1}
    assert response.meta is None


def test_success_response_supports_meta() -> None:
    meta = ResponseMeta(request_id="req-1")
    response = success_response(data={"ok": True}, meta=meta)

    assert response.meta is not None
    assert response.meta.request_id == "req-1"
