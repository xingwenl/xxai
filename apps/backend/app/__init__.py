from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.database import dispose_database
from app.core.logging import get_logger, setup_logging
from app.modules.system.router import router as system_router
from app.modules.user.router import router as user_router
from app.shared.exceptions import register_exception_handlers


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level)
    logger = get_logger(__name__)
    logger.info("Starting %s in %s mode", settings.app_name, settings.app_env)
    yield
    await dispose_database()
    logger.info("Stopped %s", settings.app_name)


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        debug=settings.app_debug,
        docs_url=settings.docs_url,
        openapi_url=settings.openapi_url,
        lifespan=lifespan,
    )

    register_exception_handlers(app)
    app.include_router(system_router, prefix=settings.api_v1_prefix)
    app.include_router(user_router, prefix=settings.api_v1_prefix)
    return app
