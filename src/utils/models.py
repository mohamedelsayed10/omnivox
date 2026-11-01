"""Plain data models shared across layers."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Passage:
    """A chunk of a knowledge-base document with its similarity score."""

    source: str
    chunk_index: int
    text: str
    score: float = 0.0


@dataclass(frozen=True)
class SearchHit:
    """One web search result."""

    title: str
    url: str
    snippet: str


@dataclass(frozen=True)
class DocumentInfo:
    """A knowledge-base document and the number of chunks stored for it."""

    source: str
    chunks: int


@dataclass(frozen=True)
class IngestResult:
    """Outcome of storing one document."""

    source: str
    chunks: int
    characters: int
