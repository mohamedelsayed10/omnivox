"""Shared fixtures. Tests are offline: dummy keys, no tracing, in-memory Qdrant, fake models."""

import os

# Must be set before any ``src`` module reads settings (``src.app`` builds an app at import).
os.environ["OPENAI_API_KEY"] = "test-key-not-real-0123456789"
os.environ["LIVEKIT_API_SECRET"] = "test-livekit-secret-0123456789abcdef"
os.environ["TRACING_PROVIDER"] = "none"

from collections.abc import Callable, Iterator
from contextlib import AsyncExitStack
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from config.settings import Settings
from src.app import create_app
from tests.fakes import build_container

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def make_settings(tmp_path: Path) -> Callable[..., Settings]:
    """Factory for settings that ignore ``.env`` and use temp paths and an in-memory Qdrant."""

    def factory(**overrides: object) -> Settings:
        values: dict[str, object] = {
            "OPENAI_API_KEY": "test-key-not-real-0123456789",
            "LIVEKIT_API_SECRET": "test-livekit-secret-0123456789abcdef",
            "TRACING_PROVIDER": "none",
            "LOG_DIR": str(tmp_path / "logs"),
            "QDRANT_URL": ":memory:",
            "GRAPH_MEMORY_BACKEND": "memory",
            "GRAPH_MEMORY_URL": str(tmp_path / "memory.sqlite"),
            "EMBEDDING_API_KEY": "embedding-key-not-real-0123456789",
            "ELEVENLABS_API_KEY": "elevenlabs-key-not-real-0123456789",
            "API_KEYS": "",
        }
        values.update(overrides)
        return Settings(_env_file=None, **values)

    return factory


@pytest.fixture
def settings(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings()


@pytest.fixture
def make_client(make_settings: Callable[..., Settings]) -> Iterator[Callable[..., TestClient]]:
    """Factory for a test client running on fakes; every client is closed after the test."""
    clients: list[TestClient] = []

    def factory(
        script: list[AIMessage] | None = None, settings: Settings | None = None, **kwargs: object
    ) -> TestClient:
        settings = settings or make_settings()

        async def container_factory(runtime_settings: Settings, stack: AsyncExitStack):
            return await build_container(runtime_settings, stack, script or [], **kwargs)

        client = TestClient(
            create_app(settings, container_factory=container_factory),
            raise_server_exceptions=False,
        )
        client.__enter__()
        clients.append(client)
        return client

    yield factory
    for client in clients:
        client.__exit__(None, None, None)
