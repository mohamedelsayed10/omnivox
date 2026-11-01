"""Application factory and ``python -m src.app`` entry point. No business logic."""

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager

import uvicorn
from fastapi import APIRouter, Depends, FastAPI

from config.logger import get_logger, setup_logging
from config.settings import Settings, get_settings
from src import __version__
from src.api.deps import Container, build_container, require_api_key
from src.api.error_handlers import register_error_handlers
from src.api.middleware import register_middleware
from src.api.routes import health, info, knowledge, livekit
from src.api.routes.graph import agent

logger = get_logger(__name__)

ContainerFactory = Callable[[Settings, AsyncExitStack], Awaitable[Container]]


def create_app(
    settings: Settings | None = None, *, container_factory: ContainerFactory = build_container
) -> FastAPI:
    """Build the FastAPI app. Tests pass a ``container_factory`` that returns fake services."""
    settings = settings or get_settings()
    setup_logging(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info("Starting %s %s (%s)", settings.APP_NAME, __version__, settings.APP_ENV)
        async with AsyncExitStack() as stack:
            app.state.container = await container_factory(settings, stack)
            yield
        logger.info("Stopped %s", settings.APP_NAME)

    app = FastAPI(
        title=settings.APP_NAME,
        version=__version__,
        root_path=settings.ROOT_PATH,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.started_at = time.monotonic()
    register_middleware(app, settings)
    register_error_handlers(app)

    api = APIRouter(prefix=settings.API_PREFIX, dependencies=[Depends(require_api_key)])
    for router in (info.router, livekit.router, agent.router, knowledge.router):
        api.include_router(router)
    app.include_router(health.router)
    app.include_router(api)
    return app


app = create_app()

if __name__ == "__main__":
    runtime = get_settings()
    uvicorn.run(
        "src.app:app",
        host=runtime.HOST,
        port=runtime.PORT,
        reload=runtime.RELOAD,
        log_config=None,
    )
