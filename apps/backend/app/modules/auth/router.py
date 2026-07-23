from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.security import require_current_active_user
from app.modules.auth.schemas import AuthLogin, AuthMe, AuthRegister, AuthToken
from app.modules.auth.services import build_auth_me, login_user, register_user
from app.modules.role.repositories import RoleRepository
from app.modules.user.repositories import UserRepository
from app.shared.responses import ApiResponse, success_response


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=ApiResponse[AuthMe], status_code=status.HTTP_201_CREATED)
async def register_user_endpoint(
    payload: AuthRegister,
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[AuthMe]:
    user_repo = UserRepository(session)
    role_repo = RoleRepository(session)
    user = await register_user(user_repo, role_repo, payload)
    return success_response(data=user, message="user registered")


@router.post("/login", response_model=ApiResponse[AuthToken])
async def login_user_endpoint(
    payload: AuthLogin,
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse[AuthToken]:
    user_repo = UserRepository(session)
    token = await login_user(user_repo, payload.account, payload.password)
    return success_response(data=token, message="login successful")


@router.get("/me", response_model=ApiResponse[AuthMe])
async def get_current_user_endpoint(
    current_user=Depends(require_current_active_user),
) -> ApiResponse[AuthMe]:
    return success_response(data=build_auth_me(current_user))
