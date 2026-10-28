"""db_query 工具层的错误码收口：连接层失败必须归到 db_reader_not_configured。

密码轮换、角色被收回 LOGIN、库没起都会在连接阶段失败，和「SQL 写错了」不是一类问题：
前者重试没有意义（要管理员改配置），后者才该让模型改 SQL。这条边界靠
``_is_reader_connection_error`` 判定，这里用真实的 asyncpg 异常类型覆盖它。
"""

from __future__ import annotations

import asyncpg
import pytest

from app.modules.tools.business.db_query import _is_reader_connection_error


@pytest.mark.parametrize(
    "error",
    [
        asyncpg.InvalidPasswordError("password authentication failed"),
        asyncpg.InvalidAuthorizationSpecificationError("role cannot log in"),
        asyncpg.InvalidCatalogNameError("database does not exist"),
        ConnectionRefusedError("connection refused"),
    ],
)
def test_connection_failures_are_reader_configuration_problems(error):
    assert _is_reader_connection_error(error) is True


@pytest.mark.parametrize(
    "error",
    [
        asyncpg.UndefinedColumnError('column "nope" does not exist'),
        asyncpg.InsufficientPrivilegeError("permission denied"),
        ValueError("not a database error"),
        RuntimeError("something else"),
    ],
)
def test_sql_errors_stay_db_error(error):
    assert _is_reader_connection_error(error) is False
