from __future__ import annotations

from pydantic import BaseModel, Field

from app.modules.user.schemas import UserRead


class AuthRegister(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=255)
    account: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=6, max_length=255)


class AuthToken(BaseModel):
    access_token: str
    token_type: str
    expires_in: int


class AuthLogin(BaseModel):
    account: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=6, max_length=255)


class AuthMe(UserRead):
    pass
