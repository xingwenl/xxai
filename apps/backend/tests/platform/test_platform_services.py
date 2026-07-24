import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

from app.modules.platform.schemas import PlatformCreate
from app.modules.platform.services import create_platform, get_platform
from app.shared.exceptions import NotFoundException


@dataclass
class FakePlatform:
    id: int
    name: str
    code: str
    owner_id: int
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
