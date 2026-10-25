"""内嵌 FastAPI 服务的端口选择。

正式启动与打包态都必须监听固定端口 8765：AI Base 的 Embed Client 用
`allowed_origins` 对页面 origin 做精确匹配（校验点见
apps/backend/app/modules/embed/services.py），而桌面助手（ai-sdk 智能体）
挂载前要用 `window.location.origin` 换发短期 token。若沿用系统随机端口，
origin 永远不在白名单里，换 token 返回 401 `origin is not allowed`，
助手会静默不挂载（只在控制台留一行 warn）。
"""

from __future__ import annotations

import socket
from collections.abc import Callable

# 与 front/vite.config.ts 的 dev 代理、scripts/configure_ai_base.py 的
# DEFAULT_ORIGINS、chrome 扩展 manifest 的 host_permissions 保持一致
DEFAULT_API_PORT = 8765


def port_is_free(host: str, port: int) -> bool:
    """探测本机端口是否还能绑定（用于决定要不要退回系统分配端口）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


def resolve_api_port(
    env_value: str | None = None,
    dev_front: bool = False,
    check_free: Callable[[int], bool] | None = None,
) -> int:
    """决定内嵌服务监听端口，返回 0 表示交给系统分配。

    - 显式 `DESKTOP_API_PORT` 一律照用：配错就启动失败，不静默漂移到别的端口
    - 开发态（`DESKTOP_DEV_FRONT=1`）固定 8765：Vite 代理写死该端口，漂移即断
    - 正式/打包态优先 8765；已被占用（同一台机器开着另一个宿主）才退回随机端口，
      此时助手连不上，由调用方在日志里说明原因
    """
    if env_value:
        return int(env_value)
    if dev_front:
        return DEFAULT_API_PORT
    free = check_free or (lambda p: port_is_free("127.0.0.1", p))
    return DEFAULT_API_PORT if free(DEFAULT_API_PORT) else 0
