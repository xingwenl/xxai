"""db_query 的 SQL 轻校验单测。

这层**不是安全边界**（安全由数据库侧的只读角色与行级策略强制），
它只负责让模型尽早拿到可读的错误、并保证每条 SQL 都被外层 LIMIT 兜住。
覆盖：放行单条 SELECT/WITH、强制外层 LIMIT、注释与分号处理、各类写语句与
危险函数被拒。
"""

from __future__ import annotations

import pytest

from app.modules.db_query.guard import SqlRejected, check_sql


def test_simple_select_is_wrapped_with_limit():
    sql = check_sql("select id, created_at from conversations", max_rows=5)
    # 原文被包进子查询，外层统一加上限，避免模型漏写 LIMIT 拉回全表
    assert "select id, created_at from conversations" in sql
    assert "select * from (" in sql.lower()
    # 外层 LIMIT 取 max_rows + 1，多出的一行用于 runner 判断「是否被行数上限截断」
    assert sql.rstrip().endswith("LIMIT 6")


def test_uppercase_and_whitespace_are_accepted():
    sql = check_sql("   \n\t SELECT 1   ", max_rows=1)
    assert "LIMIT 2" in sql


def test_cte_is_accepted():
    sql = check_sql(
        "with recent as (select id from conversations where created_at > now() - interval '1 day') "
        "select count(*) from recent",
        max_rows=10,
    )
    assert "LIMIT 11" in sql


def test_leading_comment_does_not_break_detection():
    sql = check_sql("/* 统计会话数 */ select count(*) from conversations", max_rows=10)
    assert "LIMIT 11" in sql


def test_trailing_semicolon_is_single_statement():
    sql = check_sql("select 1;", max_rows=3)
    assert "LIMIT 4" in sql


def test_existing_limit_is_still_capped_by_outer_limit():
    sql = check_sql("select id from conversations limit 5000", max_rows=200)
    # 内层 LIMIT 保留，但外层再兜一次，模型写多大都不会突破上限
    assert "limit 5000" in sql.lower()
    assert sql.rstrip().endswith("LIMIT 201")


@pytest.mark.parametrize(
    "sql",
    [
        "",
        "   ",
        "update conversations set title = 'x'",
        "delete from conversations",
        "insert into conversations (title) values ('x')",
        "drop table conversations",
        "create table t (id int)",
        "alter table conversations add column x int",
        "truncate conversations",
        "grant select on conversations to public",
        "revoke select on conversations from public",
        "copy conversations to '/tmp/x.csv'",
        "set search_path to pg_catalog",
        "vacuum conversations",
        "analyze conversations",
        "explain select 1",
        "select 1; drop table conversations",
        "select pg_read_file('/etc/passwd')",
        "select * from pg_authid",
    ],
)
def test_unsafe_sql_is_rejected(sql):
    with pytest.raises(SqlRejected) as excinfo:
        check_sql(sql, max_rows=100)
    # 细分原因是给日志与排障用的；工具层再统一翻成稳定码 db_sql_rejected
    assert excinfo.value.code in {
        "empty_sql",
        "multiple_statements",
        "not_select",
        "forbidden_keyword",
        "forbidden_function",
    }
    assert excinfo.value.message


def test_semicolon_inside_string_literal_is_not_multi_statement():
    # 字符串字面量里的分号不是语句分隔符，交给数据库解析，这里不应误判
    sql = check_sql("select ';' as sep", max_rows=2)
    assert "LIMIT 3" in sql


def test_semicolon_inside_comment_is_not_multi_statement():
    sql = check_sql("select 1 -- 结束; 还有 drop table x 在注释里", max_rows=2)
    assert "LIMIT 3" in sql


@pytest.mark.parametrize(
    "sql",
    [
        # 改写会话/事务 GUC：set_config 已从 PUBLIC 收回执行权限，应用层也改用
        # SET LOCAL，这里提前把模型能想到的写法都拦成 forbidden_function
        "select set_config('app.platform_id', '1', true)",
        "select pg_catalog.set_config('app.platform_id', '1', true)",
        # 推进序列 / 踢掉其他会话 / 读服务器文件
        "select setval('conversations_id_seq', 1)",
        "select pg_terminate_backend(1234)",
        "select pg_cancel_backend(1234)",
        "select pg_stat_file('pg_hba.conf')",
    ],
)
def test_guc_and_admin_functions_are_rejected(sql):
    """SET LOCAL 改写 GUC、序列推进、会话管理等函数必须在 guard 层早失败。"""
    with pytest.raises(SqlRejected) as excinfo:
        check_sql(sql, max_rows=100)
    assert excinfo.value.code == "forbidden_function"
    assert excinfo.value.message

