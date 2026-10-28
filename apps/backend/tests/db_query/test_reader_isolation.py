"""agent_reader 只读角色与平台行级策略的**真库**验证。

与其他单测不同，这里的结论只可能来自真实 PostgreSQL：RLS 的可见集、
只读事务的拒绝、角色级 GUC 的默认值，都没有办法在 sqlite 或 mock 上验证。

未配置 ``DATABASE_READER_URL`` 时整体 skip——CI 与本地未开通只读连接串的环境
不应因此变红；``tools/harness/verify/2026-10-27-db-query-skill.sh`` 会临时给
角色开一个密码并注入该变量，把这几条真正跑一遍。
"""

from __future__ import annotations

import asyncio
import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings

READER_URL = os.getenv("DATABASE_READER_URL", "").strip()
ROOT_URL = os.getenv("DATABASE_URL", "").strip() or get_settings().database_url

pytestmark = pytest.mark.skipif(
    not READER_URL,
    reason="未配置 DATABASE_READER_URL，跳过真库隔离测试",
)


async def _root_scalars(sql: str, params: dict | None = None) -> list:
    engine = create_async_engine(ROOT_URL, pool_size=1)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text(sql), params or {})
            return list(result.scalars().all())
    finally:
        await engine.dispose()


async def _reader_scalar(platform_id: int | None, sql: str, params: dict | None = None):
    """以 agent_reader 执行一条查询；platform_id 为 None 时**故意不设租户 GUC**。"""
    engine = create_async_engine(READER_URL, pool_size=1)
    try:
        async with engine.connect() as conn:
            async with conn.begin():
                if platform_id is not None:
                    # 用 SET LOCAL 写租户 GUC，而不是 set_config：迁移把 set_config
                    # 从 PUBLIC 收回，只读角色调用会被数据库直接拒绝（防越权）
                    await conn.execute(
                        text(f"SET LOCAL app.platform_id = '{int(platform_id)}'")
                    )
                return (await conn.execute(text(sql), params or {})).scalar()
    finally:
        await engine.dispose()


def _two_platform_ids() -> list[int]:
    ids = asyncio.run(
        _root_scalars(
            "select platform_id from conversations "
            "where platform_id is not null group by platform_id order by platform_id limit 2"
        )
    )
    return [int(i) for i in ids]


def test_reader_only_sees_its_own_platform():
    ids = _two_platform_ids()
    if len(ids) < 2:
        pytest.skip("库里不足两个平台，无法验证跨平台隔离")
    for pid in ids:
        expected = int(
            asyncio.run(
                _root_scalars(
                    "select count(*) from conversations where platform_id = :pid",
                    {"pid": pid},
                )
            )[0]
        )
        actual = asyncio.run(_reader_scalar(pid, "select count(*) from conversations"))
        assert actual == expected, f"平台 {pid} 的会话数不一致：reader={actual} root={expected}"


def test_platforms_table_follows_tenant_context():
    ids = _two_platform_ids()
    if not ids:
        pytest.skip("库里没有带会话的平台")
    pid = ids[0]
    assert asyncio.run(_reader_scalar(pid, "select count(*) from platforms where id = :pid", {"pid": pid})) == 1
    if len(ids) >= 2:
        # 另一个平台的行不可见，说明 platforms 的谓词走的是 id 而不是「全部可见」
        assert asyncio.run(_reader_scalar(pid, "select count(*) from platforms where id = :pid", {"pid": ids[1]})) == 0


def test_reader_without_tenant_context_sees_nothing():
    # current_setting(..., true) 在变量缺失时是 NULL，谓词为假 → 0 行而不是报错
    assert asyncio.run(_reader_scalar(None, "select count(*) from conversations")) == 0


def test_reader_cannot_write():
    engine_url = READER_URL

    async def attempt():
        engine = create_async_engine(engine_url, pool_size=1)
        try:
            async with engine.connect() as conn:
                async with conn.begin():
                    await conn.execute(text("SET LOCAL app.platform_id = '1'"))
                    await conn.execute(text("update conversations set updated_at = now()"))
        finally:
            await engine.dispose()

    with pytest.raises(DBAPIError):
        asyncio.run(attempt())


def test_reader_cannot_change_tenant_context():
    """越权回归：模型 SQL 不能通过 set_config 改写租户 GUC 去读别的平台。"""

    async def attempt():
        engine = create_async_engine(READER_URL, pool_size=1)
        try:
            async with engine.connect() as conn:
                async with conn.begin():
                    await conn.execute(text("SET LOCAL app.platform_id = '1'"))
                    await conn.execute(
                        text("select set_config('app.platform_id', '2', true)")
                    )
        finally:
            await engine.dispose()

    with pytest.raises(DBAPIError) as excinfo:
        asyncio.run(attempt())
    assert "set_config" in str(excinfo.value)


def test_global_tables_are_not_readable():
    # sys_users 含密码哈希，迁移里刻意不给策略：RLS 开启 + 无策略 = 默认拒绝
    assert asyncio.run(_reader_scalar(1, "select count(*) from sys_users")) == 0


def test_child_table_follows_parent_tenant():
    ids = _two_platform_ids()
    if len(ids) < 2:
        pytest.skip("库里不足两个平台，无法验证子表隔离")
    pid = ids[0]
    expected = int(
        asyncio.run(
            _root_scalars(
                "select count(*) from conversation_messages m "
                "join conversations c on c.id = m.conversation_id "
                "where c.platform_id = :pid",
                {"pid": pid},
            )
        )[0]
    )
    actual = asyncio.run(_reader_scalar(pid, "select count(*) from conversation_messages"))
    assert actual == expected


def test_two_hop_table_follows_parent_tenant():
    ids = _two_platform_ids()
    if not ids:
        pytest.skip("库里没有带会话的平台")
    pid = ids[0]
    expected = int(
        asyncio.run(
            _root_scalars(
                "select count(*) from agent_loop_steps s "
                "join agent_loop_runs r on r.id = s.loop_run_id "
                "join conversations c on c.id = r.conversation_id "
                "where c.platform_id = :pid",
                {"pid": pid},
            )
        )[0]
    )
    actual = asyncio.run(_reader_scalar(pid, "select count(*) from agent_loop_steps"))
    assert actual == expected
