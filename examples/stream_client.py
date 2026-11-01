"""Stream one chat turn over SSE and print node, tool and token events as they arrive.

Run: ``uv run python examples/stream_client.py "your question"``. Reads OMNIVOX_BASE_URL
(default http://localhost:8100) and OMNIVOX_API_KEY (optional).
"""

import json
import os
import sys
import uuid

import httpx

BASE_URL = os.environ.get("OMNIVOX_BASE_URL", "http://localhost:8100")
API_KEY = os.environ.get("OMNIVOX_API_KEY", "")
DEFAULT_QUESTION = (
    "Search the web for today's top technology headline and summarize it in one sentence."
)
TIMEOUT_SECONDS = 120


def sse_events(response: httpx.Response):
    """Yield (event, data) pairs from a text/event-stream response."""
    event, data = "message", ""
    for line in response.iter_lines():
        if line.startswith("event: "):
            event = line[7:]
        elif line.startswith("data: "):
            data = line[6:]
        elif not line and data:
            yield event, json.loads(data)
            event, data = "message", ""


def main() -> int:
    question = " ".join(sys.argv[1:]) or DEFAULT_QUESTION
    headers = {"X-API-Key": API_KEY} if API_KEY else {}
    body = {"session_id": f"stream-{uuid.uuid4().hex[:8]}", "message": question}
    with httpx.stream(
        "POST",
        f"{BASE_URL}/api/v1/agent/stream",
        json=body,
        headers=headers,
        timeout=TIMEOUT_SECONDS,
    ) as response:
        if response.is_error:
            response.read()
            print(f"HTTP {response.status_code}: {response.text}", file=sys.stderr)
            return 1
        for event, data in sse_events(response):
            if event == "token":
                print(data["text"], end="", flush=True)
            elif event == "node":
                duration = f" ({data['duration_ms']} ms)" if "duration_ms" in data else ""
                print(f"\n[node {data['name']} {data['phase']}{duration}]", flush=True)
            elif event == "tool":
                print(f"\n[tool {data['name']} {data['phase']}] {data.get('args', '')}", flush=True)
            elif event == "final":
                print(f"\n\nFinal answer: {data['answer']}")
            elif event == "error":
                print(
                    f"\nError {data['code']}: {data['message']} (request {data['request_id']})",
                    file=sys.stderr,
                )
                return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
