"""Ingestion and similarity search over the knowledge base."""

from config.logger import get_logger
from config.settings import Settings
from src.ai_models.embeddings import EmbeddingService
from src.clients.qdrant import QdrantStore
from src.utils.exceptions import InvalidInputError
from src.utils.models import DocumentInfo, IngestResult, Passage
from src.utils.text import chunk_text

logger = get_logger(__name__)


class Retriever:
    """Chunk, embed and store documents; embed a query and return the closest passages."""

    def __init__(
        self, settings: Settings, embeddings: EmbeddingService, store: QdrantStore
    ) -> None:
        self._settings = settings
        self._embeddings = embeddings
        self._store = store

    async def search(self, query: str, *, top_k: int | None = None) -> list[Passage]:
        """Closest passages to ``query`` above the configured score threshold."""
        vector = await self._embeddings.aembed_query(query)
        passages = await self._store.search(
            vector,
            top_k=top_k or self._settings.RAG_TOP_K,
            score_threshold=self._settings.RAG_SCORE_THRESHOLD,
        )
        logger.info("Knowledge search returned %d passage(s)", len(passages))
        return passages

    async def ingest(self, source: str, text: str) -> IngestResult:
        """Replace the stored chunks of ``source`` with freshly embedded ones.

        New chunks are written first (same ids overwrite), then leftovers of a longer earlier
        version are removed, so a failure never leaves the document missing.
        """
        chunks = chunk_text(text, self._settings.RAG_CHUNK_SIZE, self._settings.RAG_CHUNK_OVERLAP)
        if not chunks:
            raise InvalidInputError("The document contains no text to index.")
        vectors = await self._embeddings.aembed_documents(chunks)
        await self._store.ensure_collection(len(vectors[0]))
        await self._store.upsert(source, chunks, vectors)
        await self._store.delete_stale_chunks(source, len(chunks))
        logger.info("Ingested document: %d chunk(s), %d characters", len(chunks), len(text))
        return IngestResult(source=source, chunks=len(chunks), characters=len(text))

    async def list_documents(self) -> list[DocumentInfo]:
        """Stored documents with chunk counts."""
        return await self._store.list_documents()

    async def delete_document(self, source: str) -> int:
        """Remove a document; returns the number of deleted chunks."""
        return await self._store.delete_document(source)

    async def close(self) -> None:
        """Release the Qdrant connection."""
        await self._store.close()
