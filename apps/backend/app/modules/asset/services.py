from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from uuid import uuid4

from app.core.config import get_settings

_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._ -]+")


def sanitize_filename(value: str | None, *, fallback: str = "download") -> str:
    name = Path((value or "").replace("\\", "/")).name.strip().strip(".")
    name = _SAFE_FILENAME.sub("_", name)[:255]
    return name or fallback


def resolve_asset_path(
    storage_key: str, storage_root: str | Path | None = None
) -> Path:
    root = Path(storage_root or get_settings().agent_file_storage_path).resolve()
    target = (root / storage_key).resolve()
    if target != root and root not in target.parents:
        raise ValueError("asset storage key escapes storage root")
    return target


async def persist_asset(
    repo,
    temp_path: Path,
    *,
    platform_id: int,
    agent_id: int,
    conversation_id: int,
    user_id: int | None,
    platform_end_user_id: int | None,
    filename: str,
    content_type: str,
    size_bytes: int,
    source_url: str,
):
    asset_id = uuid4().hex
    safe_name = sanitize_filename(filename)
    storage_key = str(Path("assets") / str(platform_id) / asset_id / safe_name)
    target = resolve_asset_path(storage_key)
    await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(os.replace, temp_path, target)
    try:
        return await repo.create(
            asset_id=asset_id,
            platform_id=platform_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
            user_id=user_id,
            platform_end_user_id=platform_end_user_id,
            storage_key=storage_key,
            filename=safe_name,
            content_type=content_type,
            size_bytes=size_bytes,
            source_url=source_url,
        )
    except Exception:
        await asyncio.to_thread(target.unlink, missing_ok=True)
        raise
