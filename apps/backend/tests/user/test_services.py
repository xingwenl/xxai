import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

from app.modules.role.schemas import RoleSummary
from app.modules.user.schemas import UserCreate, UserListQuery, UserUpdate
from app.modules.user.services import create_user, delete_user, get_user_detail, list_users, update_user
from app.shared.exceptions import BadRequestException, ConflictException, NotFoundException
from app.shared.pagination import PaginationParams


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
    roles: list["FakeRole"] | None = None


class FakeUserRepository:
    def __init__(self, users: list[FakeUser] | None = None) -> None:
        self.users = users or []
        self.user_roles: dict[int, list[int]] = {}
        self.role_codes: dict[str, int] = {}

    async def get_by_email(self, email: str):
        return next((user for user in self.users if user.email == email), None)

    async def get_by_account(self, account: str):
        return next((user for user in self.users if user.account == account), None)

    async def create_user(self, payload: UserCreate, *, password: str | None = None):
        user = FakeUser(
            id=len(self.users) + 1,
            name=payload.name,
            email=payload.email,
            account=payload.account,
            password=password or payload.password,
            is_active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.users.append(user)
        return user

    async def get_by_id(self, user_id: int):
        return next((user for user in self.users if user.id == user_id), None)

    def _apply_query(self, query: UserListQuery) -> list[FakeUser]:
        items = self.users
        if query.name:
            items = [user for user in items if query.name.lower() in user.name.lower()]
        if query.email:
            items = [user for user in items if user.email == query.email]
        if query.role_id is not None:
            items = [user for user in items if query.role_id in self.user_roles.get(user.id, [])]
        if query.role_code:
            role_id = self.role_codes.get(query.role_code)
            items = [
                user
                for user in items
                if role_id is not None and role_id in self.user_roles.get(user.id, [])
            ]
        reverse = query.sort.startswith("-")
        return sorted(items, key=lambda user: user.created_at, reverse=reverse)

    async def list_users(self, params: PaginationParams, query: UserListQuery):
        filtered = self._apply_query(query)
        start = params.offset
        end = start + params.limit
        return filtered[start:end]

    async def count_users(self, query: UserListQuery):
        return len(self._apply_query(query))

    async def update_user(self, user: FakeUser, payload: UserUpdate):
        updates = payload.model_dump(exclude_unset=True, exclude_none=True)
        for field, value in updates.items():
            setattr(user, field, value)
        return user

    async def delete_user(self, user: FakeUser):
        self.users = [item for item in self.users if item.id != user.id]

    async def replace_user_roles(self, user_id: int, role_ids: list[int]):
        self.user_roles[user_id] = list(role_ids)


@dataclass
class FakeRole:
    id: int
    code: str
    name: str


class FakeRoleRepository:
    def __init__(self, roles: list[FakeRole] | None = None, user_roles: dict[int, list[int]] | None = None) -> None:
        self.roles = roles or []
        self.user_roles = user_roles or {}

    async def get_by_ids(self, role_ids: list[int]):
        return [role for role in self.roles if role.id in role_ids]

    async def get_roles_by_user_id(self, user_id: int):
        role_ids = self.user_roles.get(user_id, [])
        return [role for role in self.roles if role.id in role_ids]


def attach_fake_roles(repo: FakeUserRepository, role_repo: FakeRoleRepository) -> None:
    for user in repo.users:
        user.roles = [role for role in role_repo.roles if role.id in role_repo.user_roles.get(user.id, [])]


def test_create_user_rejects_duplicate_email() -> None:
    async def run() -> None:
        repo = FakeUserRepository(
            users=[
                FakeUser(
                    id=1,
                    name="Alice",
                    email="alice@example.com",
                    account="alice",
                    password="secret123",
                    is_active=True,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            ]
        )
        payload = UserCreate(
            name="Alice 2",
            email="alice@example.com",
            account="alice-2",
            password="secret123",
            role_ids=[],
        )

        try:
            await create_user(repo, FakeRoleRepository(), payload)
        except ConflictException:
            return

        raise AssertionError("Expected duplicate email to raise ConflictException")

    asyncio.run(run())


def test_get_user_detail_raises_when_missing() -> None:
    async def run() -> None:
        repo = FakeUserRepository()
        role_repo = FakeRoleRepository()

        try:
            await get_user_detail(repo, role_repo, 99)
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
                    account="alice",
                    password="secret123",
                    is_active=True,
                    created_at=datetime(2026, 7, 19, 10, 0, tzinfo=UTC),
                    updated_at=datetime(2026, 7, 19, 10, 0, tzinfo=UTC),
                ),
                FakeUser(
                    id=2,
                    name="Bob",
                    email="bob@example.com",
                    account="bob",
                    password="secret123",
                    is_active=True,
                    created_at=datetime(2026, 7, 20, 10, 0, tzinfo=UTC),
                    updated_at=datetime(2026, 7, 20, 10, 0, tzinfo=UTC),
                ),
            ]
        )
        role_repo = FakeRoleRepository(
            roles=[FakeRole(id=2, code="operator", name="Operator")],
            user_roles={2: [2]},
        )
        attach_fake_roles(repo, role_repo)
        params = PaginationParams(page=1, page_size=1)

        page_data = await list_users(repo, role_repo, params, UserListQuery())

        assert len(page_data.items) == 1
        assert page_data.page_no == 1
        assert page_data.page_size == 1
        assert page_data.total == 2
        assert page_data.pages == 2
        assert page_data.items[0]["id"] == 2
        assert page_data.items[0]["roles"] == [RoleSummary(id=2, code="operator", name="Operator").model_dump()]

    asyncio.run(run())


def test_list_users_supports_filters_sort_and_fields() -> None:
    async def run() -> None:
        repo = FakeUserRepository(
            users=[
                FakeUser(
                    id=1,
                    name="Alice Chen",
                    email="alice@example.com",
                    account="alice.chen",
                    password="secret123",
                    is_active=True,
                    created_at=datetime(2026, 7, 19, 10, 0, tzinfo=UTC),
                    updated_at=datetime(2026, 7, 19, 10, 0, tzinfo=UTC),
                ),
                FakeUser(
                    id=2,
                    name="Bob Li",
                    email="bob@example.com",
                    account="bob.li",
                    password="secret123",
                    is_active=True,
                    created_at=datetime(2026, 7, 20, 10, 0, tzinfo=UTC),
                    updated_at=datetime(2026, 7, 20, 10, 0, tzinfo=UTC),
                ),
                FakeUser(
                    id=3,
                    name="Alice Wang",
                    email="alice.wang@example.com",
                    account="alice.wang",
                    password="secret123",
                    is_active=False,
                    created_at=datetime(2026, 7, 18, 10, 0, tzinfo=UTC),
                    updated_at=datetime(2026, 7, 18, 10, 0, tzinfo=UTC),
                ),
            ]
        )
        role_repo = FakeRoleRepository(
            roles=[
                FakeRole(id=1, code="super_admin", name="Super Admin"),
                FakeRole(id=3, code="auditor", name="Auditor"),
            ],
            user_roles={1: [1], 3: [3]},
        )
        attach_fake_roles(repo, role_repo)
        params = PaginationParams(page=1, page_size=10)
        query = UserListQuery(name="alice", sort="-created_at", fields=["id", "name", "created_at"])

        page_data = await list_users(repo, role_repo, params, query)

        assert page_data.total == 2
        assert [item["id"] for item in page_data.items] == [1, 3]
        assert page_data.items[0] == {
            "id": 1,
            "name": "Alice Chen",
            "created_at": "2026-07-19 10:00:00",
        }

        exact_email = await list_users(
            repo,
            role_repo,
            params,
            UserListQuery(email="bob@example.com", fields=["email"]),
        )
        assert exact_email.total == 1
        assert exact_email.items == [{"email": "bob@example.com"}]

    asyncio.run(run())


def test_update_user_rejects_duplicate_email() -> None:
    async def run() -> None:
        repo = FakeUserRepository(
            users=[
                FakeUser(
                    id=1,
                    name="Alice",
                    email="alice@example.com",
                    account="alice",
                    password="secret123",
                    is_active=True,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                ),
                FakeUser(
                    id=2,
                    name="Bob",
                    email="bob@example.com",
                    account="bob",
                    password="secret123",
                    is_active=True,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                ),
            ]
        )
        role_repo = FakeRoleRepository()

        try:
            await update_user(repo, role_repo, 2, UserUpdate(email="alice@example.com"))
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
                    account="alice",
                    password="secret123",
                    is_active=True,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            ]
        )
        role_repo = FakeRoleRepository()

        try:
            await update_user(repo, role_repo, 1, UserUpdate())
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
                    account="alice",
                    password="secret123",
                    is_active=True,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            ]
        )

        await delete_user(repo, 1)

        assert await repo.get_by_id(1) is None

    asyncio.run(run())


def test_update_user_rejects_duplicate_account() -> None:
    async def run() -> None:
        repo = FakeUserRepository(
            users=[
                FakeUser(
                    id=1,
                    name="Alice",
                    email="alice@example.com",
                    account="alice",
                    password="secret123",
                    is_active=True,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                ),
                FakeUser(
                    id=2,
                    name="Bob",
                    email="bob@example.com",
                    account="bob",
                    password="secret123",
                    is_active=True,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                ),
            ]
        )
        role_repo = FakeRoleRepository()

        try:
            await update_user(repo, role_repo, 2, UserUpdate(account="alice"))
        except ConflictException:
            return

        raise AssertionError("Expected duplicate account on update to raise ConflictException")

    asyncio.run(run())


def test_create_user_attaches_roles() -> None:
    async def run() -> None:
        repo = FakeUserRepository()
        role_repo = FakeRoleRepository(
            roles=[
                FakeRole(id=1, code="super_admin", name="Super Admin"),
                FakeRole(id=2, code="operator", name="Operator"),
            ]
        )

        created = await create_user(
            repo,
            role_repo,
            UserCreate(
                name="Alice",
                email="alice@example.com",
                account="alice",
                password="secret123",
                role_ids=[1, 2],
            ),
        )

        assert [role.code for role in created.roles] == ["super_admin", "operator"]
        assert repo.user_roles[1] == [1, 2]

    asyncio.run(run())


def test_get_user_detail_returns_roles() -> None:
    async def run() -> None:
        repo = FakeUserRepository(
            users=[
                FakeUser(
                    id=1,
                    name="Alice",
                    email="alice@example.com",
                    account="alice",
                    password="secret123",
                    is_active=True,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            ]
        )
        role_repo = FakeRoleRepository(
            roles=[FakeRole(id=1, code="super_admin", name="Super Admin")],
            user_roles={1: [1]},
        )
        attach_fake_roles(repo, role_repo)

        detail = await get_user_detail(repo, role_repo, 1)

        assert detail.roles == [RoleSummary(id=1, code="super_admin", name="Super Admin")]

    asyncio.run(run())


def test_list_users_supports_role_filters() -> None:
    async def run() -> None:
        repo = FakeUserRepository(
            users=[
                FakeUser(
                    id=1,
                    name="Alice",
                    email="alice@example.com",
                    account="alice",
                    password="secret123",
                    is_active=True,
                    created_at=datetime(2026, 7, 19, 10, 0, tzinfo=UTC),
                    updated_at=datetime(2026, 7, 19, 10, 0, tzinfo=UTC),
                ),
                FakeUser(
                    id=2,
                    name="Bob",
                    email="bob@example.com",
                    account="bob",
                    password="secret123",
                    is_active=True,
                    created_at=datetime(2026, 7, 20, 10, 0, tzinfo=UTC),
                    updated_at=datetime(2026, 7, 20, 10, 0, tzinfo=UTC),
                ),
            ]
        )
        repo.user_roles = {1: [1], 2: [2]}
        repo.role_codes = {"super_admin": 1, "operator": 2}
        params = PaginationParams(page=1, page_size=10)

        role_repo = FakeRoleRepository(
            roles=[
                FakeRole(id=1, code="super_admin", name="Super Admin"),
                FakeRole(id=2, code="operator", name="Operator"),
            ],
            user_roles={1: [1], 2: [2]},
        )
        attach_fake_roles(repo, role_repo)

        by_role_id = await list_users(repo, role_repo, params, UserListQuery(role_id=1))
        by_role_code = await list_users(repo, role_repo, params, UserListQuery(role_code="operator"))

        assert [item["id"] for item in by_role_id.items] == [1]
        assert [item["id"] for item in by_role_code.items] == [2]

    asyncio.run(run())


def test_list_users_returns_roles_by_default() -> None:
    async def run() -> None:
        repo = FakeUserRepository(
            users=[
                FakeUser(
                    id=1,
                    name="Alice",
                    email="alice@example.com",
                    account="alice",
                    password="secret123",
                    is_active=True,
                    created_at=datetime(2026, 7, 19, 10, 0, tzinfo=UTC),
                    updated_at=datetime(2026, 7, 19, 10, 0, tzinfo=UTC),
                )
            ]
        )
        role_repo = FakeRoleRepository(
            roles=[FakeRole(id=1, code="super_admin", name="Super Admin")],
            user_roles={1: [1]},
        )
        attach_fake_roles(repo, role_repo)

        page_data = await list_users(repo, role_repo, PaginationParams(page=1, page_size=10), UserListQuery())

        assert page_data.items == [
            {
                "id": 1,
                "name": "Alice",
                "email": "alice@example.com",
                "account": "alice",
                "is_active": True,
                "created_at": "2026-07-19 10:00:00",
                "updated_at": "2026-07-19 10:00:00",
                "roles": [{"id": 1, "code": "super_admin", "name": "Super Admin"}],
            }
        ]

    asyncio.run(run())


def test_update_user_supports_role_only_update() -> None:
    async def run() -> None:
        repo = FakeUserRepository(
            users=[
                FakeUser(
                    id=1,
                    name="Alice",
                    email="alice@example.com",
                    account="alice",
                    password="secret123",
                    is_active=True,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            ]
        )
        role_repo = FakeRoleRepository(
            roles=[FakeRole(id=2, code="operator", name="Operator")],
            user_roles={1: [2]},
        )

        updated = await update_user(repo, role_repo, 1, UserUpdate(role_ids=[2]))

        assert repo.user_roles[1] == [2]
        assert updated.roles == [RoleSummary(id=2, code="operator", name="Operator")]

    asyncio.run(run())
