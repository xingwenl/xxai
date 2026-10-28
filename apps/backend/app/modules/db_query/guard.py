"""只读 SQL 的轻量前置校验。

定位：**体验层**而非安全边界。真正的隔离由数据库侧保证（reader 角色只有 SELECT、
全表 RLS、只读事务）。这里做的是「注定失败的 SQL 在占用连接前就失败」，并把拒绝
原因变成模型能读懂的一句话。

实现方式是一个最小 SQL 扫描器（不引入 sqlglot / sqlparse）：一次扫描得到两个缓冲区：

- ``executable``：剥掉注释后的原文（字符串字面量保持不变），用于最终执行；
- ``code``：在上面的基础上把字符串字面量与双引号标识符的内容抹成空格，用于扫描
  语句分隔符与关键字——否则 ``where name = 'delete'`` 这类字符串会被误判成写语句。

注释统一替换成一个空格，因为 PostgreSQL 里注释等价于空白（``sel/**/ect`` 并不等于
``select``）。
"""

from __future__ import annotations

import re

# 写操作、DDL、权限、维护、事务控制关键字：出现即拒绝。
FORBIDDEN_KEYWORDS: tuple[str, ...] = (
    "insert",
    "update",
    "delete",
    "drop",
    "create",
    "alter",
    "truncate",
    "grant",
    "revoke",
    "copy",
    "merge",
    "call",
    "do",
    "vacuum",
    "analyze",
    "reindex",
    "refresh",
    "lock",
    "commit",
    "rollback",
    "set",
    "reset",
)

# 危险标识：改写会话/事务状态（set_config）、序列推进（setval）、踢会话
# （pg_terminate_backend / pg_cancel_backend）、读写服务器文件、读取权限表。
# 注意：标识符黑名单只是「早失败」，真正的边界是数据库权限（reader 角色只有 SELECT，
# set_config 已从 PUBLIC 收回执行权限）。_scan() 会把双引号标识符内容抹成空格，因此
# pg_catalog."set_config" 这类写法拦不住，这里不为它重写扫描器。
FORBIDDEN_IDENTIFIERS: tuple[str, ...] = (
    "set_config",
    "setval",
    "pg_terminate_backend",
    "pg_cancel_backend",
    "pg_read_file",
    "pg_read_binary_file",
    "pg_ls_dir",
    "pg_stat_file",
    "lo_import",
    "lo_export",
    "dblink",
    "pg_authid",
    "pg_shadow",
)

_ALLOWED_FIRST_WORDS: frozenset[str] = frozenset({"select", "with"})

_FORBIDDEN_KEYWORD_RE = re.compile(
    r"\b(" + "|".join(FORBIDDEN_KEYWORDS) + r")\b", re.IGNORECASE
)
_FORBIDDEN_IDENTIFIER_RE = re.compile(
    r"\b(" + "|".join(FORBIDDEN_IDENTIFIERS) + r")\b", re.IGNORECASE
)
_FIRST_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_DOLLAR_QUOTE_RE = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$")


class SqlRejected(Exception):
    """SQL 未通过只读校验。

    ``code`` 是细分原因（empty_sql / multiple_statements / not_select /
    forbidden_keyword / forbidden_function），``message`` 是可以直接给模型看的中文。
    工具层会把它们统一映射成稳定错误码 ``db_sql_rejected``。
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _skip_quoted(sql: str, start: int, quote: str) -> int:
    """从 ``start``（引号本身）开始跳过一段引号内容，返回闭合引号之后的下标。

    PostgreSQL 用引号重复表示转义（``'it''s'`` / ``"a""b"``）。未闭合时返回末尾，
    交给后续校验/数据库给出语法错误。
    """
    index = start + 1
    length = len(sql)
    while index < length:
        char = sql[index]
        if char == quote:
            if index + 1 < length and sql[index + 1] == quote:
                index += 2
                continue
            return index + 1
        index += 1
    return length


def _scan(sql: str) -> tuple[str, str]:
    """剥离注释，返回 ``(可执行 SQL, 仅代码文本)``。"""
    executable: list[str] = []
    code: list[str] = []
    index = 0
    length = len(sql)
    block_comment_depth = 0

    while index < length:
        char = sql[index]

        if block_comment_depth:
            if sql.startswith("/*", index):
                block_comment_depth += 1
                index += 2
            elif sql.startswith("*/", index):
                block_comment_depth -= 1
                index += 2
            else:
                index += 1
            continue

        if sql.startswith("--", index):
            # 行注释：替换成一个空格，换行符本身保留为空白
            executable.append(" ")
            code.append(" ")
            newline = sql.find("\n", index)
            index = length if newline == -1 else newline
            continue

        if sql.startswith("/*", index):
            executable.append(" ")
            code.append(" ")
            block_comment_depth = 1
            index += 2
            continue

        if char == "'":
            end = _skip_quoted(sql, index, "'")
            executable.append(sql[index:end])
            code.append(" " * (end - index))
            index = end
            continue

        if char == '"':
            # 引号标识符不可能是关键字，代码副本里抹掉以免 "update" 这类列名误杀
            end = _skip_quoted(sql, index, '"')
            executable.append(sql[index:end])
            code.append(" " * (end - index))
            index = end
            continue

        dollar_quote = _DOLLAR_QUOTE_RE.match(sql, index)
        if dollar_quote:
            tag = dollar_quote.group(0)
            closing = sql.find(tag, dollar_quote.end())
            end = length if closing == -1 else closing + len(tag)
            executable.append(sql[index:end])
            code.append(" " * (end - index))
            index = end
            continue

        executable.append(char)
        code.append(char)
        index += 1

    return "".join(executable), "".join(code)


def _strip_trailing_semicolons(sql: str) -> str:
    """去掉结尾空白与连续的结尾分号（允许 ``select 1;`` 这种写法）。"""
    stripped = sql.rstrip()
    while stripped.endswith(";"):
        stripped = stripped[:-1].rstrip()
    return stripped


def check_sql(sql: str, *, max_rows: int) -> str:
    """校验 SQL 是单条只读查询，返回包好外层 LIMIT 的最终 SQL。

    :param sql: 模型给出的原始 SQL。
    :param max_rows: 外层 LIMIT 的行数上限（正整数，由调用方按配置传入）。
    :raises SqlRejected: SQL 不是合规的单条 SELECT / WITH 查询。
    :raises ValueError: ``max_rows`` 不是正整数（调用方 bug，不是用户输入问题）。
    """
    if not isinstance(max_rows, int) or isinstance(max_rows, bool) or max_rows < 1:
        raise ValueError("max_rows 必须是正整数")

    if not isinstance(sql, str) or not sql.strip():
        raise SqlRejected("empty_sql", "SQL 不能为空")

    executable, code = _scan(sql)

    # 先按分号判断语句数：字符串/注释里的分号已在 code 副本里抹掉
    code_without_tail = _strip_trailing_semicolons(code)
    if ";" in code_without_tail:
        raise SqlRejected(
            "multiple_statements",
            "一次只能执行一条 SQL，请去掉分号拼接的多条语句",
        )

    leading = code_without_tail.lstrip()
    if not leading:
        raise SqlRejected("empty_sql", "SQL 不能为空")

    first_word_match = _FIRST_WORD_RE.match(leading)
    first_word = first_word_match.group(0).lower() if first_word_match else ""
    if first_word not in _ALLOWED_FIRST_WORDS:
        raise SqlRejected("not_select", "只允许执行只读查询（SELECT 或 WITH）")

    forbidden_keyword = _FORBIDDEN_KEYWORD_RE.search(leading)
    if forbidden_keyword:
        keyword = forbidden_keyword.group(0)
        raise SqlRejected(
            "forbidden_keyword",
            f"SQL 包含不允许的关键字：{keyword.upper()}，只允许只读查询",
        )

    forbidden_identifier = _FORBIDDEN_IDENTIFIER_RE.search(leading)
    if forbidden_identifier:
        identifier = forbidden_identifier.group(0)
        raise SqlRejected(
            "forbidden_function",
            f"SQL 使用了不允许的函数或系统表：{identifier}",
        )

    final_sql = _strip_trailing_semicolons(executable)
    if not final_sql:
        raise SqlRejected("empty_sql", "SQL 不能为空")

    # 外层强制包一层 LIMIT：无论模型是否自己写了 LIMIT 都生效；
    # max_rows 是 int() 格式化，不存在注入面。
    # 这里故意取 max_rows + 1：runner 靠「多出来的一行」判断结果是否被行数
    # 上限截断（正好 max_rows 行 ≠ 截断）。多取的一行在 runner 里被丢掉，不会返回。
    return f"SELECT * FROM (\n{final_sql}\n) AS db_q LIMIT {int(max_rows) + 1}"
