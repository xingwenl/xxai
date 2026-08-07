from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.security import bearer_scheme, decode_access_token
from app.modules.asset.repositories import AssetRepository
from app.modules.asset.services import resolve_asset_path
from app.modules.embed.security import decode_embed_token
from app.modules.user.repositories import UserRepository
from app.shared.exceptions import NotFoundException, UnauthorizedException

router = APIRouter(prefix="/assets", tags=["assets"])


async def _resolve_principal(
    credentials: HTTPAuthorizationCredentials | None,
    session: AsyncSession,
) -> tuple[str, dict]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedException("not authenticated")
    token = credentials.credentials
    try:
        payload = decode_access_token(token)
        subject = payload["sub"]
        user = (
            await UserRepository(session).get_by_id(int(subject))
            if subject.isdigit()
            else None
        )
        if user is None or not user.is_active:
            raise UnauthorizedException("user not found")
        return "user", {"user_id": user.id}
    except UnauthorizedException:
        payload = decode_embed_token(token)
        subject = str(payload.get("sub", ""))
        if not subject.isdigit():
            raise UnauthorizedException("invalid embed subject")
        return "embed", {
            "platform_id": int(payload["platform_id"]),
            "agent_id": int(payload["agent_id"]),
            "end_user_id": int(subject),
        }


@router.get("/{asset_id}")
async def download_asset_endpoint(
    asset_id: str,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_db_session),
):
    principal_type, principal = await _resolve_principal(credentials, session)
    repo = AssetRepository(session)
    if principal_type == "user":
        asset = await repo.get_for_user(asset_id, principal["user_id"])
    else:
        asset = await repo.get_for_embed(asset_id, **principal)
    if asset is None:
        raise NotFoundException("asset not found")
    path = resolve_asset_path(asset.storage_key)
    if not path.is_file():
        raise NotFoundException("asset file not found")
    return FileResponse(
        path,
        media_type=asset.content_type,
        filename=asset.filename,
        content_disposition_type="attachment",
        headers={"X-Content-Type-Options": "nosniff"},
    )
