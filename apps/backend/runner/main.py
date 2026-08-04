from __future__ import annotations

import hashlib
import hmac
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath

from fastapi import FastAPI, Header, HTTPException, Request

from skill_runner_protocol import ScriptExecuteRequest, ScriptExecuteResponse

app = FastAPI(title="Skill Runner", docs_url=None, redoc_url=None, openapi_url=None)

STORAGE_ROOT = Path(os.getenv("SKILL_STORAGE_ROOT", "/app/storage")).resolve()
SHARED_SECRET = os.getenv(
    "SKILL_RUNNER_SHARED_SECRET", "dev-skill-runner-secret-change-me"
)
INTERPRETERS = {
    ".py": sys.executable,
    ".js": "node",
    ".mjs": "node",
    ".sh": "/bin/sh",
}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/execute", response_model=ScriptExecuteResponse)
async def execute(
    request: Request,
    signature: str = Header(alias="X-Skill-Runner-Signature"),
) -> ScriptExecuteResponse:
    body = await request.body()
    expected = hmac.new(SHARED_SECRET.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="invalid runner signature")
    payload = ScriptExecuteRequest.model_validate_json(body)
    try:
        script = _resolve_script(payload.storage_key, payload.script_path)
        return _run_script(script, payload)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail="script not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _safe_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("unsafe script path")
    return path


def _resolve_script(storage_key: str, script_path: str) -> Path:
    package_path = (STORAGE_ROOT / _safe_relative_path(storage_key)).resolve(strict=True)
    package_path.relative_to(STORAGE_ROOT)
    candidate = (package_path / _safe_relative_path(script_path)).resolve(strict=True)
    candidate.relative_to(package_path)
    if not candidate.is_file() or candidate.suffix.lower() not in INTERPRETERS:
        raise ValueError("unsupported script")
    return candidate


def _run_script(
    script: Path, payload: ScriptExecuteRequest
) -> ScriptExecuteResponse:
    if any(len(argument) > 1000 for argument in payload.arguments):
        raise ValueError("script argument is too long")
    started = time.monotonic()
    interpreter = INTERPRETERS[script.suffix.lower()]
    with tempfile.TemporaryDirectory(prefix="skill-run-") as work_dir:
        stdout_path = Path(work_dir) / "stdout.log"
        stderr_path = Path(work_dir) / "stderr.log"
        with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
            process = subprocess.Popen(
                [interpreter, str(script), *payload.arguments],
                cwd=script.parent,
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                env={
                    "PATH": "/usr/local/bin:/usr/bin:/bin",
                    "HOME": work_dir,
                    "TMPDIR": work_dir,
                    "PYTHONUNBUFFERED": "1",
                },
                start_new_session=True,
            )
            error = None
            try:
                exit_code = process.wait(timeout=payload.timeout_seconds)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                exit_code = None
                error = "script execution timed out"
        stdout = _read_limited(stdout_path, payload.max_output_bytes)
        stderr = _read_limited(stderr_path, payload.max_output_bytes)
    duration_ms = int((time.monotonic() - started) * 1000)
    status = "succeeded" if exit_code == 0 and error is None else "failed"
    return ScriptExecuteResponse(
        status=status,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_ms=duration_ms,
        error=error,
    )


def _read_limited(path: Path, limit: int) -> str:
    with path.open("rb") as file:
        content = file.read(limit + 1)
    truncated = len(content) > limit
    text = content[:limit].decode("utf-8", errors="replace")
    return f"{text}\n[输出已截断]" if truncated else text
