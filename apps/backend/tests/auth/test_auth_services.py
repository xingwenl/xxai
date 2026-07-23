import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from app.modules.auth.schemas import AuthRegister
from app.modules.auth.services import login_user, register_user
from app.shared.exceptions import ConflictException, UnauthorizedException


@dataclass
class FakeRole:
    id: int
    code: str
    name: str


@dataclass
class FakeUser:
    id: int
    name: str
    email: str
    account: str
    password: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    roles: list[FakeRole]


class FakeUserRepository:
    def __init__(self, users: list[FakeUser] | None = None) -> None:
        self.users = users or []
        self.user_roles: dict[int, list[int]] = {}

    async def get_by_email(self, email: str):
        return next((user for user in self.users if user.email == email), None)

    async def get_by_account(self, account: str):
        return next((user for user in self.users if user.account == account), None)

    async def create_user(self, payload, *, password: str | None = None):
        user = FakeUser(
            id=len(self.users) + 1,
            name=payload.name,
            email=payload.email,
            account=payload.account,
            password=password or payload.password,
            is_active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            roles=[],
        )
        self.users.append(user)
        return user

    async def replace_user_roles(self, user_id: int, role_ids: list[int]):
        self.user_roles[user_id] = list(role_ids)

    async def get_by_id(self, user_id: int):
        return next((user for user in self.users if user.id == user_id), None)


class FakeRoleRepository:
    async def get_by_ids(self, role_ids: list[int]):
        return []


def test_hash_password_and_verify_password_round_trip() -> None:
    hashed_password = hash_password("secret123")

    assert hashed_password != "secret123"
    assert verify_password("secret123", hashed_password) is True
    assert verify_password("wrong-pass", hashed_password) is False


def test_decode_access_token_rejects_expired_token() -> None:
    expired_token = create_access_token("1", expires_delta=timedelta(seconds=-1))

    try:
        decode_access_token(expired_token)
    except UnauthorizedException as exc:
        assert exc.message == "token expired"
        return

    raise AssertionError("Expected expired token to raise UnauthorizedException")


def test_register_user_creates_user_with_hashed_password() -> None:
    async def run() -> None:
        user_repo = FakeUserRepository()
        user = await register_user(
            user_repo,
            FakeRoleRepository(),
            AuthRegister(
                name="Alice",
                email="alice@example.com",
                account="alice",
                password="secret123",
            ),
        )

        created_user = user_repo.users[0]
        assert created_user.password != "secret123"
        assert verify_password("secret123", created_user.password) is True
        assert user.roles == []

    asyncio.run(run())


def test_register_user_rejects_duplicate_account() -> None:
    async def run() -> None:
        user_repo = FakeUserRepository(
            users=[
                FakeUser(
                    id=1,
                    name="Alice",
                    email="alice@example.com",
                    account="alice",
                    password=hash_password("secret123"),
                    is_active=True,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                    roles=[],
                )
            ]
        )

        try:
            await register_user(
                user_repo,
                FakeRoleRepository(),
                AuthRegister(
                    name="Alice 2",
                    email="alice-2@example.com",
                    account="alice",
                    password="secret123",
                ),
            )
        except ConflictException:
            return

        raise AssertionError("Expected duplicate account to raise ConflictException")

    asyncio.run(run())


def test_login_user_returns_access_token() -> None:
    async def run() -> None:
        user_repo = FakeUserRepository(
            users=[
                FakeUser(
                    id=7,
                    name="Alice",
                    email="alice@example.com",
                    account="alice",
                    password=hash_password("secret123"),
                    is_active=True,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                    roles=[],
                )
            ]
        )

        token = await login_user(user_repo, "alice", "secret123")
        payload = decode_access_token(token.access_token)

        assert token.token_type == "bearer"
        assert token.expires_in > 0
        assert payload["sub"] == "7"

    asyncio.run(run())


def test_login_user_rejects_invalid_password() -> None:
    async def run() -> None:
        user_repo = FakeUserRepository(
            users=[
                FakeUser(
                    id=7,
                    name="Alice",
                    email="alice@example.com",
                    account="alice",
                    password=hash_password("secret123"),
                    is_active=True,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                    roles=[],
                )
            ]
        )

        try:
            await login_user(user_repo, "alice", "wrong-pass")
        except UnauthorizedException as exc:
            assert exc.message == "invalid account or password"
            return

        raise AssertionError("Expected invalid password to raise UnauthorizedException")

    asyncio.run(run())
