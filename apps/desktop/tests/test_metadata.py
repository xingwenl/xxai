"""元数据抓取器测试：SSRF 防护、三级抓取链、图标下载与 SVG 消毒。"""

from __future__ import annotations

import pytest

import desktop_app.metadata as metadata
from desktop_app.metadata import (
    MAX_ICON_SIZE,
    MetadataError,
    fetch_icon,
    fetch_site_metadata,
    preflight_frameable,
    sanitize_svg,
    validate_fetchable_url,
)


class FakeResponse:
    """模拟 urllib HTTPResponse：支持切片式 read 与大小写不敏感头读取。"""

    def __init__(self, status: int = 200, headers: dict | None = None, body: bytes = b"", url: str = "") -> None:
        self._status = status
        self.headers = headers or {}
        self._body = body
        self._url = url

    def getcode(self) -> int:
        return self._status

    def geturl(self) -> str:
        return self._url

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            return self._body
        chunk = self._body[:n]
        self._body = self._body[n:]
        return chunk


def make_fetcher(routes: dict[tuple[str, str], FakeResponse | Exception]):
    """构造注入用 fetcher：按键 (method, url) 返回响应或抛异常，未命中返回 404。"""

    def fetcher(request, timeout: float | None = None):  # noqa: ARG001
        key = (request.get_method(), request.full_url)
        hit = routes.get(key)
        if hit is None:
            return FakeResponse(404, url=request.full_url)
        if isinstance(hit, Exception):
            raise hit
        # 真实 urllib 每次请求返回独立响应对象；这里克隆避免响应体被消费后复用
        return FakeResponse(hit._status, dict(hit.headers), bytes(hit._body), hit._url)

    return fetcher


HTML_OG = (
    "<html><head><title>Fallback Title</title>"
    '<meta property="og:title" content="OG Site"/>'
    '<meta property="og:description" content="OG 描述"/>'
    '<meta property="og:image" content="https://93.184.216.34/og.png"/>'
    '<link rel="icon" href="/favicon.ico"/></head><body></body></html>'
)


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch: pytest.MonkeyPatch):
    """测试默认禁用真实网络：仅注入的 fake fetcher 可用。"""
    monkeypatch.setattr(metadata, "_urlopen", make_fetcher({}))


# ---------- SSRF 防护 ----------


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://0.0.0.0/",
        "http://224.0.0.1/",
        "http://240.0.0.1/",
        "ftp://93.184.216.34/",
        "https://user:pass@93.184.216.34/",
        "https:///missing-host",
    ],
)
def test_validate_public_url_rejects(url: str) -> None:
    with pytest.raises(MetadataError):
        validate_fetchable_url(url)


def test_validate_public_url_accepts_public_ip() -> None:
    assert validate_fetchable_url("https://93.184.216.34/page") == "https://93.184.216.34/page"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:3000/",
        "http://localhost:3000/",
        "http://[::1]:3000/",
        "http://192.168.1.10/",
        "http://10.0.0.5:8080/",
        "http://172.16.0.1/",
    ],
)
def test_validate_public_url_accepts_local(url: str) -> None:
    """桌面应用本机场景：回环与私有网段地址允许作为插件 URL。"""
    assert validate_fetchable_url(url) == url


# ---------- 抓取链 ----------


def test_fetch_og_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    fetcher = make_fetcher({
        ("GET", "https://93.184.216.34/"): FakeResponse(
            headers={"Content-Type": "text/html"}, body=HTML_OG.encode(), url="https://93.184.216.34/"
        ),
        ("GET", "https://93.184.216.34/og.png"): FakeResponse(
            headers={"Content-Type": "image/png"}, body=b"\x89PNG", url="https://93.184.216.34/og.png"
        ),
    })
    monkeypatch.setattr(metadata, "_urlopen", fetcher)
    meta = fetch_site_metadata("https://93.184.216.34/")
    assert meta.name == "OG Site"
    assert meta.description == "OG 描述"
    assert meta.icon_bytes == b"\x89PNG"
    assert meta.icon_ext == "png"


def test_fetch_manifest_takes_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    html = (
        '<html><head><link rel="manifest" href="/manifest.json"/>'
        "<title>Page Title</title></head></html>"
    )
    manifest = (
        '{"name": "Manifest App", "description": "来自 manifest", '
        '"icons": [{"src": "/icon.png", "sizes": "512x512", "type": "image/png"}]}'
    )
    fetcher = make_fetcher({
        ("GET", "https://93.184.216.34/"): FakeResponse(body=html.encode(), url="https://93.184.216.34/"),
        ("GET", "https://93.184.216.34/manifest.json"): FakeResponse(
            headers={"Content-Type": "application/manifest+json"},
            body=manifest.encode(),
            url="https://93.184.216.34/manifest.json",
        ),
        ("GET", "https://93.184.216.34/icon.png"): FakeResponse(
            headers={"Content-Type": "image/png"}, body=b"icon", url="https://93.184.216.34/icon.png"
        ),
    })
    monkeypatch.setattr(metadata, "_urlopen", fetcher)
    meta = fetch_site_metadata("https://93.184.216.34/")
    assert meta.name == "Manifest App"
    assert meta.description == "来自 manifest"
    assert meta.icon_ext == "png"


def test_fetch_title_fallback_without_icon(monkeypatch: pytest.MonkeyPatch) -> None:
    html = "<html><head><title>仅标题站点</title></head></html>"
    fetcher = make_fetcher({
        ("GET", "https://93.184.216.34/"): FakeResponse(body=html.encode(), url="https://93.184.216.34/"),
        ("GET", "https://93.184.216.34/favicon.ico"): FakeResponse(404),
    })
    monkeypatch.setattr(metadata, "_urlopen", fetcher)
    meta = fetch_site_metadata("https://93.184.216.34/")
    assert meta.name == "仅标题站点"
    assert meta.icon_bytes is None


def test_fetch_failure_raises_metadata_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fetcher = make_fetcher({
        ("GET", "https://93.184.216.34/"): FakeResponse(500),
    })
    monkeypatch.setattr(metadata, "_urlopen", fetcher)
    with pytest.raises(MetadataError, match="非 200"):
        fetch_site_metadata("https://93.184.216.34/")


# ---------- 图标下载与消毒 ----------


def test_fetch_icon_svg_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    evil_svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)">'
        "<script>alert(2)</script>"
        '<a href="javascript:alert(3)"><rect width="10"/></a>'
        "</svg>"
    )
    fetcher = make_fetcher({
        ("GET", "https://93.184.216.34/icon.svg"): FakeResponse(
            headers={"Content-Type": "image/svg+xml"}, body=evil_svg.encode(), url="https://93.184.216.34/icon.svg"
        ),
    })
    monkeypatch.setattr(metadata, "_urlopen", fetcher)
    data, ext = fetch_icon("https://93.184.216.34/icon.svg")
    assert ext == "svg"
    cleaned = data.decode()
    assert "script" not in cleaned.lower()
    assert "onload" not in cleaned.lower()
    assert "javascript:" not in cleaned.lower()


def test_sanitize_svg_standalone() -> None:
    cleaned = sanitize_svg(b'<svg xmlns="x"><script>bad()</script><rect onload="x" width="1"/></svg>')
    text = cleaned.decode()
    assert "script" not in text
    assert "onload" not in text
    assert "<rect" in text


def test_fetch_icon_rejects_oversize(monkeypatch: pytest.MonkeyPatch) -> None:
    fetcher = make_fetcher({
        ("GET", "https://93.184.216.34/big.png"): FakeResponse(
            headers={"Content-Type": "image/png"}, body=b"x" * (MAX_ICON_SIZE + 1)
        ),
    })
    monkeypatch.setattr(metadata, "_urlopen", fetcher)
    with pytest.raises(MetadataError, match="大小限制"):
        fetch_icon("https://93.184.216.34/big.png")


def test_fetch_icon_rejects_non_image(monkeypatch: pytest.MonkeyPatch) -> None:
    fetcher = make_fetcher({
        ("GET", "https://93.184.216.34/not-an-image"): FakeResponse(
            headers={"Content-Type": "text/html"}, body=b"<html>"
        ),
    })
    monkeypatch.setattr(metadata, "_urlopen", fetcher)
    with pytest.raises(MetadataError, match="不是图片"):
        fetch_icon("https://93.184.216.34/not-an-image")


# ---------- 嵌入性预检 ----------


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"X-Frame-Options": "DENY"}, False),
        ({"X-Frame-Options": "SAMEORIGIN"}, False),
        ({"Content-Security-Policy": "frame-ancestors 'none'"}, False),
        ({"Content-Security-Policy": "frame-ancestors 'self'"}, False),
        ({"Content-Security-Policy": "frame-ancestors *"}, True),
        ({"Content-Security-Policy": "default-src 'self'; frame-ancestors https://a.example"}, False),
        ({}, True),
    ],
)
def test_preflight_frameable(monkeypatch: pytest.MonkeyPatch, headers: dict, expected: bool) -> None:
    fetcher = make_fetcher({
        ("HEAD", "https://93.184.216.34/"): FakeResponse(headers=headers, url="https://93.184.216.34/"),
    })
    monkeypatch.setattr(metadata, "_urlopen", fetcher)
    assert preflight_frameable("https://93.184.216.34/") is expected


def test_preflight_head_unsupported_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    fetcher = make_fetcher({
        ("HEAD", "https://93.184.216.34/"): FakeResponse(405),
    })
    monkeypatch.setattr(metadata, "_urlopen", fetcher)
    assert preflight_frameable("https://93.184.216.34/") is None


def test_preflight_non_200_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    fetcher = make_fetcher({
        ("HEAD", "https://93.184.216.34/"): FakeResponse(500),
    })
    monkeypatch.setattr(metadata, "_urlopen", fetcher)
    assert preflight_frameable("https://93.184.216.34/") is None
