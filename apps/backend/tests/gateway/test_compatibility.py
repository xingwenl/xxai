from app.modules.gateway.auth import (
    SUPPORTED_PROTOCOL_VERSION,
    check_client_compatibility,
)


def test_current_protocol_and_sdk_are_accepted():
    result = check_client_compatibility(protocol_version=1, sdk_version="0.1.0")

    assert result.allowed is True


def test_unknown_protocol_major_is_rejected_before_authentication():
    result = check_client_compatibility(protocol_version=2, sdk_version="0.1.0")

    assert result.allowed is False
    assert result.code == "unsupported_protocol_version"
    assert result.retryable is False
    assert SUPPORTED_PROTOCOL_VERSION == 1


def test_old_sdk_is_rejected_with_stable_code():
    result = check_client_compatibility(protocol_version=1, sdk_version="0.0.1")

    assert result.allowed is False
    assert result.code == "unsupported_sdk_version"
