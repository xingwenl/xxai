import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

from app.modules.user.schemas import UserCreate, UserUpdate
from app.modules.user.services import create_user, delete_user, get_user_detail, list_users, update_user
from app.shared.exceptions import BadRequestException, ConflictException, NotFoundException
from app.shared.pagination import PaginationParams


@dataclass
class FakeUser:
    id: int
    name: str
    email: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class FakeUserRepository:
    def __init__(self, users: list[FakeUser] | None = None) -> None:
        self.users = users or []

    async def get_by_email(self, email: str):
        return next((user for user in self.users if user.email == email), None)

    async def create_user(self, payload: UserCreate):
        user = FakeUser(
            id=len(self.users) + 1,
            name=payload.name,
            email=payload.email,
            is_active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.users.append(user)
        return user

    async def get_by_id(self, user_id: int):
        return next((user for user in self.users if user.id == user_id), None)

    async def list_users(self, params: PaginationParams):
        start = params.offset
        end = start + params.limit
        return self.users[start:end]

    async def count_users(self):
        return len(self.users)

    async def update_user(self, user: FakeUser, payload: UserUpdate):
        updates = payload.model_dump(exclude_unset=True, exclude_none=True)
        for field, value in updates.items():
            setattr(user, field, value)
        return user

    async def delete_user(self, user: FakeUser):
        self.users = [item for item in self.users if item.id != user.id]


def test_create_user_rejects_duplicate_email() -> None:
    async def run() -> None:
        repo = FakeUserRepository(
            users=[
                FakeUser(
                    id=1,
                    name="Alice",
                    email="alice@example.com",
                    is_active=True,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            ]
        )
        payload = UserCreate(name="Alice 2", email="alice@example.com")

        try:
            await create_user(repo, payload)
        except ConflictException:
            return

        raise AssertionError("Expected duplicate email to raise ConflictException")

    asyncio.run(run())


def test_get_user_detail_raises_when_missing() -> None:
    async def run() -> None:
        repo = FakeUserRepository()

        try:
            await get_user_detail(repo, 99)
        except NotFoundException:
            return

        raise AssertionError("Expected missing user to raise NotFoundException")

    asyncio.run(run())


def test_list_users_returns_page_data() -> None:
    async def run() -> None:
        repo = FakeUserRepository(
            users=[
                FakeUser(
                    id=1,
                    name="Alice",
                    email="alice@example.com",
                    is_active=True,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                ),
                FakeUser(
                    id=2,
                    name="Bob",
                    email="bob@example.com",
                    is_active=True,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                ),
            ]
        )
        params = PaginationParams(page=1, page_size=1)

        page_data = await list_users(repo, params)

        assert len(page_data.items) == 1
        assert page_data.page_no == 1
        assert page_data.page_size == 1
        assert page_data.total == 2
        assert page_data.pages == 2

    asyncio.run(run())


def test_update_user_rejects_duplicate_email() -> None:
    async def run() -> None:
        repo = FakeUserRepository(
            users=[
                FakeUser(
                    id=1,
                    name="Alice",
                    email="alice@example.com",
                    is_active=True,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                ),
                FakeUser(
                    id=2,
                    name="Bob",
                    email="bob@example.com",
                    is_active=True,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                ),
            ]
        )

        try:
            await update_user(repo, 2, UserUpdate(email="alice@example.com"))
        except ConflictException:
            return

        raise AssertionError("Expected duplicate email on update to raise ConflictException")

    asyncio.run(run())


def test_update_user_rejects_empty_patch() -> None:
    async def run() -> None:
        repo = FakeUserRepository(
            users=[
                FakeUser(
                    id=1,
                    name="Alice",
                    email="alice@example.com",
                    is_active=True,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            ]
        )

        try:
            await update_user(repo, 1, UserUpdate())
        except BadRequestException:
            return

        raise AssertionError("Expected empty update payload to raise BadRequestException")

    asyncio.run(run())


def test_delete_user_removes_user() -> None:
    async def run() -> None:
        repo = FakeUserRepository(
            users=[
                FakeUser(
                    id=1,
                    name="Alice",
                    email="alice@example.com",
                    is_active=True,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            ]
        )

        await delete_user(repo, 1)

        assert await repo.get_by_id(1) is None

    asyncio.run(run())
