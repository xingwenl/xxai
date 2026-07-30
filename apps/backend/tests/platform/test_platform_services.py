import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

from app.modules.platform.schemas import PlatformCreate, PlatformUpdate
from app.modules.platform.services import (
    create_platform,
    delete_platform,
    get_platform,
    update_platform,
)
from app.shared.exceptions import NotFoundException


@dataclass
class FakePlatform:
    id: int
    name: str
    code: str
    owner_id: int
    is_active: bool = True
    created_at: datetime = datetime.now(UTC)
    updated_at: datetime = datetime.now(UTC)


class FakePlatformRepository:
    def __init__(self) -> None:
        self.items = [FakePlatform(id=2, name="Other", code="other", owner_id=9)]

    async def get_by_id_for_user(self, platform_id: int, user_id: int):
        return next(
            (
                item
                for item in self.items
                if item.id == platform_id and item.owner_id == user_id
            ),
            None,
        )

    async def get_by_code(self, code: str):
        return next((item for item in self.items if item.code == code), None)

    async def create_platform(self, payload, owner_id: int):
        item = FakePlatform(
            id=1, name=payload.name, code=payload.code, owner_id=owner_id
        )
        self.items.append(item)
        return item

    async def update_platform(self, platform, values: dict):
        for key, value in values.items():
            setattr(platform, key, value)
        return platform

    async def delete_platform(self, platform) -> None:
        self.items.remove(platform)


def test_create_platform_returns_platform_for_creator() -> None:
    async def run() -> None:
        result = await create_platform(
            FakePlatformRepository(),
            PlatformCreate(name="Demo", code="demo"),
            user_id=7,
        )

        assert result.name == "Demo"
        assert result.code == "demo"
        assert result.owner_id == 7

    asyncio.run(run())


def test_get_platform_rejects_platform_owned_by_another_user() -> None:
    async def run() -> None:
        try:
            await get_platform(FakePlatformRepository(), platform_id=2, user_id=7)
        except NotFoundException as exc:
            assert exc.message == "platform not found"
            return

        raise AssertionError("cross-platform access should be rejected")

    asyncio.run(run())


def test_update_platform_allows_owner_to_rename_and_disable() -> None:
    async def run() -> None:
        result = await update_platform(
            FakePlatformRepository(),
            platform_id=2,
            payload=PlatformUpdate(name="Renamed", code="renamed", is_active=False),
            user_id=9,
        )

        assert result.name == "Renamed"
        assert result.code == "renamed"
        assert result.is_active is False
        assert result.owner_id == 9

    asyncio.run(run())


def test_update_platform_rejects_cross_user_access() -> None:
    async def run() -> None:
        try:
            await update_platform(
                FakePlatformRepository(),
                platform_id=2,
                payload=PlatformUpdate(name="Nope"),
                user_id=7,
            )
        except NotFoundException as exc:
            assert exc.message == "platform not found"
            return

        raise AssertionError("cross-platform update should be rejected")

    asyncio.run(run())


def test_delete_platform_hard_deletes_owner_platform() -> None:
    async def run() -> None:
        repo = FakePlatformRepository()

        await delete_platform(repo, platform_id=2, user_id=9)

        assert repo.items == []

    asyncio.run(run())
