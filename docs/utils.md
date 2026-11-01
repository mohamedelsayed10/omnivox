# Helpers

Pure helpers and data models in `src/utils/`. They import nothing from other `src` layers.

## `src/utils/text.py`

| Function | Purpose |
| --- | --- |
| `normalize_text(text) -> str` | Normalize line endings, drop NUL, collapse runs of spaces and blank lines, trim. |
| `truncate(text, limit) -> str` | Cut to at most `limit` characters, ending with `…` when cut. |
| `escape_tags(text) -> str` | Replace `<` and `>` with look-alike single quotation marks so untrusted text cannot close the tag around it. |
| `chunk_text(text, size, overlap) -> list[str]` | Split into chunks of at most `size` characters on paragraph and sentence boundaries; each chunk starts with the last `overlap` characters of the previous one. Raises `ValueError` unless `0 <= overlap < size`. |

```python
from src.utils.text import chunk_text, truncate

chunk_text(
    "First paragraph.\n\nSecond paragraph.", 20, 0
)  # ['First paragraph.', 'Second paragraph.']
truncate("x" * 20, 10)  # 'xxxxxxxxx…'
```

## `src/utils/models.py`

Frozen dataclasses: `Passage(source, chunk_index, text, score)`, `SearchHit(title, url, snippet)`, `DocumentInfo(source, chunks)`, `IngestResult(source, chunks, characters)`.

## `src/utils/trace_events.py`

`TraceEvent(source, type, label, data, duration_ms, turn, ts, id)` with `to_dict()` for the wire format described in [voice.md](voice.md#inspector). `TRACE_TOPIC = "omnivox.trace"` and the `TraceSource` literal. Constructing an event is the only thing the graph, the voice inspector and the SSE stream need to agree on.

```python
from src.utils.trace_events import TraceEvent

TraceEvent(
    "tool", "end", "Tool web_search returned", {"name": "web_search"}, duration_ms=120.5
).to_dict()
```

## `src/utils/exceptions.py`

Framework-free domain errors. `str(exc)` is for logs; `exc.public_message` is what a client may see (generic unless `expose_message` is true).

| Class | `code` | Typical cause |
| --- | --- | --- |
| `InvalidInputError` | `invalid_input` | Business-rule violation; message is shown to the client |
| `NotFoundError` | `not_found` | Unknown document |
| `UnauthorizedError` | `unauthorized` | Bad API key |
| `LLMError` | `llm_error` | Provider failure, empty or blocked output |
| `LLMTimeoutError`, `LLMRateLimitError` | `llm_timeout`, `llm_rate_limited` | Subclasses of `LLMError` |
| `ExternalServiceError` | `external_service_error` | Qdrant, embeddings or web search down |
| `GraphExecutionError` | `graph_error` | Graph failure or step limit |
| `ConfigurationError` | `service_not_configured` | Feature used without its configuration |

The HTTP mapping lives in `src/api/error_handlers.py`.
