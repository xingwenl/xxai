#!/usr/bin/env python3
"""ai-base 技能包命令行：按 GitHub 源列出并导入技能。

对标 ``npx skills add <source> --skill <name>``，但平台侧**不在服务端执行
npx / git**（后端镜像是 python:3.12-slim，没有 Node 也没有 git；而且
``skills add`` 的产物落在 ``./<agent>/skills/`` 这类本机目录，与平台的
``SkillPackage`` + 受控存储模型对不上）。

本脚本只是一个薄包装，解析仓库、拉取技能目录、校验与落库全部在服务端完成：

* ``POST /api/v1/platforms/{platform_id}/skill-packages/source-skills``
* ``POST /api/v1/platforms/{platform_id}/skill-packages/import-source``

只用标准库实现，因此不需要安装任何依赖。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_API_BASE = "http://127.0.0.1:8000"
SKILLS_ROUTE = "/api/v1/platforms/{platform_id}/skill-packages"
PREVIEW_PATH = SKILLS_ROUTE + "/source-skills"
IMPORT_PATH = SKILLS_ROUTE + "/import-source"
REQUEST_TIMEOUT_SECONDS = 180


class CliError(Exception):
    """面向用户的错误：只打印消息，不打印堆栈。"""


def call(api_base: str, token: str | None, path: str, payload: dict) -> dict:
    url = api_base.rstrip("/") + path
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise CliError(_http_error_message(exc)) from exc
    except urllib.error.URLError as exc:
        raise CliError(f"无法连接 {url}：{exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise CliError("平台返回了无法解析的响应") from exc
    if not isinstance(body, dict) or not body.get("success"):
        message = body.get("message") if isinstance(body, dict) else None
        raise CliError(str(message or "请求失败"))
    return body.get("data") or {}


def _http_error_message(exc: urllib.error.HTTPError) -> str:
    try:
        body = json.loads(exc.read().decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return f"HTTP {exc.code} {exc.reason}"
    if isinstance(body, dict) and body.get("message"):
        return str(body["message"])
    return f"HTTP {exc.code} {exc.reason}"


def apply_ref(source: str, ref: str | None) -> str:
    """把 ``--ref`` 折进来源字符串（服务端只从 tree/<ref> 链接读分支）。"""
    if not ref:
        return source
    stripped = source.strip().rstrip("/")
    if "://" in stripped:
        if "/tree/" not in stripped:
            return f"{stripped}/tree/{ref}"
        head, _, tail = stripped.partition("/tree/")
        rest = tail.split("/", 1)
        suffix = f"/{rest[1]}" if len(rest) > 1 else ""
        return f"{head}/tree/{ref}{suffix}"
    parts = [part for part in stripped.split("/") if part]
    if len(parts) < 2:
        raise CliError("技能来源需形如 owner/repo")
    link = f"https://github.com/{parts[0]}/{parts[1]}/tree/{ref}"
    subpath = "/".join(parts[2:])
    return f"{link}/{subpath}" if subpath else link


def human_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def resolve_selection(skills: list[str], select_all: bool) -> list[str]:
    if select_all:
        return ["*"]
    cleaned = [item.strip() for item in skills if item.strip()]
    if not cleaned:
        raise CliError("请用 --skill 指定要导入的技能，或先用 --list 查看可选技能")
    return cleaned


def print_preview(data: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    items = data.get("skills") or []
    print(f"仓库：{data.get('repository')}@{data.get('ref')}")
    if data.get("subpath"):
        print(f"限定目录：{data['subpath']}")
    print(f"可选技能 {len(items)} 个：")
    if not items:
        print("  （该来源下没有找到含 SKILL.md 的技能目录）")
        return
    width = min(46, max((len(item.get("name", "")) for item in items), default=0))
    for item in items:
        flags = " [含 scripts]" if item.get("has_scripts") else ""
        print(
            f"  {item.get('name', ''):<{width}}  "
            f"{item.get('file_count', 0)} 个文件  "
            f"{human_bytes(int(item.get('total_bytes') or 0))}"
            f"  {item.get('path', '')}{flags}"
        )


def print_import_result(data: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    package = data.get("package") or {}
    print(f"已导入技能包：{package.get('name')}（{package.get('slug')}）")
    print(f"  类型：{package.get('package_type')}")
    skills = package.get("skills") or []
    if skills:
        print("  技能：" + "、".join(str(item.get("name")) for item in skills))
    files = package.get("files") or []
    print(f"  文件数：{len(files)}，脚本执行权限：{'开启' if package.get('allow_script_execution') else '关闭'}")
    for warning in data.get("warnings") or []:
        print(f"  提示：{warning}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="skills",
        description="按 GitHub 源列出并导入 ai-base 技能包（对标 npx skills add）",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(target: argparse.ArgumentParser) -> None:
        target.add_argument("source", help="技能来源，如 owner/repo 或 github.com 仓库链接")
        target.add_argument("--platform", type=int, required=True, help="平台 ID")
        target.add_argument("--ref", help="分支或 tag，等价于链接里的 tree/<ref>")
        target.add_argument(
            "--api-base",
            default=os.getenv("AI_BASE_API_BASE", DEFAULT_API_BASE),
            help=f"平台地址，默认 {DEFAULT_API_BASE}（可用环境变量 AI_BASE_API_BASE）",
        )
        target.add_argument(
            "--token",
            default=os.getenv("AI_BASE_TOKEN"),
            help="管理员 Bearer Token（可用环境变量 AI_BASE_TOKEN）",
        )
        target.add_argument("--json", action="store_true", help="输出原始 JSON")

    list_parser = subparsers.add_parser("list", help="列出源里可选的技能")
    add_common(list_parser)

    add_parser = subparsers.add_parser("add", help="从源导入选中的技能")
    add_common(add_parser)
    add_parser.add_argument(
        "--list", "-l", action="store_true", dest="list_only", help="只列出，不导入"
    )
    add_parser.add_argument(
        "--skill", "-s", action="append", default=[], help="要导入的技能，可重复"
    )
    add_parser.add_argument("--all", action="store_true", help="导入该来源下全部技能")
    add_parser.add_argument("--package-name", help="技能包显示名，默认 <repo>-skills")
    add_parser.add_argument("--yes", "-y", action="store_true", help="跳过确认")

    return parser


def run_preview(args: argparse.Namespace) -> dict:
    source = apply_ref(args.source, args.ref)
    return call(
        args.api_base,
        args.token,
        PREVIEW_PATH.format(platform_id=args.platform),
        {"source": source},
    )


def run_list(args: argparse.Namespace) -> int:
    print_preview(run_preview(args), args.json)
    return 0


def run_add(args: argparse.Namespace) -> int:
    source = apply_ref(args.source, args.ref)
    preview = run_preview(args)
    if args.list_only:
        print_preview(preview, args.json)
        return 0

    selection = resolve_selection(args.skill, args.all)
    if not args.yes and not args.json:
        shown = "全部技能" if selection == ["*"] else "、".join(selection)
        answer = input(f"将从 {preview.get('repository')} 导入 {shown}，继续？[y/N] ")
        if answer.strip().lower() not in {"y", "yes"}:
            print("已取消")
            return 1

    payload: dict = {"source": source, "skills": selection}
    if args.package_name:
        payload["package_name"] = args.package_name
    data = call(
        args.api_base,
        args.token,
        IMPORT_PATH.format(platform_id=args.platform),
        payload,
    )
    print_import_result(data, args.json)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "list":
            return run_list(args)
        return run_add(args)
    except CliError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("已中断", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
