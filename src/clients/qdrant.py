"""Thin async wrapper around Qdrant for knowledge-base chunks."""

import uuid
from collections import Counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qm
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

from config.logger import get_logger
from config.settings import Settings
from src.utils.exceptions import ExternalServiceError
from src.utils.models import DocumentInfo, Passage

logger = get_logger(__name__)

IN_MEMORY_URL = ":memory:"
SOURCE_FIELD = "source"
CHUNK_FIELD = "chunk_index"
POINT_NAMESPACE = uuid.UUID("6f1c6a52-3d1e-4c3b-9e0a-0d7f8b1f2a11")
SCROLL_PAGE_SIZE = 256
UPSERT_BATCH_SIZE = 128


def point_id(source: str, chunk_index: int) -> str:
    """Stable id for a chunk, so re-ingesting a document overwrites instead of duplicating."""
    return str(uuid.uuid5(POINT_NAMESPACE, f"{source}#{chunk_index}"))


class QdrantStore:
    """Collection management, upsert, similarity search and per-document operations."""

    def __init__(self, settings: Settings, *, client: AsyncQdrantClient | None = None) -> None:
        self._collection = settings.QDRANT_COLLECTION
        if client is not None:
            self._client = client
        elif settings.QDRANT_URL == IN_MEMORY_URL:
            self._client = AsyncQdrantClient(location=IN_MEMORY_URL)
        else:
            key = settings.QDRANT_API_KEY.get_secret_value() if settings.QDRANT_API_KEY else None
            self._client = AsyncQdrantClient(
                url=settings.QDRANT_URL, api_key=key, timeout=int(settings.REQUEST_TIMEOUT)
            )

    @asynccontextmanager
    async def _guard(self, action: str) -> AsyncIterator[None]:
        try:
            yield
        except (UnexpectedResponse, ResponseHandlingException, OSError) as exc:
            raise ExternalServiceError(
                f"Qdrant {action} failed: {type(exc).__name__}: {exc}"
            ) from exc

    async def ensure_collection(self, dimension: int) -> None:
        """Create the collection (cosine distance, indexed ``source``) or check its vector size."""
        async with self._guard("ensure_collection"):
            if await self._client.collection_exists(self._collection):
                info = await self._client.get_collection(self._collection)
                vectors = info.config.params.vectors
                existing = vectors.size if isinstance(vectors, qm.VectorParams) else None
                if existing is not None and existing != dimension:
                    raise ExternalServiceError(
                        f"Collection {self._collection} holds {existing}-dimension vectors but "
                        f"the embedding model produces {dimension}. Use another QDRANT_COLLECTION."
                    )
                return
            await self._client.create_collection(
                self._collection,
                vectors_config=qm.VectorParams(size=dimension, distance=qm.Distance.COSINE),
            )
            await self._client.create_payload_index(
                self._collection, SOURCE_FIELD, qm.PayloadSchemaType.KEYWORD
            )
            logger.info("Created collection %s (dimension %d)", self._collection, dimension)

    async def upsert(self, source: str, chunks: list[str], vectors: list[list[float]]) -> None:
        """Store the chunks of one document."""
        points = [
            qm.PointStruct(
                id=point_id(source, index),
                vector=vector,
                payload={SOURCE_FIELD: source, CHUNK_FIELD: index, "text": text},
            )
            for index, (text, vector) in enumerate(zip(chunks, vectors, strict=True))
        ]
        async with self._guard("upsert"):
            for start in range(0, len(points), UPSERT_BATCH_SIZE):
                await self._client.upsert(
                    self._collection, points=points[start : start + UPSERT_BATCH_SIZE], wait=True
                )

    async def delete_stale_chunks(self, source: str, keep: int) -> None:
        """Delete the chunks of ``source`` whose index is ``keep`` or higher."""
        selector = qm.Filter(
            must=[
                qm.FieldCondition(key=SOURCE_FIELD, match=qm.MatchValue(value=source)),
                qm.FieldCondition(key=CHUNK_FIELD, range=qm.Range(gte=keep)),
            ]
        )
        async with self._guard("delete_stale_chunks"):
            await self._client.delete(
                self._collection, points_selector=qm.FilterSelector(filter=selector), wait=True
            )

    async def search(
        self, vector: list[float], *, top_k: int, score_threshold: float | None
    ) -> list[Passage]:
        """Nearest chunks to ``vector``; an absent collection means an empty knowledge base."""
        async with self._guard("search"):
            if not await self._client.collection_exists(self._collection):
                return []
            response = await self._client.query_points(
                self._collection,
                query=vector,
                limit=top_k,
                score_threshold=score_threshold or None,
                with_payload=True,
            )
        return [
            Passage(
                source=str(point.payload.get(SOURCE_FIELD, "")),
                chunk_index=int(point.payload.get("chunk_index", 0)),
                text=str(point.payload.get("text", "")),
                score=float(point.score),
            )
            for point in response.points
            if point.payload
        ]

    async def list_documents(self) -> list[DocumentInfo]:
        """Documents with their chunk counts, sorted by name."""
        counts: Counter[str] = Counter()
        async with self._guard("list_documents"):
            if not await self._client.collection_exists(self._collection):
                return []
            offset = None
            while True:
                points, offset = await self._client.scroll(
                    self._collection,
                    limit=SCROLL_PAGE_SIZE,
                    offset=offset,
                    with_payload=[SOURCE_FIELD],
                    with_vectors=False,
                )
                counts.update(str(point.payload[SOURCE_FIELD]) for point in points if point.payload)
                if offset is None:
                    break
        return [DocumentInfo(source=name, chunks=count) for name, count in sorted(counts.items())]

    async def delete_document(self, source: str) -> int:
        """Delete every chunk of a document and return how many were removed."""
        selector = qm.Filter(
            must=[qm.FieldCondition(key=SOURCE_FIELD, match=qm.MatchValue(value=source))]
        )
        async with self._guard("delete_document"):
            if not await self._client.collection_exists(self._collection):
                return 0
            found = await self._client.count(self._collection, count_filter=selector, exact=True)
            if found.count:
                await self._client.delete(
                    self._collection, points_selector=qm.FilterSelector(filter=selector), wait=True
                )
        return found.count

    async def close(self) -> None:
        """Release the connection."""
        await self._client.close()
