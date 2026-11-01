"""Embedding service (OpenAI-compatible endpoint, default Cohere ``embed-v5.0-fast``)."""

import asyncio
from urllib.parse import urlparse

from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings
from openai import DefaultAsyncHttpxClient

from config.logger import get_logger
from config.settings import Settings
from src.ai_models.base import AIModel, ModelInfo, classify_provider_error
from src.utils.exceptions import ConfigurationError, ExternalServiceError, OmniVoxError

logger = get_logger(__name__)

PROBE_TEXT = "dimension probe"


def build_embeddings(settings: Settings) -> OpenAIEmbeddings:
    """Create the embeddings client; raises ``ConfigurationError`` when no key is set."""
    if settings.EMBEDDING_API_KEY is None:
        raise ConfigurationError("The embedding API key (EMBEDDING_API_KEY) is not configured.")
    return OpenAIEmbeddings(
        model=settings.EMBEDDING_MODEL,
        api_key=settings.EMBEDDING_API_KEY,
        base_url=settings.EMBEDDING_BASE_URL,
        max_retries=settings.MAX_RETRIES,
        request_timeout=settings.REQUEST_TIMEOUT,
        chunk_size=settings.EMBEDDING_BATCH_SIZE,
        check_embedding_ctx_length=False,
        http_async_client=DefaultAsyncHttpxClient(timeout=settings.REQUEST_TIMEOUT),
        model_kwargs={"encoding_format": "float"},
    )


async def _gather_or_cancel(coroutines: list) -> list:
    """Run coroutines together; when one fails, cancel the rest instead of letting them run on."""
    tasks = [asyncio.ensure_future(coro) for coro in coroutines]
    try:
        return await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


class EmbeddingService(AIModel):
    """Batched, concurrency-bounded embeddings with errors mapped to domain exceptions."""

    kind = "embedding"

    def __init__(self, settings: Settings, *, embeddings: Embeddings | None = None) -> None:
        self._settings = settings
        self._embeddings = embeddings
        self._owns_client = embeddings is None
        self._semaphore = asyncio.Semaphore(settings.EMBEDDING_CONCURRENCY)
        self._dimension: int | None = None

    @property
    def info(self) -> ModelInfo:
        return ModelInfo(
            kind=self.kind,
            provider="openai-compatible",
            model=self._settings.EMBEDDING_MODEL,
            details={"host": urlparse(self._settings.EMBEDDING_BASE_URL).netloc},
        )

    async def aclose(self) -> None:
        """Close the HTTP client this service created, if it was ever used."""
        client = getattr(self._embeddings, "http_async_client", None)
        if client is not None and self._owns_client:
            await client.aclose()

    @property
    def configured(self) -> bool:
        """True when embeddings can be requested."""
        return self._embeddings is not None or self._settings.EMBEDDING_API_KEY is not None

    def _client(self) -> Embeddings:
        if self._embeddings is None:
            self._embeddings = build_embeddings(self._settings)
        return self._embeddings

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed texts in batches, preserving order."""
        if not texts:
            return []
        size = self._settings.EMBEDDING_BATCH_SIZE
        batches = [texts[start : start + size] for start in range(0, len(texts), size)]
        async with self.traced("aembed_documents", texts=len(texts), batches=len(batches)):
            results = await _gather_or_cancel([self._embed_batch(batch) for batch in batches])
        return [vector for batch in results for vector in batch]

    async def aembed_query(self, text: str) -> list[float]:
        """Embed one search query."""
        async with self.traced("aembed_query", chars=len(text)):
            try:
                async with self._semaphore:
                    return await self._client().aembed_query(text)
            except OmniVoxError:
                raise
            except Exception as exc:
                raise self._map_error(exc) from exc

    async def dimension(self) -> int:
        """Vector size of the model, found once by embedding a probe text."""
        if self._dimension is None:
            self._dimension = len(await self.aembed_query(PROBE_TEXT))
        return self._dimension

    async def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        try:
            async with self._semaphore:
                return await self._client().aembed_documents(batch)
        except OmniVoxError:
            raise
        except Exception as exc:
            raise self._map_error(exc) from exc

    @staticmethod
    def _map_error(exc: Exception) -> ExternalServiceError:
        kind = classify_provider_error(exc)
        return ExternalServiceError(
            f"Embedding request failed ({kind}): {type(exc).__name__}: {exc}"
        )
