"""技能来源解析与选择的纯逻辑用例（不访问网络、不依赖数据库）。"""

from __future__ import annotations

import asyncio
import zipfile
from io import BytesIO

import pytest
from pydantic import ValidationError

from app.modules.skill import source_resolver
from app.modules.skill.schemas import (
    SkillSourceImportRequest,
    SkillSourcePreviewRequest,
)
from app.modules.skill.source_resolver import (
    ResolvedSource,
    SourceSkillEntry,
    _blob_entries,
    _collect_skill_entries,
    _ensure_safe_member_path,
    parse_source,
    select_skill_entries,
)
from app.shared.exceptions import BadRequestException


def test_parse_source_accepts_supported_forms() -> None:
    assert parse_source("travisjneuman/.claude") == ResolvedSource(
        owner="travisjneuman", repo=".claude", ref="HEAD", subpath=""
    )
    assert parse_source("https://github.com/travisjneuman/.claude") == ResolvedSource(
        owner="travisjneuman", repo=".claude", ref="HEAD", subpath=""
    )
    assert parse_source(
        "https://github.com/travisjneuman/.claude/tree/master/skills"
    ) == ResolvedSource(
        owner="travisjneuman", repo=".claude", ref="master", subpath="skills"
    )
    assert parse_source("travisjneuman/.claude/skills") == ResolvedSource(
        owner="travisjneuman", repo=".claude", ref="HEAD", subpath="skills"
    )


def test_parse_source_strips_git_suffix_and_trailing_slash() -> None:
    assert parse_source("travisjneuman/.claude.git/") == ResolvedSource(
        owner="travisjneuman", repo=".claude", ref="HEAD", subpath=""
    )


def test_resolved_source_repository_property() -> None:
    resolved = parse_source("travisjneuman/.claude")
    assert resolved.repository == "travisjneuman/.claude"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("", "技能来源不能为空"),
        ("http://github.com/a/b", "技能来源链接必须使用 https"),
        ("https://evil.example/a/b", "当前只支持 github.com 来源"),
        ("https://169.254.169.254/latest/meta-data", "当前只支持 github.com 来源"),
        ("https://user:pw@github.com/a/b", "技能来源不能包含凭据"),
        ("https://github.com/only-owner", "技能来源链接需包含 owner/repo"),
        ("https://github.com/only-owner/repo/issues", "只支持指向仓库或 tree"),
        ("https://github.com/a/../b", "只支持指向仓库或 tree"),
        ("a/b/tree/../../x", "技能来源目录包含非法路径"),
        ("a" * 600, "技能来源过长"),
    ],
)
def test_parse_source_rejects_unsafe_input(source: str, expected: str) -> None:
    with pytest.raises(BadRequestException) as excinfo:
        parse_source(source)
    assert expected in excinfo.value.message


def _tree() -> list[dict]:
    return [
        {"type": "blob", "path": "README.md", "size": 120},
        {"type": "tree", "path": "skills"},
        {"type": "blob", "path": "skills/agent-cli-developer/SKILL.md", "size": 5356},
        {"type": "blob", "path": "skills/agent-python-pro/scripts/run.py", "size": 800},
        {"type": "blob", "path": "skills/agent-python-pro/SKILL.md", "size": 2048},
        {"type": "blob", "path": "skills/README.md", "size": 40},
        {"type": "blob", "path": "SKILL.md", "size": 512},
    ]


def test_collect_skill_entries_detects_every_skill_directory() -> None:
    resolved = parse_source("travisjneuman/.claude")
    entries = {entry.name: entry for entry in _collect_skill_entries(_tree(), resolved)}

    # 仓库根的 SKILL.md 以仓库名作为技能名。
    assert ".claude" in entries
    assert entries[".claude"].path == ""

    only = entries["agent-cli-developer"]
    assert only.path == "skills/agent-cli-developer"
    assert only.skill_path == "skills/agent-cli-developer/SKILL.md"
    assert only.file_count == 1
    assert only.total_bytes == 5356
    assert only.has_scripts is False

    scripted = entries["agent-python-pro"]
    assert scripted.file_count == 2
    assert scripted.total_bytes == 2848
    assert scripted.has_scripts is True


def test_collect_skill_entries_respects_subpath_scope() -> None:
    resolved = parse_source(
        "https://github.com/travisjneuman/.claude/tree/master/skills"
    )
    names = {entry.name for entry in _collect_skill_entries(_tree(), resolved)}

    assert "agent-cli-developer" in names
    assert "agent-python-pro" in names
    # 被 subpath 挡在外面的根目录 SKILL.md 不应出现。
    assert ".claude" not in names


def _entries() -> list[SourceSkillEntry]:
    resolved = parse_source("travisjneuman/.claude")
    return _collect_skill_entries(_tree(), resolved)


def test_select_skill_entries_supports_star_and_names_and_paths() -> None:
    entries = _entries()

    assert len(select_skill_entries(entries, ["*"])) == len(entries)

    by_name = select_skill_entries(entries, ["agent-cli-developer"])
    assert [entry.path for entry in by_name] == ["skills/agent-cli-developer"]

    by_path = select_skill_entries(entries, ["skills/agent-python-pro"])
    assert [entry.name for entry in by_path] == ["agent-python-pro"]


def test_select_skill_entries_deduplicates_and_reports_missing() -> None:
    entries = _entries()

    picked = select_skill_entries(
        entries, ["agent-cli-developer", "skills/agent-cli-developer"]
    )
    assert [entry.path for entry in picked] == ["skills/agent-cli-developer"]

    with pytest.raises(BadRequestException) as excinfo:
        select_skill_entries(entries, ["agent-cli-developer", "not-a-skill"])
    assert "未找到指定技能：not-a-skill" in excinfo.value.message

    with pytest.raises(BadRequestException) as excinfo:
        select_skill_entries(entries, ["nope"])
    assert "未找到指定技能，可选：" in excinfo.value.message


def test_source_import_request_validates_bounds() -> None:
    payload = SkillSourceImportRequest(
        source="travisjneuman/.claude", skills=["skills/agent-cli-developer"]
    )
    assert payload.package_name is None

    with pytest.raises(ValidationError):
        SkillSourceImportRequest(source="travisjneuman/.claude", skills=[])
    with pytest.raises(ValidationError):
        SkillSourceImportRequest(source="", skills=["a"])
    with pytest.raises(ValidationError):
        SkillSourceImportRequest(source="x" * 501, skills=["a"])
    with pytest.raises(ValidationError):
        SkillSourceImportRequest(source="a/b", skills=["s"] * 101)


def test_source_preview_request_validates_bounds() -> None:
    assert SkillSourcePreviewRequest(source="travisjneuman/.claude").source
    with pytest.raises(ValidationError):
        SkillSourcePreviewRequest(source="")


def test_unsafe_sources_never_reach_the_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """被拒的来源必须在纯解析阶段就失败，一次出网请求都不能发出。"""
    calls: list[str] = []

    async def fake_request(url: str, accept: str):
        calls.append(url)
        raise AssertionError("非法来源不应发起任何出网请求")

    monkeypatch.setattr(source_resolver, "_github_request", fake_request)

    for source in (
        "http://github.com/a/b",
        "https://evil.example/a/b",
        "https://169.254.169.254/latest/meta-data",
        "https://user:pw@github.com/a/b",
        "a/b/tree/../../x",
    ):
        with pytest.raises(BadRequestException):
            asyncio.run(source_resolver.list_source_skills(source))

    assert calls == []


def test_blob_entries_skips_git_symlinks() -> None:
    tree = [
        {"type": "blob", "path": "skills/x/SKILL.md", "size": 10, "mode": "100644"},
        {"type": "blob", "path": "skills/x/link.md", "size": 10, "mode": "120000"},
        {"type": "tree", "path": "skills/x/assets"},
    ]

    assert [blob["path"] for blob in _blob_entries(tree)] == ["skills/x/SKILL.md"]


@pytest.mark.parametrize(
    "path", ["", "/etc/passwd", "a/../../b", "..", "a\\b", "a/\x00b"]
)
def test_ensure_safe_member_path_rejects_escaping_paths(path: str) -> None:
    with pytest.raises(BadRequestException):
        _ensure_safe_member_path(path)


def test_ensure_safe_member_path_accepts_package_relative_paths() -> None:
    for path in ("SKILL.md", "skills/a/SKILL.md", "skills/a/scripts/run.py"):
        _ensure_safe_member_path(path)


def test_build_source_package_zip_keeps_repo_paths_and_drops_symlinks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tree = [
        {"type": "blob", "path": "skills/a/SKILL.md", "size": 4, "mode": "100644"},
        {
            "type": "blob",
            "path": "skills/a/scripts/run.py",
            "size": 4,
            "mode": "100644",
        },
        {"type": "blob", "path": "skills/a/evil", "size": 4, "mode": "120000"},
    ]

    async def fake_tree(resolved: ResolvedSource) -> list[dict]:
        return tree

    async def fake_content(resolved: ResolvedSource, blob: dict) -> bytes:
        return b"data"

    monkeypatch.setattr(source_resolver, "_fetch_tree", fake_tree)
    monkeypatch.setattr(source_resolver, "_fetch_blob_content", fake_content)

    resolved = parse_source("travisjneuman/.claude")
    entries = _collect_skill_entries(tree, resolved)
    assert [entry.name for entry in entries] == ["a"]
    assert entries[0].file_count == 2
    assert entries[0].has_scripts is True

    content, filename = asyncio.run(
        source_resolver.build_source_package_zip(resolved, entries)
    )
    with zipfile.ZipFile(BytesIO(content)) as archive:
        assert archive.namelist() == ["skills/a/SKILL.md", "skills/a/scripts/run.py"]
    assert filename == ".claude-skills.zip"
