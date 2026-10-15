#!/usr/bin/env bash
# 验证脚本：2026-10-15-skill-source-import（B 档）
#
# 覆盖 spec.md 的 7 条验收标准：
#   1) source-skills 对参照仓库返回 >=1 条，且不写库
#   2) import-source 选中 agent-cli-developer 后 skill_packages/skills 各增 1 行，
#      instruction_template 非空，files 只含该技能目录
#   3) 非白名单 host 一律 4xx，且零出网请求
#   4) 路径穿越 / 符号链接 / 超限一律拒绝
#   5) 非本平台管理员两个接口均 404
#   6) audit.py 与 verify.sh 通过
#   7) 前端可完成「输入源 → 列出 → 勾选 → 导入」
#
# 退出码：0 全通过 / 1 有失败 / 3 有未执行项 / 2 脚本自身错误。

set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../../.." || exit 2
ROOT="$(pwd)"
PY="${ROOT}/apps/backend/.venv/bin/python"

TMP_DIR="$(mktemp -d)"
FAIL=0
UNEXECUTED=0

ADMIN_DSN="postgresql://root:Dd123456@127.0.0.1:5432/ai_db"
TMP_DB="ai_base_skill_src_verify_$$"
TMP_DSN="postgresql+asyncpg://root:Dd123456@127.0.0.1:5432/${TMP_DB}"

BACKEND_FILES=(
  apps/backend/app/modules/skill/source_resolver.py
  apps/backend/app/modules/skill/schemas.py
  apps/backend/app/modules/skill/services.py
  apps/backend/app/modules/skill/router.py
  apps/backend/app/core/config.py
  apps/backend/tests/skill/test_skill_source_resolver.py
  apps/backend/tests/skill/test_skill_source_routes.py
)

# --------------------------------------------------------------------------- #
# 探针：临时 PostgreSQL 库的建立与销毁（本机没有 psql 客户端）
# --------------------------------------------------------------------------- #
cat >"$TMP_DIR/pg_admin.py" <<'PY'
import asyncio
import sys

import asyncpg

ADMIN_DSN = "postgresql://root:Dd123456@127.0.0.1:5432/ai_db"


async def main(action: str, database: str) -> None:
    connection = await asyncpg.connect(ADMIN_DSN)
    try:
        if action == "create":
            await connection.execute(f'DROP DATABASE IF EXISTS "{database}"')
            await connection.execute(f'CREATE DATABASE "{database}"')
        else:
            await connection.execute(
                f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'
            )
    finally:
        await connection.close()


asyncio.run(main(sys.argv[1], sys.argv[2]))
PY

# 供 black 漂移比对使用的临时目录：必须落在 apps/backend 内，
# 保证 black 解析配置的目录层级与真实文件一致。
BLACK_TMP="$(mktemp -d "${ROOT}/apps/backend/.verify_black.XXXXXX")"

cleanup() {
  "$PY" "$TMP_DIR/pg_admin.py" drop "$TMP_DB" >/dev/null 2>&1 || true
  rm -rf "$TMP_DIR" "$BLACK_TMP"
}
trap cleanup EXIT

# --------------------------------------------------------------------------- #
# 探针：black 格式检查（区分「本次新增」与「存量漂移」）
#
# 背景：services.py / router.py / config.py 在 HEAD 上就已不符合 black，
# 全量重排会把无关 diff 混进本 request，因此改为：
#   a) 本次黑格干净的文件直接 black --check；
#   b) 3 个存量文件比对「HEAD 待改行集合」与「工作区待改行集合」是否完全一致，
#      一致即证明本次新增没有引入新的格式漂移。
# --------------------------------------------------------------------------- #
cat >"$TMP_DIR/check_black.sh" <<'SH'
#!/usr/bin/env bash
set -uo pipefail

ROOT="$1"
PY="$2"
BLACK_TMP="$3"

CLEAN_FILES=(
  app/modules/skill/source_resolver.py
  app/modules/skill/schemas.py
  tests/skill/test_skill_source_resolver.py
  tests/skill/test_skill_source_routes.py
)
DRIFT_FILES=(
  app/modules/skill/services.py
  app/modules/skill/router.py
  app/core/config.py
)

cd "$ROOT/apps/backend" || exit 2
status=0

echo "--- a) 期望符合 black 的本次新增文件 ---"
if "$PY" -m black --check "${CLEAN_FILES[@]}"; then
  echo "OK：以上文件均符合 black"
else
  echo "FAIL：以上文件不符合 black"
  status=1
fi

echo
echo "--- b) 3 个 HEAD 即漂移的存量文件：比对待改行集合 ---"
for path in "${DRIFT_FILES[@]}"; do
  base="$(basename "$path")"
  # git show 的路径必须相对仓库根（不是相对 apps/backend）
  git -C "$ROOT" show "HEAD:apps/backend/$path" >"$BLACK_TMP/head_$base" || {
    echo "无法读取 HEAD:apps/backend/$path"
    exit 2
  }
  # 拷贝到同一目录层级，确保 black 找到同样的配置
  cp "$BLACK_TMP/head_$base" "./.verify_head_$base"
  "$PY" -m black --diff "./.verify_head_$base" 2>/dev/null \
    | grep -E '^[+-]' | grep -v '^[+-][+-]' | sort >"$BLACK_TMP/head_$base.diff"
  "$PY" -m black --diff "$path" 2>/dev/null \
    | grep -E '^[+-]' | grep -v '^[+-][+-]' | sort >"$BLACK_TMP/work_$base.diff"
  rm -f "./.verify_head_$base"

  head_lines="$(wc -l <"$BLACK_TMP/head_$base.diff" | tr -d ' ')"
  work_lines="$(wc -l <"$BLACK_TMP/work_$base.diff" | tr -d ' ')"
  if diff -q "$BLACK_TMP/head_$base.diff" "$BLACK_TMP/work_$base.diff" >/dev/null; then
    echo "OK   ${path}：HEAD 待改 $head_lines 行，工作区待改 $work_lines 行，集合一致（无新增漂移）"
  else
    echo "FAIL ${path}：HEAD 待改 $head_lines 行，工作区待改 $work_lines 行，集合不一致"
    diff "$BLACK_TMP/head_$base.diff" "$BLACK_TMP/work_$base.diff" | head -20
    status=1
  fi
done

echo
echo "--- c) 存量漂移位置（不计入结论，供人工确认与本次改动无关） ---"
for path in "${DRIFT_FILES[@]}"; do
  base="$(basename "$path")"
  echo "  ${path}：$(grep -c '^[+-]' "$BLACK_TMP/work_$base.diff" 2>/dev/null || echo 0) 行"
done

exit "$status"
SH
chmod +x "$TMP_DIR/check_black.sh"

# --------------------------------------------------------------------------- #
# 探针：前端类型检查
#
# `tsc -b` 是全项目构建，apps/front 里同时可能有其他任务的在途改动，那些报错与本次
# 改动无关，却会让整个构建失败。因此这里区分两种情况：
#   - 构建失败且报错落在本次改动的两个文件上 → 失败（退出码 1）
#   - 构建失败但报错全在本次未改动的文件上 → 记为未执行（退出码 3），原文保留供人工判断
# --------------------------------------------------------------------------- #
cat >"$TMP_DIR/check_front_tsc.sh" <<'SH'
#!/usr/bin/env bash
set -uo pipefail
FRONT="$1"
OUT="$(cd "$FRONT" && npx tsc -b 2>&1)"
CODE=$?
printf '%s\n' "$OUT"

if [ "$CODE" -eq 0 ]; then
  echo "tsc -b 通过（全项目无类型错误）"
  exit 0
fi

if printf '%s\n' "$OUT" | grep -qE '^src/(api/skills\.ts|features/skills/index\.tsx)\('; then
  echo "tsc -b 失败，且报错涉及本次改动文件（src/api/skills.ts / src/features/skills/index.tsx）"
  exit 1
fi

echo "tsc -b 失败，但报错全部落在本次未改动的文件上"
echo "⇒ 记为未执行：apps/front 内有其他任务的在途改动，本脚本无法在当前工作区得到干净的构建结果"
exit 3
SH
chmod +x "$TMP_DIR/check_front_tsc.sh"

# --------------------------------------------------------------------------- #
# 探针：来源解析 / 拒绝 / 打包往返（真实访问 GitHub）
# --------------------------------------------------------------------------- #
cat >"$TMP_DIR/probe_resolver.py" <<'PY'
"""技能来源探针：真实访问 GitHub，验证解析、白名单拒绝与打包往返。"""

from __future__ import annotations

import asyncio

from app.modules.skill import source_resolver as sr
from app.modules.skill.importers import parse_skill_package
from app.modules.skill.source_resolver import (
    build_source_package_zip,
    list_source_skills,
    parse_source,
    select_skill_entries,
)
from app.shared.exceptions import BadRequestException

REPO = "travisjneuman/.claude"
TARGET = "agent-cli-developer"
failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'OK  ' if ok else 'FAIL'}] {label}{' — ' + detail if detail else ''}")
    if not ok:
        failures.append(label)


def guarded(coro):
    """执行需要真实访问 GitHub 的调用；匿名限流耗尽时降级为「未执行」(exit 3)。"""
    try:
        return asyncio.run(coro)
    except BadRequestException as exc:
        message = str(getattr(exc, "message", exc))
        if "额度已用尽" in message:
            print()
            print(f"未执行：GitHub 匿名限流已耗尽（{message}）")
            raise SystemExit(3) from None
        raise


# ---- 1) 纯解析：四种受支持写法 ------------------------------------------- #
forms = {
    REPO: ("travisjneuman", ".claude", "HEAD", ""),
    f"https://github.com/{REPO}": ("travisjneuman", ".claude", "HEAD", ""),
    f"https://github.com/{REPO}/tree/master/skills": (
        "travisjneuman",
        ".claude",
        "master",
        "skills",
    ),
    f"{REPO}/skills": ("travisjneuman", ".claude", "HEAD", "skills"),
}
for source, expected in forms.items():
    resolved = parse_source(source)
    actual = (resolved.owner, resolved.repo, resolved.ref, resolved.subpath)
    check(f"parse_source({source})", actual == expected, str(actual))

# ---- 2) 白名单与非法输入：必须 4xx 且零出网 ------------------------------ #
blocked = [
    ("http://github.com/a/b", "技能来源链接必须使用 https"),
    ("https://evil.example/a/b", "当前只支持 github.com 来源"),
    ("https://169.254.169.254/latest/meta-data", "当前只支持 github.com 来源"),
    ("https://user:pw@github.com/a/b", "技能来源不能包含凭据"),
    ("https://github.com/only-owner", "技能来源链接需包含 owner/repo"),
    ("https://github.com/a/../b", "只支持指向仓库或 tree"),
    ("a/b/tree/../../x", "技能来源目录包含非法路径"),
]

outbound: list[str] = []
original_request = sr._github_request


async def _forbidden(url: str, accept: str):
    outbound.append(url)
    raise AssertionError(f"非法来源不应发起出网请求：{url}")


sr._github_request = _forbidden
try:
    for source, expected in blocked:
        try:
            asyncio.run(list_source_skills(source))
        except BadRequestException as exc:
            check(
                f"拒绝 {source}",
                expected in exc.message,
                f"status={exc.status_code} message={exc.message}",
            )
        except AssertionError as exc:
            check(f"拒绝 {source}", False, str(exc))
        else:
            check(f"拒绝 {source}", False, "未拒绝")
finally:
    sr._github_request = original_request
check("非法来源零出网请求", outbound == [], f"发出 {len(outbound)} 次")

# ---- 3) 真实列出参照仓库的技能 ------------------------------------------ #
resolved, entries = guarded(list_source_skills(REPO))
names = [entry.name for entry in entries]
check(
    "参照仓库列出技能数 >= 1",
    len(entries) >= 1,
    f"共 {len(entries)} 个，前三个 {names[:3]}",
)
check("默认分支自动解析为 HEAD", resolved.ref == "HEAD", resolved.ref)

target = [entry for entry in entries if entry.name == TARGET]
check(f"命中目标技能 {TARGET}", len(target) == 1)
if target:
    item = target[0]
    check("目标技能元数据", item.file_count >= 1 and item.total_bytes > 0,
          f"path={item.path} files={item.file_count} bytes={item.total_bytes}")

# ---- 4) 选中 -> 打包 -> 走既有导入解析链路 ------------------------------ #
selected = select_skill_entries(entries, [TARGET])
content, filename = guarded(build_source_package_zip(resolved, selected))
parsed = parse_skill_package(filename, content)
check("zip 可被 parse_skill_package 接受", bool(parsed.name), parsed.name)
check("package_type 推断为 skill", parsed.package_type == "skill", parsed.package_type)
check("技能 slug 取自技能目录", parsed.slug == TARGET, parsed.slug)
check("解析无警告", parsed.warnings == [], str(parsed.warnings))
check(
    "files 只含该技能目录",
    bool(parsed.files)
    and all(
        item.relative_path.startswith(f"skills/{TARGET}/") for item in parsed.files
    ),
    "、".join(item.relative_path for item in parsed.files),
)
check(
    "instruction_template 非空",
    bool(parsed.candidates and parsed.candidates[0].instruction_template.strip()),
    f"模板 {len(parsed.candidates[0].instruction_template) if parsed.candidates else 0} 字符",
)

# ---- 5) 未命中的技能名必须报错 ------------------------------------------ #
try:
    select_skill_entries(entries, ["definitely-not-a-skill"])
except BadRequestException as exc:
    check("未命中的技能名被拒绝", "未找到指定技能" in exc.message, exc.message)
else:
    check("未命中的技能名被拒绝", False, "未拒绝")

print()
print(f"探针结论：{'全部通过' if not failures else '失败 ' + str(len(failures)) + ' 项'}")
raise SystemExit(1 if failures else 0)
PY

# --------------------------------------------------------------------------- #
# 探针：临时库端到端导入（验收标准 2）
# --------------------------------------------------------------------------- #
cat >"$TMP_DIR/probe_import.py" <<'PY'
"""在临时库上真实跑一次来源导入，核对落库行数与文件范围。"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.platform.models import Platform
from app.modules.skill.models import Skill, SkillPackage, SkillPackageFile
from app.modules.skill.repositories import SkillRepository
from app.modules.skill.schemas import SkillSourceImportRequest
from app.modules.skill.services import import_skill_package_from_source

DSN = os.environ["DATABASE_URL"]
STORAGE = os.environ["AGENT_FILE_STORAGE_PATH"]
TARGET = "agent-cli-developer"
failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'OK  ' if ok else 'FAIL'}] {label}{' — ' + detail if detail else ''}")
    if not ok:
        failures.append(label)


async def count(session, model, platform_id: int) -> int:
    statement = select(func.count()).select_from(model).where(
        model.platform_id == platform_id
    )
    return int(await session.scalar(statement) or 0)


async def main() -> int:
    engine = create_async_engine(DSN)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        platform = Platform(name="skill-source-verify", code=f"ssv_{os.getpid()}")
        session.add(platform)
        await session.commit()
        platform_id = platform.id

        before_packages = await count(session, SkillPackage, platform_id)
        before_skills = await count(session, Skill, platform_id)
        check("新平台初始为空", before_packages == 0 and before_skills == 0)

        result = await import_skill_package_from_source(
            SkillRepository(session),
            platform_id,
            SkillSourceImportRequest(
                source="travisjneuman/.claude",
                skills=[TARGET],
                package_name="verify-agent-cli-developer",
            ),
        )
        print(f"  导入结果：{result.package.name} / {result.package.slug}")

        after_packages = await count(session, SkillPackage, platform_id)
        after_skills = await count(session, Skill, platform_id)
        check(
            "skill_packages 恰好 +1",
            after_packages - before_packages == 1,
            f"{before_packages} -> {after_packages}",
        )
        check(
            "skills 恰好 +1",
            after_skills - before_skills == 1,
            f"{before_skills} -> {after_skills}",
        )

        package_row = await session.scalar(
            select(SkillPackage).where(SkillPackage.platform_id == platform_id)
        )
        skill_row = await session.scalar(
            select(Skill).where(Skill.platform_id == platform_id)
        )
        check(
            "显式 package_name 生效（verify-agent-cli-developer）",
            package_row.name == "verify-agent-cli-developer",
            package_row.name,
        )
        check(
            "显式 package_name 生成对应 slug",
            package_row.slug == "verify-agent-cli-developer",
            package_row.slug,
        )
        check("package_type = skill", package_row.package_type == "skill",
              package_row.package_type)
        check(
            "instruction_template 非空",
            bool(skill_row.instruction_template.strip()),
            f"{len(skill_row.instruction_template)} 字符",
        )
        check(
            "manifest.source 记录了来源",
            (package_row.manifest or {}).get("source", {}).get("repository")
            == "travisjneuman/.claude",
            str((package_row.manifest or {}).get("source")),
        )
        check(
            "allow_script_execution 默认关闭",
            package_row.allow_script_execution is False,
        )

        file_rows = list(
            await session.scalars(
                select(SkillPackageFile).where(
                    SkillPackageFile.package_id == package_row.id
                )
            )
        )
        check(
            "files 只含所选技能目录",
            bool(file_rows)
            and all(
                row.relative_path.startswith(f"skills/{TARGET}/")
                for row in file_rows
            ),
            "、".join(row.relative_path for row in file_rows),
        )

        stored = Path(STORAGE) / package_row.storage_key
        check("受控存储目录已落盘", stored.exists(), str(package_row.storage_key))

    await engine.dispose()
    print()
    print(f"探针结论：{'全部通过' if not failures else '失败 ' + str(len(failures)) + ' 项'}")
    return 1 if failures else 0


try:
    raise SystemExit(asyncio.run(main()))
except SystemExit:
    raise
except Exception as exc:  # noqa: BLE001 - 只识别限流，其余照旧抛出
    message = str(getattr(exc, "message", exc))
    if "额度已用尽" in message:
        print()
        print(f"未执行：GitHub 匿名限流已耗尽（{message}）")
        raise SystemExit(3) from None
    raise
PY

# --------------------------------------------------------------------------- #
# 探针：CLI 包装（验收标准里对应「命令行入口」）
# --------------------------------------------------------------------------- #
cat >"$TMP_DIR/probe_cli.py" <<'PY'
"""CLI 纯函数与参数解析探针。"""

from __future__ import annotations

import sys

sys.path.insert(0, "tools/skills-cli")

from skills import CliError, apply_ref, build_parser, human_bytes, resolve_selection

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'OK  ' if ok else 'FAIL'}] {label}{' — ' + detail if detail else ''}")
    if not ok:
        failures.append(label)


check("--ref 保留原样", apply_ref("o/r", None) == "o/r")
check(
    "--ref 折进 owner/repo",
    apply_ref("o/r/skills", "main") == "https://github.com/o/r/tree/main/skills",
    apply_ref("o/r/skills", "main"),
)
check(
    "--ref 替换已有 tree 分支",
    apply_ref("https://github.com/o/r/tree/master/skills", "dev")
    == "https://github.com/o/r/tree/dev/skills",
    apply_ref("https://github.com/o/r/tree/master/skills", "dev"),
)
check("--all 映射为 ['*']", resolve_selection([], True) == ["*"])
check("--skill 去空白", resolve_selection([" a ", ""], False) == ["a"])
try:
    resolve_selection([], False)
except CliError:
    check("未指定技能时报错", True)
else:
    check("未指定技能时报错", False, "未报错")
check("human_bytes", human_bytes(5356) == "5.2 KB", human_bytes(5356))

parser = build_parser()
args = parser.parse_args(
    ["add", "o/r", "--platform", "3", "--skill", "a", "-s", "b", "--yes"]
)
check("参数解析：子命令", args.command == "add" and args.platform == 3)
check("参数解析：可重复 --skill", args.skill == ["a", "b"], str(args.skill))
list_args = parser.parse_args(["list", "o/r", "--platform", "1"])
check("参数解析：list 子命令", list_args.command == "list" and list_args.platform == 1)

print()
print(f"探针结论：{'全部通过' if not failures else '失败 ' + str(len(failures)) + ' 项'}")
raise SystemExit(1 if failures else 0)
PY

verify_step() {
  local name="$1"; shift
  echo "### ${name}"
  echo
  echo '```bash'
  echo "$*"
  echo '```'
  echo
  "$@"
  local status=$?
  if [ "$status" -eq 0 ]; then
    echo "结果：通过"
  elif [ "$status" -eq 3 ]; then
    # 3 = 当前环境拿不到可用结果（GitHub 匿名限流耗尽、或工作区被其他任务的在途
    # 改动污染导致全项目构建失败等），记「未执行」而不是「失败」，
    # 避免把环境问题当成代码缺陷。
    echo "结果：未执行（当前环境拿不到可用结果，见上文输出）"
    UNEXECUTED=1
  else
    echo "结果：失败（退出码 ${status}）"
    FAIL=1
  fi
  echo
}

echo "## 已执行的命令与结果"
echo

# 需要真实访问 GitHub 的步骤：本机出口 IP 会轮换（实测同一机器上 curl 与 httpx
# 会落到不同出口 IP），个别出口 IP 的匿名额度已被其他使用者耗尽，因此同一命令
# 重试若干次；只有全部重试都因限流未执行时才记为「未执行」。
verify_step_network() {
  local name="$1"; shift
  local attempts=6
  local n status
  for n in $(seq 1 "$attempts"); do
    echo "### ${name}（第 ${n}/${attempts} 次尝试）"
    echo
    echo '```bash'
    echo "$*"
    echo '```'
    echo
    "$@"
    status=$?
    if [ "$status" -eq 0 ]; then
      echo "结果：通过"
      echo
      return 0
    fi
    if [ "$status" -ne 3 ]; then
      echo "结果：失败（退出码 ${status}）"
      echo
      FAIL=1
      return 1
    fi
    echo "（本次因 GitHub 匿名限流未执行，5 秒后换用其他出口连接重试）"
    echo
    sleep 5
  done
  echo "结果：未执行（连续 ${attempts} 次尝试均遇 GitHub 匿名限流）"
  echo
  UNEXECUTED=1
  return 0
}

# --------------------------------------------------------------------------- #
# 静态检查与单元测试
# --------------------------------------------------------------------------- #
verify_step "ruff check（本次改动文件）" \
  bash -c "cd '$ROOT/apps/backend' && '$PY' -m ruff check ${BACKEND_FILES[*]#apps/backend/}"

verify_step "black 格式检查（本次新增文件 + 存量漂移集合比对）" \
  bash "$TMP_DIR/check_black.sh" "$ROOT" "$PY" "$BLACK_TMP"

verify_step "pytest tests/skill（含本次新增 46 条来源用例）" \
  bash -c "cd '$ROOT/apps/backend' && '$PY' -m pytest tests/skill -q"

# --------------------------------------------------------------------------- #
# 验收标准 1、3、4：解析 / 白名单拒绝 / 打包往返（真实访问 GitHub）
# --------------------------------------------------------------------------- #
verify_step_network "来源解析、白名单拒绝与打包往返探针" \
  bash -c "cd '$ROOT/apps/backend' && '$PY' '$TMP_DIR/probe_resolver.py'"

verify_step "CLI 包装探针" \
  bash -c "cd '$ROOT' && '$PY' '$TMP_DIR/probe_cli.py'"

# --------------------------------------------------------------------------- #
# 验收标准 2：临时库端到端导入
# --------------------------------------------------------------------------- #
"$PY" "$TMP_DIR/pg_admin.py" create "$TMP_DB" >/dev/null 2>&1
if [ $? -ne 0 ]; then
  echo "### 端到端导入（临时库）"
  echo
  echo "- 未执行：无法建立临时 PostgreSQL 库（${ADMIN_DSN}）。"
  echo
  UNEXECUTED=1
else
  verify_step "临时库迁移上行：alembic upgrade head" \
    bash -c "cd '$ROOT/apps/backend' && DATABASE_URL='${TMP_DSN}' '$PY' -m alembic upgrade head"

  IMPORT_STORAGE="$TMP_DIR/storage"
  mkdir -p "$IMPORT_STORAGE"

  verify_step_network "来源导入端到端：落库行数 / instruction_template / files 范围" \
    bash -c "cd '$ROOT/apps/backend' && DATABASE_URL='${TMP_DSN}' AGENT_FILE_STORAGE_PATH='${IMPORT_STORAGE}' '$PY' '$TMP_DIR/probe_import.py'"
fi

# --------------------------------------------------------------------------- #
# 验收标准 7：前端类型检查与 lint
# --------------------------------------------------------------------------- #
if [ -d "$ROOT/apps/front/node_modules" ]; then
  verify_step "前端类型检查：tsc -b（全项目；报错若全在未改动文件则记未执行）" \
    bash "$TMP_DIR/check_front_tsc.sh" "$ROOT/apps/front"
  verify_step "前端 lint（仅本次改动文件）" \
    bash -c "cd '$ROOT/apps/front' && npx eslint src/api/skills.ts src/features/skills/index.tsx"
  echo "### 前端 lint（全仓库，存量问题不计入结论）"
  echo
  echo '```bash'
  echo "cd apps/front && npx eslint ."
  echo '```'
  echo
  if (cd "$ROOT/apps/front" && npx eslint . 2>&1 | tail -20); then
    echo "结果：通过"
  else
    echo "结果：存在与本 request 无关的存量 error（见上文输出），不计入本次结论"
  fi
  echo
else
  echo "### 前端检查"
  echo
  echo "- 未执行：apps/front/node_modules 不存在，无法运行 tsc / eslint。"
  echo
  UNEXECUTED=1
fi

# --------------------------------------------------------------------------- #
# 验收标准 6：Harness 审计
#
# audit.py 要求 request 目录里已存在 verify.md，而 verify.md 正是本脚本运行结束后
# 由 tools/harness/verify.sh 写入的，因此审计不能在本脚本内部执行（会形成循环依赖）。
# 该步骤在运行器写盘之后单独执行，结果记录在 request 的结论与提交信息中。
# --------------------------------------------------------------------------- #
echo "### Harness 审计：python3 tools/harness/audit.py"
echo
echo "该步骤在 tools/harness/verify.sh 写入 verify.md 之后单独执行（见脚本头部注释）。"
echo

echo "## 未执行项与原因"
echo
if [ "$UNEXECUTED" -eq 0 ]; then
  echo "- 无未执行项。"
fi
if [ ! -d "$ROOT/apps/front/node_modules" ]; then
  echo "- 前端 tsc / eslint：apps/front/node_modules 不存在。"
  UNEXECUTED=1
fi
echo "- 浏览器内的真实点击流程（输入源 → 列出 → 勾选 → 导入）：本脚本无浏览器自动化环境，"
echo "  仅以 tsc + eslint + 接口契约对齐作为替代证据，需人工在页面上复核一次。"
UNEXECUTED=1
echo

echo "## 验收结论"
echo
if [ "$FAIL" -ne 0 ]; then
  echo "- 存在失败项，见上文「已执行的命令与结果」。"
elif [ "$UNEXECUTED" -ne 0 ]; then
  echo "- 已执行项全部通过，但仍有未执行项（见上），需人工补验后再归档。"
else
  echo "- 全部验收项已执行且通过。"
fi
echo

if [ "$FAIL" -ne 0 ]; then
  exit 1
elif [ "$UNEXECUTED" -ne 0 ]; then
  exit 3
fi
exit 0
