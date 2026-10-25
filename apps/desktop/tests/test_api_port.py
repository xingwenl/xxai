"""内嵌服务端口选择测试。

打包态必须固定监听 8765：AI Base 的 Embed Client 按 allowed_origins 精确匹配
页面 origin，随机端口会导致换 token 401 origin is not allowed，助手静默不显示。
"""

from __future__ import annotations

import socket

from desktop_app.api_port import DEFAULT_API_PORT, port_is_free, resolve_api_port


def test_default_port_matches_embed_allowlist() -> None:
    """8765 是 configure_ai_base.py / Vite 代理 / Chrome 扩展硬编码的约定端口。"""
    assert DEFAULT_API_PORT == 8765


def test_packaged_mode_prefers_default_port() -> None:
    """打包态（非 dev_front）端口空闲时必须落到 8765，而不是交给系统分配。"""
    assert resolve_api_port(None, False, lambda port: True) == DEFAULT_API_PORT


def test_packaged_mode_falls_back_when_default_port_busy() -> None:
    """端口被另一个宿主占用时退回 0（系统分配），保证第二个窗口仍能打开。"""
    probed: list[int] = []

    def _busy(port: int) -> bool:
        probed.append(port)
        return False

    assert resolve_api_port(None, False, _busy) == 0
    assert probed == [DEFAULT_API_PORT]


def test_dev_front_is_pinned_even_if_busy() -> None:
    """开发态不能漂移：Vite 代理写死 8765，绑不上就该启动失败而不是换端口。"""
    assert resolve_api_port(None, True, lambda port: False) == DEFAULT_API_PORT


def test_explicit_env_override_wins() -> None:
    """显式 DESKTOP_API_PORT 优先于一切默认值（配错由启动失败暴露）。"""
    assert resolve_api_port("9123", False, lambda port: True) == 9123
    assert resolve_api_port("9123", True, lambda port: False) == 9123


def test_port_is_free_detects_listening_socket() -> None:
    """port_is_free 要能识别已被监听（LISTEN）的端口。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        taken = int(listener.getsockname()[1])
        assert port_is_free("127.0.0.1", taken) is False

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        released = int(probe.getsockname()[1])
    assert port_is_free("127.0.0.1", released) is True
