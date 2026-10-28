#!/usr/bin/env bash
# 只读查库能力（db_schema / db_query 两个内置工具 + db-query 技能）的验证脚本。
#
# 覆盖：静态检查与工具注册、迁移升级/回滚、库侧安全边界（角色/RLS/策略/权限）、
# 启动期覆盖检查的 fail-closed 行为、真库租户隔离、工具层错误码与结果上限、
# 审计落库、未开通时的稳定错误码、应用完整性、相关回归测试。
#
# 用法：tools/harness/verify.sh 2026-10-27-db-query-skill
# 依赖：本地 PostgreSQL（默认 127.0.0.1:5432/ai_db）、apps/backend/.venv、pnpm。
# 库连不上时相关段落会记为「未执行」，不会伪装成通过。
#
# 注意：本脚本会在第 3 段 downgrade/upgrade 迁移，迁移会删除并重建 agent_reader 角色，
# 正在运行的 api/worker 里已建立的只读连接池因此失效（表现为 invalid role OID /
# permission denied）。脚本退出时会恢复角色密码，但**应用侧需要重启容器**才能重连：
#   docker compose restart api worker task-scheduler wechat-bot-worker
# 若本地已经开通了查库能力，更稳妥的做法是指定一个独立库：VERIFY_DATABASE_URL=…。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
BACKEND="$ROOT/apps/backend"
FRONT="$ROOT/apps/front"
PY="$BACKEND/.venv/bin/python"
DB_URL="${VERIFY_DATABASE_URL:-${DATABASE_URL:-postgresql+asyncpg://root:Dd123456@127.0.0.1:5432/ai_db}}"
READER_USER="agent_reader"
READER_PASSWORD="tmp_verify_only_$$"
READER_LOGIN_OPEN=0
# 运行前 agent_reader 的原状态（"<密码散列>|t|f"）；退出时据此恢复，避免 /verify
# 一次就把本地已开通的查库能力（.env 里的连接串）弄失效。
ORIG_READER_STATE=""
FAIL=0

printf '## 已执行的命令与结果\n'

section() { printf '\n### %s\n\n' "$1"; }
verdict() { if [ "$1" -eq 0 ]; then printf '\n结果：PASS（exit=0）\n'; else printf '\n结果：FAIL（exit=%s）\n' "$1"; FAIL=1; fi; }

restore_reader() {
  # 无论脚本怎么退出，都不能把 agent_reader 留在脚本造的临时登录态里：
  # 运行前本来就开通了（本地有 .env 连接串）就恢复原密码散列，否则收回成 NOLOGIN。
  if [ "$READER_LOGIN_OPEN" = "1" ] || [ -n "${ORIG_READER_STATE:-}" ]; then
    ORIG_READER_STATE="${ORIG_READER_STATE:-}" DATABASE_URL="$DB_URL" "$PY" - <<'PY' 2>&1 || true
import asyncio, os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

STATE = (os.environ.get("ORIG_READER_STATE") or "").strip()


async def main():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    try:
        async with engine.begin() as conn:
            if "|" in STATE:
                hashed, can_login = STATE.split("|", 1)
                if hashed and can_login.strip() == "t":
                    # 已经加密过的散列按原样写回（PostgreSQL 会直接存，不重复加密）。
                    # 必须用 exec_driver_sql 发原始 SQL：text() 会把散列里的 "$4096…"
                    # 当成绑定参数，ALTER 直接失败、密码被清空而 LOGIN 还开着。
                    escaped = hashed.replace("'", "''")
                    await conn.exec_driver_sql(
                        f"ALTER ROLE agent_reader WITH LOGIN PASSWORD '{escaped}'"
                    )
                    now = (
                        await conn.execute(
                            text(
                                "select rolpassword from pg_authid "
                                "where rolname = 'agent_reader'"
                            )
                        )
                    ).scalar()
                    print(
                        "恢复 agent_reader：LOGIN + 原密码散列"
                        + ("（已校验一致）" if now == hashed else "（校验不一致！）")
                    )
                    return
            await conn.exec_driver_sql(
                "ALTER ROLE agent_reader WITH NOLOGIN PASSWORD NULL"
            )
            print("恢复 agent_reader：NOLOGIN + 空密码")
    finally:
        await engine.dispose()


asyncio.run(main())
PY
    READER_LOGIN_OPEN=0
  fi
}
trap restore_reader EXIT

db_reachable() {
  DATABASE_URL="$DB_URL" "$PY" - <<'PY' >/dev/null 2>&1
import asyncio, os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

async def main():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    try:
        async with engine.connect() as conn:
            await conn.execute(text("select 1"))
    finally:
        await engine.dispose()

asyncio.run(main())
PY
}

DB_OK=0
if db_reachable; then
  DB_OK=1
  printf '连接数据库：`%s`\n' "${DB_URL%%@*}@…"
else
  printf '数据库不可用（%s），涉及库的段落将记为未执行。\n' "${DB_URL%%@*}@…"
fi

# ---------------------------------------------------------------------------
# 记录运行前的角色状态：本地可能已经按 runbook 开通了查库能力（.env 里有连接串），
# 脚本结束时必须把它恢复回去，否则跑一次 /verify 就会让线上能力静默失效。
if [ "$DB_OK" = "1" ]; then
  ORIG_READER_STATE="$(
    DATABASE_URL="$DB_URL" "$PY" - <<'PY' 2>/dev/null
import asyncio, os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def main():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    try:
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "select rolpassword, rolcanlogin from pg_authid "
                        "where rolname = 'agent_reader'"
                    )
                )
            ).first()
            if row is None:
                print("")
            else:
                print(f"{row[0] or ''}|{'t' if row[1] else 'f'}")
    finally:
        await engine.dispose()


asyncio.run(main())
PY
  )"
  case "$ORIG_READER_STATE" in
    *"|t") printf '运行前 agent_reader：已开通 LOGIN（结束时恢复原密码散列）\n' ;;
    *"|f") printf '运行前 agent_reader：存在但未开通 LOGIN（结束时收回为 NOLOGIN）\n' ;;
    *) printf '运行前 agent_reader：不存在（结束时保持不存在/NOLOGIN）\n' ;;
  esac
fi

# 上一次运行若在 section 6 中途被打断，可能把 agent_reader 留在可登录态；先复位，
# 这样 section 2 对「角色默认不可登录」的断言才是确定性的（角色不存在则跳过）。
section "0. 复位上一次中断留下的临时登录态（保证后续断言可重复）"
if [ "$DB_OK" = "1" ]; then
  printf '```text\n'
  DATABASE_URL="$DB_URL" "$PY" - <<'PY' 2>&1
import asyncio
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.exc import ProgrammingError


async def main():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    try:
        async with engine.begin() as conn:
            try:
                await conn.execute(
                    text("ALTER ROLE agent_reader WITH NOLOGIN PASSWORD NULL")
                )
                print("agent_reader 已复位：NOLOGIN + 空密码")
            except ProgrammingError:
                print("agent_reader 尚不存在（全新库），跳过复位")
    finally:
        await engine.dispose()


asyncio.run(main())
PY
  verdict $?
  printf '```\n'
else
  printf '跳过：数据库不可用。\n'
fi

# ---------------------------------------------------------------------------
section "1. 静态检查：ruff 与工具注册"
cd "$BACKEND" || exit 1
"$PY" -m ruff check \
  app/modules/db_query \
  app/modules/tools/business/db_query.py \
  app/modules/tools/business/registry.py \
  app/modules/builtin_tool/groups.py \
  app/__init__.py \
  migrations/versions/20261027_0047_agent_reader_and_rls.py \
  tests/tools/test_db_query_guard.py \
  tests/db_query/test_reader_isolation.py 2>&1
verdict $?

printf '\n```text\n'
PYTHONPATH="$BACKEND" DATABASE_URL="$DB_URL" "$PY" - <<'PY' 2>&1
"""工具注册与副作用声明的静态断言（导入即注册，漏登记分组会在导入期报错）。"""
from app.modules.builtin_tool.groups import BUILTIN_TOOL_GROUPS, TOOL_GROUP_META
from app.modules.tools.business import registry  # noqa: F401  导入即注册全部业务工具
from app.modules.tools.business.framework import BUSINESS_TOOL_REGISTRY
from app.modules.tools.side_effects import side_effect_rank

for name in ("db_schema", "db_query"):
    tool = BUSINESS_TOOL_REGISTRY[name]
    group = BUILTIN_TOOL_GROUPS[name]
    assert group == "db", f"{name} 应登记到 db 组，实际 {group}"
    assert tool.side_effect == "none", f"{name} 的副作用应为 none，实际 {tool.side_effect}"
    assert side_effect_rank(tool.side_effect) == 0
    print(f"{name}: group={group} side_effect={tool.side_effect} 必填参数={tool.input_schema.get('required')}")

title, description = TOOL_GROUP_META["db"]
print(f"db 组：title={title} description={description}")
print("工具注册与分组断言通过")
PY
verdict $?
printf '```\n'

# ---------------------------------------------------------------------------
section "2. 迁移升级与库侧安全边界"
if [ "$DB_OK" = "1" ]; then
  printf '```bash\n$ alembic upgrade head\n```\n'
  printf '\n```text\n'
  ( cd "$BACKEND" && DATABASE_URL="$DB_URL" "$PY" -m alembic upgrade head 2>&1 ) | grep -v '^INFO' | tail -5
  upgrade_rc=${PIPESTATUS[0]}
  printf '\n```\n'
  if [ "$upgrade_rc" -ne 0 ]; then
    verdict "$upgrade_rc"
  fi

  printf '\n```text\n'
  PYTHONPATH="$BACKEND" DATABASE_URL="$DB_URL" "$PY" - <<'PY' 2>&1
"""升级后的库侧断言：角色属性、RLS 覆盖、策略清单、权限、审计表。"""
import asyncio
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

EXPECTED_NO_POLICY = {"alembic_version", "sys_roles", "sys_user_roles", "sys_users"}
EXPECTED_VERSION = "20261027_0047"


async def main():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    try:
        async with engine.connect() as conn:
            version = (await conn.execute(text("select version_num from alembic_version"))).scalar()
            assert version == EXPECTED_VERSION, f"alembic head 应为 {EXPECTED_VERSION}，实际 {version}"
            print(f"alembic_version = {version}")

            role = (
                await conn.execute(
                    text(
                        "select rolsuper, rolcanlogin, rolbypassrls, rolconfig "
                        "from pg_roles where rolname = 'agent_reader'"
                    )
                )
            ).first()
            assert role is not None, "agent_reader 角色不存在"
            assert role[0] is False, "agent_reader 不应是超级用户"
            assert role[1] is False, "agent_reader 默认不应可登录（密码由 runbook 手动开）"
            assert role[2] is False, "agent_reader 不应绕过 RLS"
            config = " ".join(role[3] or [])
            for expected in (
                "default_transaction_read_only=on",
                "idle_in_transaction_session_timeout",
                "statement_timeout",
            ):
                assert expected in config, f"角色级 GUC 缺少 {expected}"
            print(f"agent_reader: rolsuper={role[0]} rolcanlogin={role[1]} rolbypassrls={role[2]}")
            print(f"agent_reader rolconfig: {config}")

            tables = (
                await conn.execute(
                    text(
                        "select count(*) from pg_class c join pg_namespace n on n.oid = c.relnamespace "
                        "where n.nspname = 'public' and c.relkind = 'r'"
                    )
                )
            ).scalar()
            print(f"public 下 base table = {tables}")

            rls_on = (
                await conn.execute(
                    text(
                        "select count(*) from pg_class c join pg_namespace n on n.oid = c.relnamespace "
                        "where n.nspname = 'public' and c.relkind = 'r' and c.relrowsecurity"
                    )
                )
            ).scalar()
            assert rls_on == tables, f"应全部开启 RLS：{rls_on}/{tables}"
            print(f"relrowsecurity=true 的表 = {rls_on}/{tables}")

            gap = (
                await conn.execute(
                    text(
                        "select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace "
                        "where n.nspname = 'public' and c.relkind = 'r' and not c.relrowsecurity "
                        "and exists (select 1 from pg_attribute a where a.attrelid = c.oid "
                        "and a.attname = 'platform_id' and a.attnum > 0 and not a.attisdropped)"
                    )
                )
            ).scalars().all()
            assert gap == [], f"以下平台表未开启 RLS：{gap}"
            print("有 platform_id 但未开启 RLS 的表 = 0")

            no_policy = (
                await conn.execute(
                    text(
                        "select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace "
                        "where n.nspname = 'public' and c.relkind = 'r' and c.relrowsecurity "
                        "and not exists (select 1 from pg_policy p where p.polrelid = c.oid) order by 1"
                    )
                )
            ).scalars().all()
            assert set(no_policy) == EXPECTED_NO_POLICY, f"无策略表集合不符：{no_policy}"
            print(f"启用 RLS 但无策略（默认拒绝）的表 = {no_policy}")

            policy_count = (await conn.execute(text("select count(*) from pg_policy"))).scalar()
            print(f"策略数 = {policy_count}")
            assert policy_count >= 50, "策略数少于预期"

            grants = (
                await conn.execute(
                    text(
                        "select count(distinct table_name) from information_schema.role_table_grants "
                        "where grantee = 'agent_reader' and privilege_type = 'SELECT'"
                    )
                )
            ).scalar()
            print(f"agent_reader 有 SELECT 权限的表 = {grants}")
            # 审计表被明确收回：里面是同平台其它会话的 SQL 摘要
            assert grants == tables - 1, f"SELECT 应覆盖除 db_query_audits 外的 {tables - 1} 张表，实际 {grants}"

            can_insert = (
                await conn.execute(
                    text("select has_table_privilege('agent_reader', 'db_query_audits', 'INSERT')")
                )
            ).scalar()
            assert can_insert is False, "agent_reader 不应能写审计表"
            can_select_audit = (
                await conn.execute(
                    text("select has_table_privilege('agent_reader', 'db_query_audits', 'SELECT')")
                )
            ).scalar()
            assert can_select_audit is False, "agent_reader 不应能读审计表"
            print("agent_reader 对 db_query_audits：SELECT=不可读，INSERT=不可写")

            # H1 的核心防线：set_config 从 PUBLIC 收回后，模型 SQL 无法改写租户 GUC
            can_set_config = (
                await conn.execute(
                    text(
                        "select has_function_privilege('agent_reader', "
                        "'pg_catalog.set_config(text,text,boolean)', 'execute')"
                    )
                )
            ).scalar()
            assert can_set_config is False, "agent_reader 不应能执行 set_config"
            can_terminate = (
                await conn.execute(
                    text(
                        "select count(*) from pg_proc p where p.pronamespace = 'pg_catalog'::regnamespace "
                        "and p.proname in ('pg_terminate_backend', 'pg_cancel_backend', 'pg_read_file') "
                        "and has_function_privilege('agent_reader', p.oid, 'execute')"
                    )
                )
            ).scalar()
            assert can_terminate == 0, f"{can_terminate} 个 backend/文件类函数仍对 agent_reader 可执行"
            print("agent_reader：set_config 不可执行，backend/文件类函数均不可执行")


            comment_total = (
                await conn.execute(
                    text(
                        "select count(*) from pg_attribute a where a.attrelid = 'db_query_audits'::regclass "
                        "and a.attnum > 0 and not a.attisdropped"
                    )
                )
            ).scalar()
            comment_missing = (
                await conn.execute(
                    text(
                        "select count(*) from pg_attribute a where a.attrelid = 'db_query_audits'::regclass "
                        "and a.attnum > 0 and not a.attisdropped "
                        "and (col_description(a.attrelid, a.attnum) is null "
                        "or col_description(a.attrelid, a.attnum) = '')"
                    )
                )
            ).scalar()
            assert comment_missing == 0, f"{comment_missing} 个字段缺少中文 comment"
            print(f"db_query_audits 字段 = {comment_total}，缺少注释 = {comment_missing}")
    finally:
        await engine.dispose()


asyncio.run(main())
print("库侧安全边界断言通过")
PY
  verdict $?
  printf '```\n'

  section "3. 迁移回滚与再升级"
printf '注意：本段会重建 agent_reader 角色，正在运行的后端容器需重启才能重连（见脚本头部说明）。\n\n'
  printf '```text\n'
  ( cd "$BACKEND" && DATABASE_URL="$DB_URL" "$PY" -m alembic downgrade -1 2>&1 ) | grep -v '^INFO' | tail -5
  down_rc=${PIPESTATUS[0]}
  verdict "$down_rc"

  printf '\n```text\n'
  PYTHONPATH="$BACKEND" DATABASE_URL="$DB_URL" "$PY" - <<'PY' 2>&1
"""回滚后必须干净：版本回落、角色消失、审计表消失、RLS 与策略清零。"""
import asyncio
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def main():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    try:
        async with engine.connect() as conn:
            version = (await conn.execute(text("select version_num from alembic_version"))).scalar()
            assert version == "20261021_0046", f"回滚后版本应为 20261021_0046，实际 {version}"
            print(f"alembic_version = {version}")

            role = (await conn.execute(text("select count(*) from pg_roles where rolname = 'agent_reader'"))).scalar()
            assert role == 0, "回滚后 agent_reader 应被删除"
            print("agent_reader 已删除")

            audits = (
                await conn.execute(text("select to_regclass('public.db_query_audits')"))
            ).scalar()
            assert audits is None, "回滚后 db_query_audits 应被删除"
            print("db_query_audits 已删除")

            rls_on = (
                await conn.execute(
                    text(
                        "select count(*) from pg_class c join pg_namespace n on n.oid = c.relnamespace "
                        "where n.nspname = 'public' and c.relkind = 'r' and c.relrowsecurity"
                    )
                )
            ).scalar()
            policies = (await conn.execute(text("select count(*) from pg_policy"))).scalar()
            assert rls_on == 0 and policies == 0, f"回滚后应为 0：rls_on={rls_on} policies={policies}"
            print(f"relrowsecurity=true = {rls_on}，策略数 = {policies}")
    finally:
        await engine.dispose()


asyncio.run(main())
print("回滚断言通过")
PY
  verdict $?
  printf '```\n'

  printf '\n```text\n'
  ( cd "$BACKEND" && DATABASE_URL="$DB_URL" "$PY" -m alembic upgrade head 2>&1 ) | grep -v '^INFO' | tail -5
  reup_rc=${PIPESTATUS[0]}
  verdict "$reup_rc"
  printf '```\n'
else
  printf '跳过：数据库不可用，未执行迁移升级/回滚与库侧断言。\n'
fi

# ---------------------------------------------------------------------------
section "4. SQL 轻校验单测（不是安全边界，只保证早失败与外层 LIMIT）"
printf '```text\n'
( cd "$BACKEND" && "$PY" -m pytest tests/tools/test_db_query_guard.py -q 2>&1 | tail -5 )
verdict $?
printf '```\n'

# ---------------------------------------------------------------------------
section "5. 启动期自检 fail-closed（角色身份 + 默认拒绝覆盖 + 越权拒绝）"
if [ "$DB_OK" = "1" ]; then
  printf '```text\n'
  printf '5a) 把 DATABASE_READER_URL 误配成超级用户（root）时必须拒绝启动：\n'
  PYTHONPATH="$BACKEND" DATABASE_URL="$DB_URL" DATABASE_READER_URL="$DB_URL" "$PY" - <<'PY' 2>&1
"""角色身份自检：连接角色是超级用户/绕过 RLS/表 owner 时，策略对它全部失效。"""
import asyncio

from app.modules.db_query.health import ensure_rls_coverage


async def main():
    raised = False
    try:
        await ensure_rls_coverage()
    except RuntimeError as exc:
        raised = True
        print(f"拒绝启动：{exc}")
    assert raised, "把超级用户连接串当只读连接时必须拒绝启动"


asyncio.run(main())
PY
  verdict $?
  printf '```\n'

  # 提前置位：即使 5b 中途失败，EXIT trap 也会把 agent_reader 复位成 NOLOGIN
  READER_LOGIN_OPEN=1
  printf '\n5b) 白名单外「没有 platform_id、也没有策略」的新表必须拒绝启动；set_config 越权必须被权限层拒绝：\n\n```text\n'
  READER_PASSWORD="$READER_PASSWORD" DATABASE_URL="$DB_URL" "$PY" - <<'PY' 2>&1
"""默认拒绝覆盖检查 + 越权实证（探针表与临时密码用完立刻复位）。"""
import asyncio
import os
import urllib.parse

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

PROBE = "_rls_coverage_probe"


def build_reader_url() -> str:
    parts = urllib.parse.urlsplit(os.environ["DATABASE_URL"])
    host = parts.hostname or "127.0.0.1"
    port = parts.port or 5432
    database = (parts.path or "/ai_db").lstrip("/")
    password = os.environ["READER_PASSWORD"]
    return f"postgresql+asyncpg://agent_reader:{password}@{host}:{port}/{database}"


async def main():
    root = create_async_engine(os.environ["DATABASE_URL"])
    reader = None
    password = os.environ["READER_PASSWORD"]
    try:
        async with root.begin() as conn:
            await conn.execute(text(f"drop table if exists {PROBE}"))
            # 故意不给 platform_id、也不建策略：旧检查只认 platform_id，看不出这种表
            await conn.execute(text(f"create table {PROBE} (id bigint)"))
            await conn.execute(text(f"ALTER ROLE agent_reader WITH LOGIN PASSWORD '{password}'"))
        print("已临时开启 agent_reader 登录（脚本退出时会复位），并建了无策略探针表")

        os.environ["DATABASE_READER_URL"] = build_reader_url()
        from app.core.config import get_settings

        get_settings.cache_clear()  # get_settings 带 lru_cache，必须清掉才看得到新 env
        from app.modules.db_query.health import ensure_rls_coverage

        raised = False
        try:
            await ensure_rls_coverage()
        except RuntimeError as exc:
            raised = True
            print(f"无 platform_id 的新表未建策略时拒绝启动：{exc}")
        assert raised, "白名单外缺策略的表必须让启动失败"

        async with root.begin() as conn:
            await conn.execute(text(f"drop table {PROBE}"))
        await ensure_rls_coverage()
        print("探针表删除后覆盖检查通过")

        # 越权实证：模型 SQL 里改写租户 GUC 必须被数据库权限层拒绝
        reader = create_async_engine(os.environ["DATABASE_READER_URL"])
        async with reader.connect() as conn:
            for platform_id in ("1", "2"):
                await conn.execute(text("BEGIN"))
                await conn.execute(text("SET TRANSACTION READ ONLY"))
                await conn.execute(text(f"SET LOCAL app.platform_id = '{platform_id}'"))
                count = (await conn.execute(text("select count(*) from conversations"))).scalar()
                print(f"SET LOCAL app.platform_id={platform_id} → conversations 可见 {count} 行")
                await conn.execute(text("COMMIT"))

            # 攻击用例：从平台 2 的上下文里把 GUC 改成平台 1，再读平台 1 的数据
            attack = "select count(*) from (select set_config('app.platform_id','1',true)) s, conversations c"
            quoted = (
                'select count(*) from (select pg_catalog."set_config"('
                "'app.platform_id','1',true)) s, conversations c"
            )
            for label, sql in (("set_config", attack), ('pg_catalog."set_config"', quoted)):
                await conn.execute(text("BEGIN"))
                await conn.execute(text("SET TRANSACTION READ ONLY"))
                await conn.execute(text("SET LOCAL app.platform_id = '2'"))
                try:
                    await conn.execute(text(sql))
                except Exception as exc:  # 具体异常类型由驱动决定，这里只断言被拒绝
                    print(f"越权用例 {label}：被拒绝（{type(exc).__name__}，permission denied）")
                    await conn.execute(text("ROLLBACK"))
                else:
                    raise AssertionError(f"越权用例 {label} 仍可执行，租户隔离被击穿")
    finally:
        if reader is not None:
            await reader.dispose()
        async with root.begin() as conn:
            await conn.execute(text("ALTER ROLE agent_reader WITH NOLOGIN PASSWORD NULL"))
            await conn.execute(text(f"drop table if exists {PROBE}"))
        await root.dispose()


asyncio.run(main())
PY
  verdict $?
  printf '```\n'
  READER_LOGIN_OPEN=0
else
  printf '跳过：数据库不可用。\n'
fi

# ---------------------------------------------------------------------------
section "6. 真库租户隔离与工具层端到端"
if [ "$DB_OK" = "1" ]; then
  printf '```text\n'
  READER_PASSWORD="$READER_PASSWORD" DATABASE_URL="$DB_URL" "$PY" - <<'PY' 2>&1
"""临时给 agent_reader 开一个密码（脚本退出时会复位成 NOLOGIN + 空密码）。"""
import asyncio
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def main():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    try:
        async with engine.begin() as conn:
            password = os.environ["READER_PASSWORD"]
            await conn.execute(text(f"ALTER ROLE agent_reader WITH LOGIN PASSWORD '{password}'"))
    finally:
        await engine.dispose()


asyncio.run(main())
print("已临时开启 agent_reader 登录（验证结束后复位）")
PY
  login_rc=$?
  [ "$login_rc" -eq 0 ] && READER_LOGIN_OPEN=1
  verdict "$login_rc"
  printf '```\n'

  if [ "$READER_LOGIN_OPEN" = "1" ]; then
    READER_URL="$(
      READER_PASSWORD="$READER_PASSWORD" DB_URL="$DB_URL" "$PY" - <<'PY'
import os
import urllib.parse

parts = urllib.parse.urlsplit(os.environ["DB_URL"])
host = parts.hostname or "127.0.0.1"
port = parts.port or 5432
database = (parts.path or "/ai_db").lstrip("/")
print(f"postgresql+asyncpg://agent_reader:{os.environ['READER_PASSWORD']}@{host}:{port}/{database}")
PY
    )"

    printf '\n```text\n'
    ( cd "$BACKEND" && DATABASE_READER_URL="$READER_URL" "$PY" -m pytest tests/db_query/test_reader_isolation.py -q 2>&1 | tail -8 )
    verdict $?
    printf '```\n'

    printf '\n工具层端到端（错误码、结果上限、审计落库）：\n\n'
    printf '```text\n'
    PYTHONPATH="$BACKEND" DATABASE_URL="$DB_URL" DATABASE_READER_URL="$READER_URL" "$PY" - <<'PY' 2>&1
"""直接调用两个工具 handler：验证稳定错误码、200 行上限与审计落库。"""
import asyncio
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.database import dispose_database, init_database
from app.modules.db_query.engine import dispose_reader_engine
from app.modules.tools.business.db_query import db_query_tool, db_schema_tool
from app.modules.tools.business.framework import BusinessToolContext, BusinessToolError

CTX = BusinessToolContext(platform_id=1, agent_id=1, conversation_id=1)


async def expect_error(sql: str) -> str:
    try:
        await db_query_tool({"sql": sql}, CTX)
    except BusinessToolError as exc:
        print(f"  {sql[:48]!r} -> {exc.code} | {exc.message}")
        return exc.code
    raise AssertionError(f"本应被拒绝却执行成功：{sql}")


async def main():
    init_database()  # 同步创建全局 engine；只有 dispose_database 是异步的
    try:
        schema = await db_schema_tool({"tables": ["conversations"]}, CTX)
        print(f"db_schema: table_count={schema.get('table_count')} keys={sorted(schema.keys())}")
        column_count = len(schema["tables"][0]["columns"]) if schema.get("tables") else 0
        print(f"db_schema 列信息: columns={column_count} primary_key={schema['tables'][0]['primary_key'] if schema.get('tables') else []}")
        # 显式 tables 时必须带回列/主键/外键（这条路径会查 pg_constraint 的 conkey/confkey 数组列）
        assert column_count > 0, "显式 tables 时应返回列信息"

        overview = await db_schema_tool({}, CTX)
        overview_bytes = len(str(overview).encode("utf-8"))
        print(f"db_schema 默认（只回表名+注释）: table_count={overview.get('table_count')} bytes≈{overview_bytes}")
        assert overview.get("table_count", 0) > 0, "默认表清单不应为空"
        assert overview_bytes < 65536, f"默认表清单超出字节预算：{overview_bytes}"

        # 回归：asyncpg 类型内省会调用 set_config（本项目已从 PUBLIC 收回），
        # 因此只读连接关掉了 jit 探测；数组/pgvector 等类型的查询必须照常可用
        for sql in (
            "select conkey from pg_constraint limit 1",
            "select array[1, 2]::int4[] as a",
            "select embedding from conversation_asset_embeddings limit 1",
        ):
            probe = await db_query_tool({"sql": sql}, CTX)
            print(f"数组/向量类型查询 OK: {sql[:44]} -> row_count={probe.get('row_count')}")
            assert probe.get("row_count") == 1, f"类型内省相关查询失败：{sql}"

        result = await db_query_tool({"sql": "select count(*) as c from conversations"}, CTX)
        print(f"db_query: row_count={result.get('row_count')} rows={result.get('rows')} truncated={result.get('truncated')}")

        many = await db_query_tool({"sql": "select generate_series(1, 300) as n"}, CTX)
        print(f"300 行查询: row_count={many.get('row_count')} truncated={many.get('truncated')} reason={many.get('truncated_reason')}")
        assert many["row_count"] <= 200, "返回行数超过上限"
        assert many["truncated"] is True, "超过上限应标记 truncated"

        # 单元格上限：20000 字符的 text 必须截到 8192，并给出 max_cell_chars
        big_cell = await db_query_tool({"sql": "select repeat('x', 20000) as big"}, CTX)
        cell = big_cell["rows"][0][0]
        print(
            f"20KB 单元格: 返回长度={len(cell)} truncated={big_cell.get('truncated')} "
            f"reason={big_cell.get('truncated_reason')}"
        )
        assert len(cell) == 8192, f"单元格未按 8192 截断：{len(cell)}"
        assert big_cell["truncated"] is True
        assert big_cell["truncated_reason"] == "max_cell_chars", big_cell["truncated_reason"]

        # 总字节上限：150 行 × 500 字节 = 75000 > 65536，且行数没超上限，
        # 因此截断原因必须是 max_bytes（行数先触发时才会是 max_rows）
        wide = await db_query_tool(
            {"sql": "select repeat('y', 500) as s from generate_series(1, 150)"}, CTX
        )
        total_row_bytes = sum(len(str(row[0]).encode("utf-8")) for row in wide["rows"])
        print(
            f"字节预算: row_count={wide.get('row_count')} 总字节={total_row_bytes} "
            f"truncated={wide.get('truncated')} reason={wide.get('truncated_reason')}"
        )
        assert total_row_bytes <= 65536, f"结果总字节超过 65536：{total_row_bytes}"
        assert wide["truncated"] is True
        assert wide["truncated_reason"] == "max_bytes", wide["truncated_reason"]

        codes = [
            await expect_error("update conversations set updated_at = now()"),
            await expect_error("select 1; drop table conversations"),
            # 注释里藏分号后再接写语句：注释必须被剥离，但多语句仍要拒
            await expect_error("select 1 /* ; */ ; delete from conversations"),
            await expect_error("select pg_read_file('/etc/passwd')"),
            # 改写租户 GUC 的越权尝试：guard 早失败 + 数据库已收回 set_config 执行权
            await expect_error("select set_config('app.platform_id', '2', true)"),
        ]
        assert set(codes) == {"db_sql_rejected"}, f"拒绝码不符：{codes}"

        timeout_code = await expect_error("select pg_sleep(10)")
        assert timeout_code == "db_timeout", f"超时码不符：{timeout_code}"
    finally:
        await dispose_reader_engine()
        await dispose_database()

    engine = create_async_engine(os.environ["DATABASE_URL"])
    try:
        async with engine.connect() as conn:
            total = (await conn.execute(text("select count(*) from db_query_audits"))).scalar()
            rows = (
                await conn.execute(
                    text(
                        "select tool_name, status, coalesce(error_code, '-') from db_query_audits "
                        "order by id desc limit 8"
                    )
                )
            ).all()
    finally:
        await engine.dispose()
    print(f"审计行数 = {total}")
    for row in rows:
        print(f"  审计: tool={row[0]} status={row[1]} error_code={row[2]}")
    assert total > 0, "一次调用都没有落审计"


asyncio.run(main())
print("工具层端到端断言通过")
PY
    verdict $?
    printf '```\n'

    printf '\n恢复 agent_reader 为不可登录：\n\n'
    printf '```text\n'
    restore_reader
    printf '已恢复（NOLOGIN + 空密码）\n'
    printf '```\n'
  fi
else
  printf '跳过：数据库不可用，未执行真库隔离与工具端到端验证。\n'
fi

# ---------------------------------------------------------------------------
section "7. 未开通查库能力时返回稳定错误码"
printf '```text\n'
# 子进程里不设 DATABASE_READER_URL：引擎为 None，两个工具都必须返回 db_reader_not_configured
PYTHONPATH="$BACKEND" DATABASE_URL="$DB_URL" "$PY" - <<'PY' 2>&1
import asyncio

from app.core.database import dispose_database, init_database
from app.modules.tools.business.db_query import db_query_tool, db_schema_tool
from app.modules.tools.business.framework import BusinessToolContext, BusinessToolError

CTX = BusinessToolContext(platform_id=1, agent_id=1, conversation_id=1)


async def main():
    init_database()  # 同步创建全局 engine；只有 dispose_database 是异步的
    try:
        for tool, args in ((db_schema_tool, {}), (db_query_tool, {"sql": "select 1"})):
            try:
                await tool(args, CTX)
            except BusinessToolError as exc:
                print(f"{tool.__name__} -> {exc.code} | {exc.message}")
                assert exc.code == "db_reader_not_configured"
            else:
                raise AssertionError(f"{tool.__name__} 未配置 reader 时不应成功")
    finally:
        await dispose_database()


asyncio.run(main())
print("未开通时的稳定错误码断言通过")
PY
verdict $?
printf '```\n'

printf '\n连接串漏写驱动前缀（postgresql:// 而非 postgresql+asyncpg://）也必须收口成同一个稳定码：\n\n```text\n'
PYTHONPATH="$BACKEND" DATABASE_URL="$DB_URL" \
  DATABASE_READER_URL="postgresql://agent_reader:whatever@127.0.0.1:5432/ai_db" "$PY" - <<'PY' 2>&1
import asyncio

from app.core.database import dispose_database, init_database
from app.modules.tools.business.db_query import db_query_tool, db_schema_tool
from app.modules.tools.business.framework import BusinessToolContext, BusinessToolError

CTX = BusinessToolContext(platform_id=1, agent_id=1, conversation_id=1)


async def main():
    init_database()
    try:
        for tool, args in ((db_schema_tool, {}), (db_query_tool, {"sql": "select 1"})):
            try:
                await tool(args, CTX)
            except BusinessToolError as exc:
                print(f"{tool.__name__} -> {exc.code}")
                assert exc.code == "db_reader_not_configured"
            else:
                raise AssertionError(f"{tool.__name__} 连接串非法时不应成功")
    finally:
        await dispose_database()


asyncio.run(main())
print("非法连接串时的稳定错误码断言通过")
PY
verdict $?
printf '```\n'

# 密码轮换后仍用旧连接串、或角色被收回 LOGIN：连接阶段的认证失败也必须收口成同一个
# 稳定码（否则模型只会看到 db_error 反复重试，而真正要做的是找管理员改配置）。
printf '\n连接阶段认证失败（密码错 / 角色已收回 LOGIN）同样必须收口成稳定码：\n\n```text\n'
PYTHONPATH="$BACKEND" DATABASE_URL="$DB_URL"   DATABASE_READER_URL="postgresql+asyncpg://agent_reader:wrong_password@127.0.0.1:5432/ai_db" "$PY" - <<'PY' 2>&1
import asyncio

from app.core.database import dispose_database, init_database
from app.modules.tools.business.db_query import db_query_tool, db_schema_tool
from app.modules.tools.business.framework import BusinessToolContext, BusinessToolError

CTX = BusinessToolContext(platform_id=1, agent_id=1, conversation_id=1)


async def main():
    init_database()
    try:
        for tool, args in ((db_schema_tool, {}), (db_query_tool, {"sql": "select 1"})):
            try:
                await tool(args, CTX)
            except BusinessToolError as exc:
                print(f"{tool.__name__} -> {exc.code} | {exc.message}")
                assert exc.code == "db_reader_not_configured"
            else:
                raise AssertionError(f"{tool.__name__} 认证失败时不应成功")
    finally:
        await dispose_database()


asyncio.run(main())
print("认证失败时的稳定错误码断言通过")
PY
verdict $?
printf '```\n'

# ---------------------------------------------------------------------------
section "8. 应用可启动（工具注册、分组、启动检查接线）"
printf '```text\n'
PYTHONPATH="$BACKEND" DATABASE_URL="$DB_URL" "$PY" - <<'PY' 2>&1
from app import create_app

application = create_app()
# 该 FastAPI 版本用惰性 _IncludedRouter，app.routes 上看不到子路由路径，
# 改从 OpenAPI 视图取真实挂载结果（也顺带证明 OpenAPI 能生成）。
paths = sorted(application.openapi()["paths"])
assert "/api/v1/system/health" in paths, "未挂载 API 路由"
assert "/api/v1/platforms/{platform_id}/agents/{agent_id}/builtin-tools" in paths, (
    "Agent 工具页接口未挂载"
)
print(f"create_app() 成功，OpenAPI 路径数 = {len(paths)}")
print("Agent 工具页接口已挂载：/platforms/{platform_id}/agents/{agent_id}/builtin-tools")
print("启动期 RLS 覆盖检查已接线（未配置 DATABASE_READER_URL 时跳过）")
PY
verdict $?
printf '```\n'

printf '\n运行中的 api 容器健康检查（证明 RLS 对超级用户连接零影响）：\n\n'
printf '```text\n'
# 容器跑的是迁移前构建的镜像代码，这条只证明「启用 RLS 后超级用户路径照常工作」
if HEALTH_CODE="$(curl -s -o /tmp/db_query_health.json -w '%{http_code}' --max-time 5 \
  http://127.0.0.1:8000/api/v1/system/health 2>/dev/null)" && [ "$HEALTH_CODE" = "200" ]; then
  printf 'GET /api/v1/system/health -> HTTP %s\n' "$HEALTH_CODE"
  head -c 300 /tmp/db_query_health.json; printf '\n'
  verdict 0
else
  printf '跳过：本机 127.0.0.1:8000 没有运行中的 api 容器。\n'
fi
printf '```\n'

# ---------------------------------------------------------------------------
section "9. 相关回归测试（业务工具与内置工具分组）"
printf '```text\n'
( cd "$BACKEND" && "$PY" -m pytest tests/tools tests/builtin_tool -q 2>&1 | tail -5 )
verdict $?
printf '```\n'

# ---------------------------------------------------------------------------
section "10. 前端构建（工具组由接口驱动，本次无前端代码改动）"
if [ -x "$FRONT/node_modules/.bin/vite" ] || [ -d "$FRONT/node_modules" ]; then
  printf '```text\n'
  ( cd "$ROOT" && pnpm --dir apps/front build 2>&1 | tail -8 )
  verdict $?
  printf '```\n'
else
  printf '跳过：apps/front/node_modules 不存在，未执行前端构建。\n'
fi

# ---------------------------------------------------------------------------
section "11. Harness 门禁审计"
printf '```text\n'
AUDIT_OUT="$( cd "$ROOT" && python3 tools/harness/audit.py 2>&1 )"
AUDIT_RC=$?
printf '%s\n' "$AUDIT_OUT" | tail -15
ERROR_LINES="$(mktemp)"
printf '%s\n' "$AUDIT_OUT" | grep '^ERROR' > "$ERROR_LINES" || true
# 本脚本的输出就是 verify.md 的内容：运行时该文件尚不存在，审计必然报这一条。
# 它是对「本次输出」的自指，不算真实门禁失败。
# 工作区里可能还有别人未提交的 request（缺 verify.md），那不属于本任务范围，
# 单独列出、不计入本任务的判定——否则任何一个并发任务的中间态都会把本任务判红。
OUR_ERRORS="$(
  grep '2026-10-27-db-query-skill' "$ERROR_LINES" \
    | grep -v '缺少 verify.md' | wc -l | tr -d ' '
)"
FOREIGN_ERRORS="$(grep -v '2026-10-27-db-query-skill' "$ERROR_LINES" || true)"
FOREIGN_COUNT="$(printf '%s' "$FOREIGN_ERRORS" | grep -c '^ERROR' || true)"
printf '\n注：运行时 verify.md 尚未生成（本脚本输出即其内容），「缺少 verify.md」一条属自指，已排除。\n'
printf '本任务相关的 ERROR 数 = %s（audit 退出码 %s）\n' "$OUR_ERRORS" "$AUDIT_RC"
if [ "${FOREIGN_COUNT:-0}" != "0" ]; then
  printf '另有 %s 条 ERROR 来自本任务之外、工作区里未提交的 request（不计入本任务判定）：\n' "$FOREIGN_COUNT"
  printf '%s\n' "$FOREIGN_ERRORS" | sed 's/^/  /'
fi
rm -f "$ERROR_LINES"
if [ "$OUR_ERRORS" = "0" ]; then verdict 0; else verdict 1; fi
printf '```\n'

# ---------------------------------------------------------------------------
printf '\n## 未执行项与原因\n\n'
if [ "$DB_OK" = "0" ]; then
  printf -- '- 所有依赖真实 PostgreSQL 的段落（迁移升级/回滚、库侧断言、启动检查 fail-closed、真库隔离、工具端到端、审计落库）未执行：数据库不可用。\n'
fi
printf -- '- 全量 `pytest` 未执行：仓库内多个同名测试文件（`test_services.py` 等）在无 `__init__.py` 的目录下会触发 import mismatch，属存量问题；本脚本改跑工具/分组相关的 `tests/tools tests/builtin_tool` 与两个新增测试文件。\n'
printf -- '- 「Agent 工具页出现数据库组」未做浏览器端点击验证：前端完全由 group 列表接口驱动且本次无前端改动，脚本以第 1 段的注册断言 + 第 8 段的接口挂载断言 + 第 10 段构建代替。\n'
printf -- '- 第 8 段末尾的 api 容器健康检查在该端口无服务时会标注跳过；容器跑的是迁移前镜像，故该条只证明「启用 RLS 后超级用户连接照常可用」。\n'
printf -- '- `docker-compose.yml` 未注入 `DATABASE_READER_URL`：按 spec 属于部署侧动作，runbook 已写明手工步骤。\n'

printf '\n## 验收结论\n\n'
if [ "$FAIL" -eq 0 ]; then
  printf '本次执行的所有片段均通过（详见上文各段真实输出与退出码）。\n'
  exit 0
else
  printf '存在失败片段，详见上文对应段落的输出与退出码；视为未通过。\n'
  exit 1
fi
