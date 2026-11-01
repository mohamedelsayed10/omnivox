"""Request models: bounded lengths, extra fields forbidden."""

from pydantic import BaseModel, ConfigDict, Field

ID_PATTERN = r"^[A-Za-z0-9._:\-]+$"
MAX_ID_CHARS = 64
MAX_MESSAGE_CHARS = 20_000
MAX_QUERY_CHARS = 300
MAX_TOP_K = 20


class StrictModel(BaseModel):
    """Base for request bodies."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TokenRequest(StrictModel):
    """Ask for a LiveKit join token. Both fields are generated when omitted."""

    identity: str | None = Field(
        default=None, min_length=1, max_length=MAX_ID_CHARS, pattern=ID_PATTERN
    )
    room: str | None = Field(
        default=None, min_length=1, max_length=MAX_ID_CHARS, pattern=ID_PATTERN
    )


class ChatRequest(StrictModel):
    """One user message in a text chat session."""

    session_id: str = Field(min_length=1, max_length=MAX_ID_CHARS, pattern=ID_PATTERN)
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


class KnowledgeSearchRequest(StrictModel):
    """Search the knowledge base."""

    query: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    top_k: int | None = Field(default=None, ge=1, le=MAX_TOP_K)
