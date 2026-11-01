"""Minimal httpx client for the OmniVox API.

Run: ``uv run python examples/client.py``. Reads OMNIVOX_BASE_URL (default
http://localhost:8100) and OMNIVOX_API_KEY (optional).
"""

import json
import os
from pathlib import Path

import httpx

BASE_URL = os.environ.get("OMNIVOX_BASE_URL", "http://localhost:8100")
API_KEY = os.environ.get("OMNIVOX_API_KEY", "")
HERE = Path(__file__).parent
TIMEOUT_SECONDS = 90


class OmniVoxClient:
    """Thin wrapper that adds the API key and raises with the server's error body."""

    def __init__(self, base_url: str = BASE_URL, api_key: str = API_KEY) -> None:
        headers = {"X-API-Key": api_key} if api_key else {}
        self._http = httpx.Client(base_url=base_url, headers=headers, timeout=TIMEOUT_SECONDS)

    def _json(self, response: httpx.Response) -> dict:
        if response.is_error:
            error = response.json().get("error", {})
            raise RuntimeError(
                f"{response.status_code} {error.get('code')}: {error.get('message')} "
                f"(request_id={error.get('request_id')})"
            )
        return response.json()

    def health(self) -> dict:
        return self._json(self._http.get("/health"))

    def info(self) -> dict:
        return self._json(self._http.get("/api/v1/info"))

    def livekit_token(self, identity: str | None = None, room: str | None = None) -> dict:
        body = {k: v for k, v in {"identity": identity, "room": room}.items() if v}
        return self._json(self._http.post("/api/v1/livekit/token", json=body))

    def chat(self, session_id: str, message: str) -> dict:
        body = {"session_id": session_id, "message": message}
        return self._json(self._http.post("/api/v1/agent/invoke", json=body))

    def upload(self, path: Path, source: str | None = None) -> dict:
        files = {"file": (path.name, path.read_bytes())}
        data = {"source": source} if source else {}
        return self._json(self._http.post("/api/v1/knowledge/documents", files=files, data=data))

    def documents(self) -> dict:
        return self._json(self._http.get("/api/v1/knowledge/documents"))

    def search(self, query: str, top_k: int | None = None) -> dict:
        body = {"query": query, **({"top_k": top_k} if top_k else {})}
        return self._json(self._http.post("/api/v1/knowledge/search", json=body))

    def delete(self, source: str) -> dict:
        return self._json(self._http.delete(f"/api/v1/knowledge/documents/{source}"))


def show(title: str, value: dict) -> None:
    print(f"\n## {title}\n{json.dumps(value, indent=2, ensure_ascii=False)}")


def main() -> None:
    client = OmniVoxClient()
    show("health", client.health())
    show("info", client.info())
    show("chat", client.chat("example-session", "What is the capital of France? One sentence."))
    sample = HERE / "sample_document.md"
    show("upload", client.upload(sample))
    show("search", client.search("How long does the free trial last?", top_k=2))
    show(
        "chat with knowledge",
        client.chat("example-kb", "Using my documents, how long is the free trial?"),
    )
    show("delete", client.delete(sample.name))


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        raise SystemExit(f"API error: {error}") from error
