from app.modules.platform.repositories import PlatformRepository
from app.modules.platform.schemas import PlatformCreate, PlatformRead
from app.shared.exceptions import ConflictException, NotFoundException


async def create_platform(
    repo: PlatformRepository, payload: PlatformCreate, *, user_id: int
) -> PlatformRead:
    if await repo.get_by_code(payload.code) is not None:
        raise ConflictException("platform code already exists")
    platform = await repo.create_platform(payload, user_id)
    return PlatformRead.model_validate({**platform.__dict__, "owner_id": user_id})


async def get_platform(
    repo: PlatformRepository, *, platform_id: int, user_id: int
) -> PlatformRead:
    platform = await repo.get_by_id_for_user(platform_id, user_id)
    if platform is None:
        raise NotFoundException("platform not found")
    owner_id = platform.admins[0].user_id if platform.admins else None
    return PlatformRead.model_validate({**platform.__dict__, "owner_id": owner_id})
