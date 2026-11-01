"""Response models."""

from typing import Any

from pydantic import BaseModel, ConfigDict


class ErrorBody(BaseModel):
    """Details of a failed request."""

    code: str
    message: str
    request_id: str
    details: Any | None = None


class ErrorResponse(BaseModel):
    """Standard error envelope returned for every failure."""

    error: ErrorBody


class TokenResponse(BaseModel):
    """What the browser needs to join a LiveKit room."""

    token: str
    url: str
    room: str
    identity: str


class ChatResponse(BaseModel):
    """Final answer of a text chat turn."""

    session_id: str
    answer: str
    tools_used: list[str]
    request_id: str


class InfoResponse(BaseModel):
    """Non-secret runtime configuration shown in the GUI."""

    app_name: str
    version: str
    llm_model: str
    stt_provider: str
    stt_model: str
    tts_provider: str
    tts_model: str
    embedding_model: str
    turn_detector: str
    tracing_provider: str
    auth_required: bool
    knowledge_base_configured: bool


class DocumentOut(BaseModel):
    """A knowledge-base document."""

    source: str
    chunks: int


class DocumentListResponse(BaseModel):
    """All knowledge-base documents."""

    documents: list[DocumentOut]


class IngestResponse(BaseModel):
    """Outcome of an upload."""

    source: str
    chunks: int
    characters: int


class DeleteResponse(BaseModel):
    """Outcome of a delete."""

    source: str
    deleted_chunks: int


class SearchResultOut(BaseModel):
    """One passage found by a search."""

    source: str
    chunk_index: int
    score: float
    text: str


class SearchResponse(BaseModel):
    """Passages found by a search."""

    results: list[SearchResultOut]


class HealthResponse(BaseModel):
    """Liveness payload of ``GET /health``. Makes no external calls."""

    model_config = ConfigDict(json_schema_extra={"example": {"status": "ok", "service": "omnivox"}})

    status: str
    service: str
    version: str
    env: str
    uptime_seconds: float
