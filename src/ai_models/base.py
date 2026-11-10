"""Common contract of every model wrapper: identity, timing and error classification."""

import asyncio
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

import httpx
import openai

from config.logger import get_logger

logger = get_logger(__name__)

ErrorKind = Literal["timeout", "rate_limit", "other"]

# OpenAI clients refuse an empty key, while self-hosted servers such as vLLM ignore it.
PLACEHOLDER_API_KEY = "EMPTY"


@dataclass(frozen=True)
class ModelInfo:
    """What a model wrapper is configured to use. Safe to expose: it holds no secrets."""

    kind: str
    provider: str
    model: str
    details: dict[str, Any] = field(default_factory=dict)


def classify_provider_error(exc: BaseException) -> ErrorKind:
    """Sort a provider exception into the kinds the service layer cares about."""
    if isinstance(exc, (openai.APITimeoutError, httpx.TimeoutException, asyncio.TimeoutError)):
        return "timeout"
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, openai.RateLimitError):
        return "rate_limit"
    return "other"


class AIModel(ABC):
    """Base of all model wrappers (LLM, embeddings, STT, TTS, VAD, turn detection)."""

    kind: ClassVar[str]

    @property
    @abstractmethod
    def info(self) -> ModelInfo:
        """Static description of the configured model."""

    @asynccontextmanager
    async def traced(self, operation: str, **metadata: Any) -> AsyncIterator[dict[str, Any]]:
        """Time a model call and log latency; callers add usage figures to the yielded dict."""
        outputs: dict[str, Any] = {}
        started = time.perf_counter()
        try:
            yield outputs
        finally:
            latency_ms = (time.perf_counter() - started) * 1000
            logger.info(
                "%s.%s model=%s latency_ms=%.0f %s",
                self.kind,
                operation,
                self.info.model,
                latency_ms,
                " ".join(f"{key}={value}" for key, value in {**metadata, **outputs}.items()),
            )
