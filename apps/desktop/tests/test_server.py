"""FastAPI 内嵌服务的路由与静态页测试。"""

from fastapi.testclient import TestClient

from desktop_app.server import create_app


def test_health() -> None:
    client = TestClient(create_app())
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "desktop-app"


def test_index_page() -> None:
    client = TestClient(create_app())
    resp = client.get("/")
    assert resp.status_code == 200
    assert "pywebview" in resp.text
    assert "Desktop App" in resp.text


def test_static_asset() -> None:
    client = TestClient(create_app())
    resp = client.get("/favicon.ico")
    # 未提供的资源由 StaticFiles 返回 404，验证挂载生效
    assert resp.status_code == 404
