"""Knowledge-base use cases: ingest, list, delete and search documents."""

import asyncio
import re
from pathlib import PurePath

from config.settings import Settings
from src.rag.loaders import extract_text
from src.rag.retriever import Retriever
from src.utils.exceptions import InvalidInputError, NotFoundError
from src.utils.models import DocumentInfo, IngestResult, Passage

SOURCE_MAX_CHARS = 200
CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


class KnowledgeService:
    """Validates uploads and delegates storage and search to the retriever."""

    def __init__(self, retriever: Retriever, settings: Settings) -> None:
        self._retriever = retriever
        self._settings = settings

    async def ingest(self, filename: str, data: bytes, source: str | None = None) -> IngestResult:
        """Extract text from an uploaded file and (re)index it under ``source``."""
        if len(data) > self._settings.RAG_MAX_UPLOAD_BYTES:
            raise InvalidInputError(
                f"The file is larger than {self._settings.RAG_MAX_UPLOAD_BYTES} bytes."
            )
        name = self._source_name(source or filename)
        text = await asyncio.to_thread(extract_text, filename, data)
        return await self._retriever.ingest(name, text)

    async def list_documents(self) -> list[DocumentInfo]:
        """All stored documents."""
        return await self._retriever.list_documents()

    async def delete(self, source: str) -> int:
        """Delete a document; raises ``NotFoundError`` when it does not exist."""
        deleted = await self._retriever.delete_document(source)
        if deleted == 0:
            raise NotFoundError(f"No document named '{source}'.")
        return deleted

    async def search(self, query: str, top_k: int | None = None) -> list[Passage]:
        """Closest passages to ``query``."""
        return await self._retriever.search(query, top_k=top_k)

    @staticmethod
    def _source_name(raw: str) -> str:
        name = CONTROL_CHARS.sub("", PurePath(raw.replace("\\", "/")).name).strip()
        if not name:
            raise InvalidInputError("The document needs a name.")
        return name[:SOURCE_MAX_CHARS]
