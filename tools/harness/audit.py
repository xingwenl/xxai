#!/usr/bin/env python3
"""Harness v2 request 一致性审计脚本。

校验 `docs/harness/requests/` 下按 v2 机制创建的 request：

- `spec.md` / `verify.md` 的 YAML frontmatter 是否完整、枚举是否合法
- `spec.md` 是否满足规格（行数上限、无超长连续代码块、被否决项非空）
- `verify.md` 是否由脚本产出、是否记录了未执行项
- 分档与产物的对应关系（A 档需 ADR，A/B 档需可执行验证脚本）

**存量跳过**：`CUTOVER_DATE` 之前创建的 request 目录（目录名首段日期早于该日期）
一律跳过，不报错、不告警。这是 v2 与旧六阶段机制并存的边界。

用法：
    python3 tools/harness/audit.py            # 校验新机制 request
    python3 tools/harness/audit.py --all      # 同时列出被跳过的存量 request
    python3 tools/harness/audit.py --strict   # 有 WARN 也以非零码退出
"""

import argparse
import os
import re
import sys
from datetime import date, datetime

REQUESTS_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "docs", "harness", "requests")
)
VERIFY_SCRIPTS_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "verify")
)
ADR_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "docs", "adr")
)

# v2 机制的启用日：早于该日期创建的 request 属于存量，一律跳过。
# 与 docs/harness/HARNESS-V2.md 的「与旧规则的关系」一节保持一致。
CUTOVER_DATE = date(2026, 9, 20)

TIERS = ("A", "B", "C")
RISKS = ("low", "medium", "high")

SPEC_MAX_LINES = 150
SPEC_MAX_CODE_BLOCK_LINES = 30

SPEC_REQUIRED_SECTIONS = (
    "目标与范围",
    "来源与方案比较",
    "被否决的选项",
    "停点判断",
    "变更点",
    "验收标准",
)

FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.S)
SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.M)
CODE_FENCE_RE = re.compile(r"^```", re.M)


def parse_frontmatter(path):
    """返回 (frontmatter 字典, 正文, 错误列表)。

    frontmatter 只支持本仓库用到的简单 YAML 子集：标量、行内数组、
    以及一层嵌套。不引入 PyYAML 依赖，避免审计脚本对环境有额外要求。
    """
    with open(path, encoding="utf-8") as f:
        text = f.read()

    match = FRONTMATTER_RE.match(text)
    if not match:
        return None, text, ["缺少 YAML frontmatter（文件需以 `---` 开头）"]

    data = {}
    stack = [(-1, data)]
    errors = []
    for raw_line in match.group(1).splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        if ":" not in line:
            errors.append(f"frontmatter 无法解析的行：{line!r}")
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()

        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            errors.append(f"frontmatter 缩进异常：{line!r}")
            stack = [(-1, data)]

        if value == "":
            child = {}
            stack[-1][1][key] = child
            stack.append((indent, child))
        else:
            stack[-1][1][key] = _coerce(value)

    return data, text[match.end():], errors


def _coerce(value):
    """把 frontmatter 标量转成 Python 值。"""
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_coerce(item.strip()) for item in inner.split(",")]
    if value in ("true", "false"):
        return value == "true"
    if value in ("null", "~"):
        return None
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def count_longest_code_block(text):
    """返回正文中最长连续代码块的行数（不含围栏本身）。"""
    longest = current = 0
    inside = False
    for line in text.splitlines():
        if CODE_FENCE_RE.match(line):
            inside = not inside
            if not inside:
                longest = max(longest, current)
                current = 0
            continue
        if inside:
            current += 1
    return max(longest, current)


def request_date(request_id):
    """从 `<YYYY-MM-DD>-<topic>` 形式的目录名解析日期；解析失败返回 None。"""
    match = re.match(r"^(\d{4}-\d{2}-\d{2})-", request_id)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y-%m-%d").date()
    except ValueError:
        return None


def is_legacy(request_id):
    """判断是否属于 v2 生效前创建的存量 request。"""
    created = request_date(request_id)
    if created is None:
        # 命名不符合 v2 约定，无法确认属于新机制，按存量处理以免误报。
        return True
    return created < CUTOVER_DATE


def audit_request(request_id, req_dir):
    """校验单个 v2 request，返回 (errors, warnings)。"""
    errors, warnings = [], []
    files = set(os.listdir(req_dir))

    spec_path = os.path.join(req_dir, "spec.md")
    verify_path = os.path.join(req_dir, "verify.md")

    if "spec.md" not in files:
        errors.append(f"{request_id}: v2 request 缺少 spec.md")
    if "verify.md" not in files:
        errors.append(f"{request_id}: v2 request 缺少 verify.md")
    if errors:
        return errors, warnings

    meta, body, fm_errors = parse_frontmatter(spec_path)
    errors.extend(f"{request_id}: {e}" for e in fm_errors)
    if meta is None:
        return errors, warnings

    tier = meta.get("tier")
    if tier not in TIERS:
        errors.append(f"{request_id}: spec.md frontmatter tier 非法值 {tier!r}（应为 {TIERS}）")
        tier = None
    if meta.get("risk") not in RISKS:
        errors.append(f"{request_id}: spec.md frontmatter risk 非法值 {meta.get('risk')!r}（应为 {RISKS}）")
    for field in ("id", "approval"):
        if field not in meta:
            errors.append(f"{request_id}: spec.md frontmatter 缺少 {field}")

    approval = meta.get("approval")
    if isinstance(approval, dict):
        for field in ("required", "granted"):
            if field not in approval:
                errors.append(f"{request_id}: spec.md approval 缺少 {field}")
        if tier in ("A", "B") and approval.get("required") is not True:
            warnings.append(
                f"{request_id}: tier={tier} 但 approval.required 不是 true；A/B 档必须经人工确认"
            )
    elif "approval" in meta:
        errors.append(f"{request_id}: spec.md approval 应为映射（含 required/granted/why）")

    # spec.md 规格：行数与骨架
    spec_lines = len(open(spec_path, encoding="utf-8").read().splitlines())
    if spec_lines > SPEC_MAX_LINES:
        errors.append(f"{request_id}: spec.md 共 {spec_lines} 行，超过上限 {SPEC_MAX_LINES} 行")

    longest_block = count_longest_code_block(body)
    if longest_block > SPEC_MAX_CODE_BLOCK_LINES:
        errors.append(
            f"{request_id}: spec.md 存在 {longest_block} 行连续代码块，"
            f"超过上限 {SPEC_MAX_CODE_BLOCK_LINES} 行（实现细节留给代码）"
        )

    headings = set(SECTION_RE.findall(body))
    for section in SPEC_REQUIRED_SECTIONS:
        if section not in headings:
            errors.append(f"{request_id}: spec.md 缺少必需章节「{section}」")

    rejected = _section_body(body, "被否决的选项")
    if not _has_content(rejected):
        errors.append(f"{request_id}: spec.md「被否决的选项」为空；必须记录被否决方案与理由")

    # verify.md 规格
    vm, vbody, vfm_errors = parse_frontmatter(verify_path)
    if vfm_errors:
        errors.extend(f"{request_id}: verify.md {e}" for e in vfm_errors)
    if vm is None or vm.get("source") != "script":
        errors.append(
            f"{request_id}: verify.md 的 frontmatter 需为 source: script（内容由验证脚本产出）"
        )
    for section in ("已执行的命令与结果", "未执行项与原因", "验收结论"):
        if section not in set(SECTION_RE.findall(vbody)):
            errors.append(f"{request_id}: verify.md 缺少必需章节「{section}」")

    # 分档与产物对应
    script_path = os.path.join(VERIFY_SCRIPTS_DIR, f"{request_id}.sh")
    if tier in ("A", "B"):
        if not os.path.isfile(script_path):
            errors.append(f"{request_id}: tier={tier} 但缺少 tools/harness/verify/{request_id}.sh")
        elif not os.access(script_path, os.X_OK):
            errors.append(f"{request_id}: tools/harness/verify/{request_id}.sh 不可执行（chmod +x）")
    if tier == "A" and not _has_adr(request_id):
        errors.append(
            f"{request_id}: tier=A 但 docs/adr/ 下未见与本 request 关联的 ADR"
            "（若三条判据未同时成立，请在 spec.md 说明为何不写）"
        )

    return errors, warnings


def _has_content(section_text):
    """判断章节是否只有占位内容。"""
    return len(re.sub(r"[-*\s>]", "", section_text)) > 0


def _section_body(body, title):
    """取出 `## <title>` 到下一个 `##` 之间的正文。"""
    match = re.search(rf"^##\s+{re.escape(title)}\s*$", body, re.M)
    if not match:
        return ""
    rest = body[match.end():]
    nxt = SECTION_RE.search(rest)
    return rest[: nxt.start()] if nxt else rest


def _has_adr(request_id):
    """检查 docs/adr/ 下是否有引用该 request 的 ADR。"""
    if not os.path.isdir(ADR_DIR):
        return False
    for name in sorted(os.listdir(ADR_DIR)):
        if not name.endswith(".md"):
            continue
        try:
            with open(os.path.join(ADR_DIR, name), encoding="utf-8") as f:
                if request_id in f.read():
                    return True
        except OSError:
            continue
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Harness v2 request 一致性审计")
    parser.add_argument("--all", action="store_true", help="同时列出被跳过的存量 request")
    parser.add_argument("--strict", action="store_true", help="存在 WARN 时也以非零码退出")
    args = parser.parse_args()

    if not os.path.isdir(REQUESTS_DIR):
        print(f"未找到 request 目录：{REQUESTS_DIR}")
        return 2

    request_ids = sorted(os.listdir(REQUESTS_DIR))
    all_errors, all_warnings, skipped = [], [], []

    for request_id in request_ids:
        req_dir = os.path.join(REQUESTS_DIR, request_id)
        if not os.path.isdir(req_dir):
            continue
        if is_legacy(request_id):
            skipped.append(request_id)
            continue
        errors, warnings = audit_request(request_id, req_dir)
        all_errors.extend(errors)
        all_warnings.extend(warnings)

    for line in all_errors:
        print(f"ERROR  {line}")
    for line in all_warnings:
        print(f"WARN   {line}")
    if args.all:
        for request_id in skipped:
            print(f"SKIP   {request_id}（v2 生效前创建，存量不校验）")

    audited = len(request_ids) - len(skipped)
    print(
        f"\nv2 requests: {audited}  存量跳过: {len(skipped)}  "
        f"ERROR: {len(all_errors)}  WARN: {len(all_warnings)}"
    )

    if all_errors:
        return 1
    if args.strict and all_warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
