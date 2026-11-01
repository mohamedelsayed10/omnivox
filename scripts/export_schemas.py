"""Generate the files under docs/api_integration/ from the code.

``uv run python scripts/export_schemas.py`` writes them; ``--check`` exits non-zero when they are
stale. Nothing in the generated files is written by hand.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, get_args

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import Settings
from src.api.error_handlers import HTTP_CODES
from src.api.schemas.requests import ChatRequest, KnowledgeSearchRequest, TokenRequest
from src.graph.streaming import SSEEventName
from src.utils.exceptions import OmniVoxError
from src.utils.trace_events import TRACE_TOPIC, TraceSource

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "api_integration"
POSTMAN_SCHEMA = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
BASE_URL_VARIABLE = "{{base_url}}"
API_PREFIX = "/api/v1"
EXTRA_ERROR_CODES = {"validation_error", "http_error"}


def _subclasses(cls: type) -> list[type]:
    found = [cls]
    for sub in cls.__subclasses__():
        found.extend(_subclasses(sub))
    return found


def _literal_values(field: str) -> list[str]:
    annotation = Settings.model_fields[field].annotation
    return sorted(str(value) for value in get_args(annotation) if isinstance(value, str))


def build_request_schema() -> dict[str, Any]:
    """JSON Schema of every request body."""
    models = {
        "TokenRequest": TokenRequest,
        "ChatRequest": ChatRequest,
        "KnowledgeSearchRequest": KnowledgeSearchRequest,
    }
    return {name: model.model_json_schema() for name, model in models.items()}


def build_enums() -> dict[str, Any]:
    """Closed value sets used by the API and the inspector."""
    error_codes = {cls.code for cls in _subclasses(OmniVoxError)}
    return {
        "error_codes": sorted(error_codes | set(HTTP_CODES.values()) | EXTRA_ERROR_CODES),
        "sse_events": list(get_args(SSEEventName)),
        "trace_sources": list(get_args(TraceSource)),
        "trace_topic": TRACE_TOPIC,
        "stt_providers": _literal_values("STT_PROVIDER"),
        "tts_providers": _literal_values("TTS_PROVIDER"),
        "turn_detectors": _literal_values("TURN_DETECTOR"),
        "tracing_providers": _literal_values("TRACING_PROVIDER"),
        "graph_memory_backends": _literal_values("GRAPH_MEMORY_BACKEND"),
    }


def _url(path: str) -> dict[str, Any]:
    return {
        "raw": f"{BASE_URL_VARIABLE}{path}",
        "host": [BASE_URL_VARIABLE],
        "path": [part for part in path.split("/") if part],
    }


def _request(
    name: str, method: str, path: str, description: str, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    headers = [{"key": "X-API-Key", "value": "{{api_key}}", "type": "text"}]
    request: dict[str, Any] = {
        "method": method,
        "header": headers,
        "url": _url(path),
        "description": description,
    }
    if body is not None:
        headers.append({"key": "Content-Type", "value": "application/json", "type": "text"})
        request["body"] = {
            "mode": "raw",
            "raw": json.dumps(body, indent=2),
            "options": {"raw": {"language": "json"}},
        }
    return {"name": name, "request": request}


def build_collection() -> dict[str, Any]:
    """Postman v2.1 collection with every endpoint (imports into Postman, Bruno and Insomnia)."""
    upload = _request(
        "Upload document",
        "POST",
        f"{API_PREFIX}/knowledge/documents",
        "Index a .txt, .md or .pdf file. Uploading the same name again replaces it.",
    )
    upload["request"]["body"] = {
        "mode": "formdata",
        "formdata": [
            {"key": "file", "type": "file", "src": []},
            {"key": "source", "type": "text", "value": "pricing.md", "disabled": True},
        ],
    }
    items = [
        _request("Health", "GET", "/health", "Liveness. Makes no external calls."),
        _request("Info", "GET", f"{API_PREFIX}/info", "Models and switches the service runs with."),
        _request(
            "Create LiveKit token",
            "POST",
            f"{API_PREFIX}/livekit/token",
            "Join token for the browser. A new room makes LiveKit dispatch the voice agent.",
            {"identity": "demo-user"},
        ),
        _request(
            "Chat (invoke)",
            "POST",
            f"{API_PREFIX}/agent/invoke",
            "Run one message through the agent graph and return the answer.",
            {"session_id": "demo", "message": "What is the capital of France?"},
        ),
        _request(
            "Chat (stream, SSE)",
            "POST",
            f"{API_PREFIX}/agent/stream",
            "Server-sent events: node, tool, token, then final or error.",
            {"session_id": "demo", "message": "Search the web for today's top headline."},
        ),
        upload,
        _request(
            "List documents", "GET", f"{API_PREFIX}/knowledge/documents", "Indexed documents."
        ),
        _request(
            "Delete document",
            "DELETE",
            f"{API_PREFIX}/knowledge/documents/pricing.md",
            "Remove a document and its chunks.",
        ),
        _request(
            "Search knowledge base",
            "POST",
            f"{API_PREFIX}/knowledge/search",
            "Passages closest to a query.",
            {"query": "What does the pricing plan cost?", "top_k": 4},
        ),
    ]
    return {
        "info": {
            "name": "OmniVox API",
            "description": "Voice agent API. Set base_url, and api_key when API_KEYS is set.",
            "schema": POSTMAN_SCHEMA,
        },
        "variable": [
            {"key": "base_url", "value": "http://localhost:8100"},
            {"key": "api_key", "value": ""},
        ],
        "item": items,
    }


def build_files() -> dict[Path, dict[str, Any]]:
    """Every generated file and its content."""
    return {
        OUTPUT_DIR / "schemas" / "request_schema.json": build_request_schema(),
        OUTPUT_DIR / "schemas" / "enums.json": build_enums(),
        OUTPUT_DIR / "collections" / "collection.json": build_collection(),
    }


def render(content: dict[str, Any]) -> str:
    """Stable text form of a generated file."""
    return json.dumps(content, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail when files are out of date")
    args = parser.parse_args()
    stale = []
    for path, content in build_files().items():
        text = render(content)
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(path)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path.relative_to(OUTPUT_DIR.parent.parent)}")
    if stale:
        print("stale: " + ", ".join(str(p) for p in stale) + " (run make schemas)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
