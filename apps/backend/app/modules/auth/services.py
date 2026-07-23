from __future__ import annotations

from app.core.config import get_settings
from app.core.security import create_access_token, verify_password
from app.modules.auth.schemas import AuthRegister, AuthToken
from app.modules.user.schemas import UserCreate, UserRead
from app.modules.user.services import build_role_summaries, build_user_read, create_user
from app.shared.exceptions import UnauthorizedException


async def register_user(user_repo, role_repo, payload: AuthRegister) -> UserRead:
    return await create_user(
        user_repo,
        role_repo,
        UserCreate(
            name=payload.name,
            email=payload.email,
            account=payload.account,
            password=payload.password,
            role_ids=[],
        ),
    )


async def login_user(user_repo, account: str, password: str) -> AuthToken:
    user = await user_repo.get_by_account(account)
    if user is None or not verify_password(password, user.password):
        raise UnauthorizedException("invalid account or password")
    if not user.is_active:
        raise UnauthorizedException("user is inactive")

    settings = get_settings()
    access_token = create_access_token(str(user.id))
    return AuthToken(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60,
    )


def build_auth_me(user) -> UserRead:
    return build_user_read(user, build_role_summaries(user.roles))
