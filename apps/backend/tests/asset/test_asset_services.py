from __future__ import annotations

import asyncio
from functools import wraps
from types import SimpleNamespace

import pytest

from app.modules.asset.services import (
    persist_asset,
    resolve_asset_path,
    sanitize_filename,
)


def async_test(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return run


class FakeAssetRepository:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.values = None

    async def create(self, **values):
        self.values = values
        if self.fail:
            raise RuntimeError("database unavailable")
        return SimpleNamespace(**values)


def test_sanitize_filename_removes_path_and_unsafe_characters() -> None:
    assert sanitize_filename("../../report<script>.pdf") == "report_script_.pdf"
    assert sanitize_filename("") == "download"


def test_resolve_asset_path_rejects_storage_escape(tmp_path) -> None:
    with pytest.raises(ValueError):
        resolve_asset_path("../outside.txt", tmp_path)


@async_test
async def test_persist_asset_moves_file_and_records_relative_key(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("AGENT_FILE_STORAGE_PATH", str(tmp_path))
    from app.core.config import get_settings

    get_settings.cache_clear()
    temp = tmp_path / "pending"
    temp.write_bytes(b"content")
    repo = FakeAssetRepository()
    asset = await persist_asset(
        repo,
        temp,
        platform_id=1,
        agent_id=2,
        conversation_id=3,
        user_id=4,
        platform_end_user_id=None,
        filename="report.pdf",
        content_type="application/pdf",
        size_bytes=7,
        source_url="https://example.com/report.pdf",
    )
    assert not temp.exists()
    assert resolve_asset_path(asset.storage_key).read_bytes() == b"content"
    get_settings.cache_clear()


@async_test
async def test_persist_asset_removes_final_file_when_database_write_fails(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("AGENT_FILE_STORAGE_PATH", str(tmp_path))
    from app.core.config import get_settings

    get_settings.cache_clear()
    temp = tmp_path / "pending"
    temp.write_bytes(b"content")
    repo = FakeAssetRepository(fail=True)
    with pytest.raises(RuntimeError):
        await persist_asset(
            repo,
            temp,
            platform_id=1,
            agent_id=2,
            conversation_id=3,
            user_id=4,
            platform_end_user_id=None,
            filename="report.pdf",
            content_type="application/pdf",
            size_bytes=7,
            source_url="https://example.com/report.pdf",
        )
    assert list((tmp_path / "assets" / "1").rglob("report.pdf")) == []
    get_settings.cache_clear()
