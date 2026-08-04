from io import BytesIO
from zipfile import ZipFile

import pytest

from app.modules.skill.importers import parse_skill_package
from app.modules.skill.services import render_skill_instruction
from app.shared.exceptions import BadRequestException


def test_render_skill_instruction_uses_declared_parameters() -> None:
    result = render_skill_instruction(
        "请为 {{ customer }} 查询订单 {{ order_id }}",
        {"customer": "Alice", "order_id": "A-100"},
    )

    assert result == "请为 Alice 查询订单 A-100"


def test_render_skill_instruction_rejects_missing_parameter() -> None:
    with pytest.raises(BadRequestException, match="skill parameter is missing"):
        render_skill_instruction("查询 {{ order_id }}", {})


def test_parse_root_skill_zip_preserves_scripts_and_assets() -> None:
    package = parse_skill_package(
        "reporter.zip",
        _zip_bytes(
            {
                "SKILL.md": (
                    "---\n"
                    "name: Report Writer\n"
                    "description: Writes reports\n"
                    "---\n"
                    "Use references before drafting."
                ),
                "scripts/render.py": "print('render')",
                "assets/template.txt": "template",
            }
        ),
    )

    assert package.name == "Report Writer"
    assert package.slug == "report-writer"
    assert package.candidates[0].description == "Writes reports"
    assert package.candidates[0].instruction_template == "Use references before drafting."
    assert {file.role for file in package.files} == {"skill", "script", "asset"}
    assert "检测到 scripts 目录，脚本执行权限默认关闭" in package.warnings


def test_parse_skill_zip_supports_yaml_multiline_description() -> None:
    package = parse_skill_package(
        "writer.zip",
        _zip_bytes(
            {
                "writer/SKILL.md": (
                    "---\r\n"
                    "name: Writer\r\n"
                    "description: >-\r\n"
                    "  Writes reports with:\r\n"
                    "  citations and tables.\r\n"
                    "---\r\n"
                    "Draft the report."
                )
            }
        ),
    )

    assert package.candidates[0].description == (
        "Writes reports with: citations and tables."
    )
    assert package.candidates[0].instruction_template == "Draft the report."


def test_parse_codex_plugin_zip_returns_multiple_candidates() -> None:
    package = parse_skill_package(
        "market.zip",
        _zip_bytes(
            {
                ".codex-plugin/plugin.json": '{"name":"Market Plugin"}',
                "skills/a/SKILL.md": "---\nname: Alpha\n---\nAlpha body",
                "skills/b/SKILL.md": "---\nname: Beta\n---\nBeta body",
            }
        ),
    )

    assert package.package_type == "codex_plugin"
    assert package.name == "Market Plugin"
    assert [candidate.name for candidate in package.candidates] == ["Alpha", "Beta"]


def test_parse_skill_zip_rejects_unsafe_path() -> None:
    with pytest.raises(BadRequestException, match="unsafe path"):
        parse_skill_package("bad.zip", _zip_bytes({"../SKILL.md": "bad"}))


def test_parse_skill_zip_requires_skill_md() -> None:
    with pytest.raises(BadRequestException, match="does not contain SKILL.md"):
        parse_skill_package("empty.zip", _zip_bytes({"README.md": "hello"}))


def test_parse_skill_zip_rejects_duplicate_paths() -> None:
    buffer = BytesIO()
    with pytest.warns(UserWarning, match="Duplicate name"):
        with ZipFile(buffer, "w") as archive:
            archive.writestr("SKILL.md", "First")
            archive.writestr("SKILL.md", "Second")

    with pytest.raises(BadRequestException, match="duplicate paths"):
        parse_skill_package("duplicate.zip", buffer.getvalue())


def _zip_bytes(files: dict[str, str]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return buffer.getvalue()
