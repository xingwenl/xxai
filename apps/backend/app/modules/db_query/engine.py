"""只读查库引擎：与业务主引擎隔离的独立连接池。

池子刻意开得很小（默认 pool_size=2、max_overflow=0）：Agent 查库是低频旁路，
不应与业务请求争抢数据库连接。未配置 ``DATABASE_READER_URL`` 时返回 None，
上层据此返回 ``db_reader_not_configured``，而不是让整个应用启动失败。
"""

from __future__ import annotations

import asyncpg
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_reader_engine: AsyncEngine | None = None


class _NoJitProbeConnection(asyncpg.Connection):
    """关闭 JIT 能力探测的 asyncpg 连接（只读查库专用）。

    背景：asyncpg 在首次做类型内省时会先执行
    ``SELECT current_setting('jit'), set_config('jit','off',false)``
    （``asyncpg/connection.py`` 的 ``_introspect_types``，只要服务端版本 >= 11
    就会触发）。本项目的只读角色刻意被收回 ``set_config`` 执行权（迁移
    20261027_0047：防止模型 SQL 用 set_config 改写租户 GUC 越过行级安全），
    于是一旦需要类型内省（数组、pgvector 等非内置映射类型），查询会以
    ``permission denied for function set_config`` 失败——这会把合法的只读查询
    也一起误伤。

    这里把连接能力里的 jit 标记清掉，让 asyncpg 跳过那段探测：只读查询用不到
    JIT（本来也是短小的取数语句），跳过没有副作用。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        caps = getattr(self, "_server_caps", None)
        if caps is not None and getattr(caps, "jit", False):
            self._server_caps = caps._replace(jit=False)


def get_reader_engine() -> AsyncEngine | None:
    """返回只读查库引擎；未配置 reader 连接串时返回 None（懒初始化）。"""
    global _reader_engine

    if _reader_engine is not None:
        return _reader_engine

    settings = get_settings()
    url = (settings.database_reader_url or "").strip()
    if not url:
        return None

    try:
        _reader_engine = create_async_engine(
            url,
            pool_size=settings.db_query_pool_size,
            # 不允许溢出连接：查库慢时宁可排队/超时，也不挤占业务连接数
            max_overflow=0,
            # 取连接前 ping 一次，避免拿到已被数据库断开的空闲连接
            pool_pre_ping=True,
            # 见 _NoJitProbeConnection：跳过会调用 set_config 的 JIT 能力探测
            connect_args={"connection_class": _NoJitProbeConnection},
        )
    except Exception as exc:  # noqa: BLE001 - 连接串写错是配置问题，不能把框架异常抛给模型
        # 最常见的是漏写驱动前缀（``postgresql://`` 而不是 ``postgresql+asyncpg://``）。
        # 这里收口成 None，让工具层统一返回 db_reader_not_configured：只有管理员改配置
        # 才能修好，模型重试没有意义，也不该看到 create_async_engine 的原始异常。
        logger.warning(
            "只读查库引擎初始化失败（连接串非法，按未配置处理） error=%s detail=%s",
            type(exc).__name__,
            exc,
        )
        return None

    logger.info("只读查库引擎已初始化 pool_size=%s", settings.db_query_pool_size)
    return _reader_engine

async def dispose_reader_engine() -> None:
    """释放只读引擎连接池（应用关闭时调用）。"""
    global _reader_engine

    if _reader_engine is not None:
        await _reader_engine.dispose()

    _reader_engine = None
