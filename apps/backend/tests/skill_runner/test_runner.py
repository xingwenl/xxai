import hashlib
import hmac
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.modules.skill_runner.schemas import ScriptExecuteRequest
from app.modules.skill_runner.tools import build_skill_script_tools
from runner import main as runner_main


def _binding(*, allowed: bool, files: list[tuple[str, str]]):
    package = SimpleNamespace(
        id=7,
        name="Reporter",
        is_active=True,
        allow_script_execution=allowed,
        files=[
            SimpleNamespace(relative_path=path, role=role) for path, role in files
        ],
    )
    skill = SimpleNamespace(id=9, package=package)
    return SimpleNamespace(skill=skill)


def test_build_script_tools_requires_package_permission() -> None:
    tools = build_skill_script_tools(
        [_binding(allowed=False, files=[("scripts/run.py", "script")])]
    )

    assert tools == []


def test_build_script_tools_only_exposes_supported_indexed_scripts() -> None:
    tools = build_skill_script_tools(
        [
            _binding(
                allowed=True,
                files=[
                    ("scripts/run.py", "script"),
                    ("scripts/native.bin", "script"),
                    ("assets/helper.py", "asset"),
                ],
            )
        ]
    )

    assert tools[0].name == "run_skill_script_7"
    assert tools[0].input_schema["properties"]["script_path"]["enum"] == [
        "scripts/run.py"
    ]


def test_resolve_script_rejects_path_traversal(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(runner_main, "STORAGE_ROOT", tmp_path.resolve())

    with pytest.raises(ValueError, match="unsafe script path"):
        runner_main._resolve_script("../outside", "scripts/run.py")


def test_execute_maps_missing_storage_key_to_bad_request(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(runner_main, "STORAGE_ROOT", tmp_path.resolve())
    body = ScriptExecuteRequest(
        execution_id=1,
        storage_key="skill-packages/1/missing",
        script_path="run.py",
        timeout_seconds=1,
        max_output_bytes=1024,
    ).model_dump_json().encode()
    signature = hmac.new(
        runner_main.SHARED_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    response = TestClient(runner_main.app).post(
        "/execute",
        content=body,
        headers={"X-Skill-Runner-Signature": signature},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "script not found"}


def test_resolve_script_rejects_symlink_escape(tmp_path, monkeypatch) -> None:
    package = tmp_path / "skill-packages" / "1" / "package"
    package.mkdir(parents=True)
    outside = tmp_path / "outside.py"
    outside.write_text("print('outside')", encoding="utf-8")
    (package / "escape.py").symlink_to(outside)
    monkeypatch.setattr(runner_main, "STORAGE_ROOT", tmp_path.resolve())

    with pytest.raises(ValueError):
        runner_main._resolve_script(
            "skill-packages/1/package", "escape.py"
        )


def test_run_python_script_returns_output_and_exit_code(tmp_path) -> None:
    script = tmp_path / "run.py"
    script.write_text(
        "import sys\nprint('|'.join(sys.argv[1:]))\n", encoding="utf-8"
    )
    payload = ScriptExecuteRequest(
        execution_id=1,
        storage_key="skill-packages/1/package",
        script_path="run.py",
        arguments=["alpha", "beta"],
        timeout_seconds=5,
        max_output_bytes=1024,
    )

    result = runner_main._run_script(script, payload)

    assert result.status == "succeeded"
    assert result.exit_code == 0
    assert result.stdout.strip() == "alpha|beta"


def test_run_script_times_out(tmp_path) -> None:
    script = tmp_path / "slow.py"
    script.write_text("import time\ntime.sleep(5)\n", encoding="utf-8")
    payload = ScriptExecuteRequest(
        execution_id=1,
        storage_key="skill-packages/1/package",
        script_path="slow.py",
        timeout_seconds=1,
        max_output_bytes=1024,
    )

    result = runner_main._run_script(script, payload)

    assert result.status == "failed"
    assert result.exit_code is None
    assert result.error == "script execution timed out"


def test_run_script_truncates_output(tmp_path) -> None:
    script = tmp_path / "noisy.py"
    script.write_text("print('x' * 4096)\n", encoding="utf-8")
    payload = ScriptExecuteRequest(
        execution_id=1,
        storage_key="skill-packages/1/package",
        script_path="noisy.py",
        timeout_seconds=5,
        max_output_bytes=1024,
    )

    result = runner_main._run_script(script, payload)

    assert result.status == "succeeded"
    assert result.stdout.endswith("[输出已截断]")
    assert len(result.stdout.encode()) < 1100
