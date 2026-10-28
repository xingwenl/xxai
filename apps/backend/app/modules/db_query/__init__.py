"""只读查库能力（db_schema / db_query 两个内置工具的底层实现）。

隔离由数据库侧保证：独立的 reader 角色只有 SELECT 权限、所有业务表开启 RLS、
查询跑在只读事务里。本包的 guard 只负责「注定失败的 SQL 尽早失败」并把错误信息
变得对模型可读，不是安全边界（见 docs/adr/0018-db-query-read-only-boundary.md）。
"""
