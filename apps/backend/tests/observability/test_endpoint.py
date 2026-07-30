from fastapi.testclient import TestClient

from app import create_app


def test_metrics_endpoint_returns_prometheus_text():
    with TestClient(create_app()) as client:
        response = client.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "agent_gateway_" in response.text
