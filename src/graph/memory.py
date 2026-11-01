"""Checkpointer factory for the text chat endpoints (voice history lives in LiveKit)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from config.logger import get_logger
from config.settings import Settings

logger = get_logger(__name__)


@asynccontextmanager
async def open_checkpointer(settings: Settings) -> AsyncIterator[BaseCheckpointSaver]:
    """Open the configured checkpointer and close it when the context exits."""
    if settings.GRAPH_MEMORY_BACKEND == "sqlite":
        path = Path(settings.GRAPH_MEMORY_URL)
        path.parent.mkdir(parents=True, exist_ok=True)
        async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
            logger.info("Graph memory: sqlite")
            yield saver
    else:
        logger.info("Graph memory: in-process")
        yield InMemorySaver()
