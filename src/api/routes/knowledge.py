"""Knowledge-base management and search."""

from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile

from src.api.deps import KnowledgeDep
from src.api.schemas.requests import KnowledgeSearchRequest
from src.api.schemas.responses import (
    DeleteResponse,
    DocumentListResponse,
    DocumentOut,
    ErrorResponse,
    IngestResponse,
    SearchResponse,
    SearchResultOut,
)
from src.utils.models import SOURCE_MAX_CHARS

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

ERROR_RESPONSES = {
    400: {"model": ErrorResponse},
    401: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    502: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
}


@router.post(
    "/documents", response_model=IngestResponse, status_code=200, responses=ERROR_RESPONSES
)
async def upload_document(
    service: KnowledgeDep,
    file: Annotated[UploadFile, File(description="A .txt, .md or .pdf file")],
    source: Annotated[str | None, Form(max_length=SOURCE_MAX_CHARS)] = None,
) -> IngestResponse:
    """Index a document. Uploading the same name again replaces it."""
    data = await file.read()
    result = await service.ingest(file.filename or "", data, source)
    return IngestResponse(source=result.source, chunks=result.chunks, characters=result.characters)


@router.get(
    "/documents", response_model=DocumentListResponse, status_code=200, responses=ERROR_RESPONSES
)
async def list_documents(service: KnowledgeDep) -> DocumentListResponse:
    """List indexed documents."""
    documents = await service.list_documents()
    return DocumentListResponse(
        documents=[DocumentOut(source=item.source, chunks=item.chunks) for item in documents]
    )


@router.delete(
    "/documents/{source}",
    response_model=DeleteResponse,
    status_code=200,
    responses={**ERROR_RESPONSES, 404: {"model": ErrorResponse}},
)
async def delete_document(source: str, service: KnowledgeDep) -> DeleteResponse:
    """Remove a document and its chunks."""
    deleted = await service.delete(source)
    return DeleteResponse(source=source, deleted_chunks=deleted)


@router.post("/search", response_model=SearchResponse, status_code=200, responses=ERROR_RESPONSES)
async def search(body: KnowledgeSearchRequest, service: KnowledgeDep) -> SearchResponse:
    """Find the passages closest to a query."""
    passages = await service.search(body.query, body.top_k)
    return SearchResponse(
        results=[
            SearchResultOut(
                source=item.source, chunk_index=item.chunk_index, score=item.score, text=item.text
            )
            for item in passages
        ]
    )
