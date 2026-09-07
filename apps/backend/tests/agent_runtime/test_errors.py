from app.modules.agent_runtime.errors import cancellation_error, error_from_exception


def test_cancellation_has_stable_retryable_payload():
    payload = cancellation_error().as_payload()

    assert payload == {
        "code": "agent_request_cancelled",
        "message": "Agent 请求已取消",
        "retryable": True,
        "details": {},
    }


def test_connection_errors_are_retryable_but_unknown_errors_are_not():
    assert error_from_exception(TimeoutError()).retryable is True
    assert error_from_exception(ValueError("bad input")).retryable is False


def test_http_5xx_is_upstream_unavailable_and_retryable():
    error = error_from_exception(RuntimeError("HTTP 502 Bad Gateway"))

    assert error.code == "agent_upstream_unavailable"
    assert error.retryable is True
    assert error.details == {"statusCode": "502", "exceptionType": "RuntimeError"}


def test_status_code_attribute_is_used_for_classification():
    class ProviderFailure(RuntimeError):
        def __init__(self):
            super().__init__("upstream failed")
            self.status_code = 503

    error = error_from_exception(ProviderFailure())

    assert error.code == "agent_upstream_unavailable"
    assert error.retryable is True
    assert error.details["statusCode"] == "503"


def test_context_length_exceeded_is_not_retryable():
    error = error_from_exception(
        RuntimeError("This model's maximum context length is 128000 tokens")
    )

    assert error.code == "context_length_exceeded"
    assert error.retryable is False


def test_client_errors_are_not_retryable_and_do_not_leak_message():
    class AuthFailure(RuntimeError):
        def __init__(self):
            super().__init__("secret-token invalid authentication")
            self.status_code = 401

    error = error_from_exception(AuthFailure())

    assert error.code == "agent_request_failed"
    assert error.retryable is False
    assert "secret-token" not in str(error.details)
