import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

from app.modules.role.schemas import RoleCreate, RoleListQuery, RoleUpdate
from app.modules.role.services import create_role, delete_role, get_role_detail, list_roles, update_role
from app.shared.exceptions import BadRequestException, ConflictException, NotFoundException
from app.shared.pagination import PaginationParams


@dataclass
class FakeRole:
    id: int
    code: str
    name: str
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class FakeRoleRepository:
    def __init__(self, roles: list[FakeRole] | None = None, bindings: dict[int, int] | None = None) -> None:
        self.roles = roles or []
        self.bindings = bindings or {}

    async def get_by_code(self, code: str):
        return next((role for role in self.roles if role.code == code), None)

    async def create_role(self, payload: RoleCreate):
        role = FakeRole(
            id=len(self.roles) + 1,
            code=payload.code,
            name=payload.name,
            description=payload.description,
            is_active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.roles.append(role)
        return role

    async def get_by_id(self, role_id: int):
        return next((role for role in self.roles if role.id == role_id), None)

    async def list_roles(self, params: PaginationParams, query: RoleListQuery):
        items = self.roles
        if query.name:
            items = [role for role in items if query.name.lower() in role.name.lower()]
        if query.code:
            items = [role for role in items if role.code == query.code]
        reverse = query.sort.startswith("-")
        items = sorted(items, key=lambda role: role.created_at, reverse=reverse)
        return items[params.offset : params.offset + params.limit]

    async def count_roles(self, query: RoleListQuery):
        items = self.roles
        if query.name:
            items = [role for role in items if query.name.lower() in role.name.lower()]
        if query.code:
            items = [role for role in items if role.code == query.code]
        return len(items)

    async def update_role(self, role: FakeRole, payload: RoleUpdate):
        updates = payload.model_dump(exclude_unset=True, exclude_none=True)
        for field, value in updates.items():
            setattr(role, field, value)
        return role

    async def count_user_bindings(self, role_id: int):
        return self.bindings.get(role_id, 0)

    async def delete(self, role: FakeRole):
        self.roles = [item for item in self.roles if item.id != role.id]


def test_create_role_rejects_duplicate_code() -> None:
    async def run() -> None:
        repo = FakeRoleRepository(
            roles=[
                FakeRole(
                    id=1,
                    code="super_admin",
                    name="Super Admin",
                    description=None,
                    is_active=True,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            ]
        )

        try:
            await create_role(repo, RoleCreate(code="super_admin", name="Duplicate"))
        except ConflictException:
            return

        raise AssertionError("Expected duplicate role code to raise ConflictException")

    asyncio.run(run())


def test_get_role_detail_raises_when_missing() -> None:
    async def run() -> None:
        repo = FakeRoleRepository()

        try:
            await get_role_detail(repo, 99)
        except NotFoundException:
            return

        raise AssertionError("Expected missing role to raise NotFoundException")

    asyncio.run(run())


def test_list_roles_returns_page_data() -> None:
    async def run() -> None:
        repo = FakeRoleRepository(
            roles=[
                FakeRole(
                    id=1,
                    code="operator",
                    name="Operator",
                    description=None,
                    is_active=True,
                    created_at=datetime(2026, 7, 19, 10, 0, tzinfo=UTC),
                    updated_at=datetime(2026, 7, 19, 10, 0, tzinfo=UTC),
                ),
                FakeRole(
                    id=2,
                    code="super_admin",
                    name="Super Admin",
                    description=None,
                    is_active=True,
                    created_at=datetime(2026, 7, 20, 10, 0, tzinfo=UTC),
                    updated_at=datetime(2026, 7, 20, 10, 0, tzinfo=UTC),
                ),
            ]
        )

        page_data = await list_roles(repo, PaginationParams(page=1, page_size=1), RoleListQuery())

        assert len(page_data.items) == 1
        assert page_data.items[0].id == 2
        assert page_data.total == 2

    asyncio.run(run())


def test_update_role_rejects_duplicate_code() -> None:
    async def run() -> None:
        repo = FakeRoleRepository(
            roles=[
                FakeRole(
                    id=1,
                    code="super_admin",
                    name="Super Admin",
                    description=None,
                    is_active=True,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                ),
                FakeRole(
                    id=2,
                    code="operator",
                    name="Operator",
                    description=None,
                    is_active=True,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                ),
            ]
        )

        try:
            await update_role(repo, 2, RoleUpdate(code="super_admin"))
        except ConflictException:
            return

        raise AssertionError("Expected duplicate role code to raise ConflictException")

    asyncio.run(run())


def test_update_role_rejects_empty_patch() -> None:
    async def run() -> None:
        repo = FakeRoleRepository(
            roles=[
                FakeRole(
                    id=1,
                    code="super_admin",
                    name="Super Admin",
                    description=None,
                    is_active=True,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            ]
        )

        try:
            await update_role(repo, 1, RoleUpdate())
        except BadRequestException:
            return

        raise AssertionError("Expected empty role update to raise BadRequestException")

    asyncio.run(run())


def test_delete_role_rejects_bound_role() -> None:
    async def run() -> None:
        repo = FakeRoleRepository(
            roles=[
                FakeRole(
                    id=1,
                    code="super_admin",
                    name="Super Admin",
                    description=None,
                    is_active=True,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            ],
            bindings={1: 2},
        )

        try:
            await delete_role(repo, 1)
        except ConflictException:
            return

        raise AssertionError("Expected bound role delete to raise ConflictException")

    asyncio.run(run())
