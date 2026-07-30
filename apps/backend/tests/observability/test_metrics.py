from app.modules.observability.metrics import (
    METRIC_LABELS,
    metrics_payload,
    record_authentication,
    record_quota_rejection,
)


def test_metrics_have_only_low_cardinality_labels_and_expose_samples():
    assert "request_id" not in METRIC_LABELS
    assert "conversation_id" not in METRIC_LABELS
    assert "external_user_id" not in METRIC_LABELS
    assert "token" not in METRIC_LABELS

    record_authentication("success")
    record_quota_rejection("message", "quota_exceeded")
    payload = metrics_payload()

    assert "agent_gateway_authentication_total" in payload
    assert 'result="success"' in payload
    assert "agent_gateway_quota_rejections_total" in payload
    assert 'resource="message"' in payload
