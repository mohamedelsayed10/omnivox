"""Happy paths of every route."""

import json

import jwt

from src.utils.models import SearchHit
from tests.fakes import ai

HITS = [SearchHit("Paris", "https://example.org/paris", "Paris is the capital of France.")]
PRICING = b"Our pricing plan costs ten dollars per month for each seat."


def parse_sse(text: str) -> list[tuple[str, dict]]:
    frames = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        frames.append((lines["event"], json.loads(lines["data"])))
    return frames


def test_info_lists_models_and_flags_without_secrets(make_client):
    response = make_client().get("/api/v1/info")
    assert response.status_code == 200
    body = response.json()
    assert body["llm_model"] == "gemini-3-flash-preview"
    assert (body["stt_provider"], body["stt_model"]) == ("elevenlabs", "scribe_v2_realtime")
    assert (body["tts_provider"], body["tts_model"]) == ("elevenlabs", "eleven_v4_turbo")
    assert body["embedding_model"] == "embed-v5.0-fast"
    assert body["turn_detector"] == "audio" and body["auth_required"] is False
    assert body["knowledge_base_configured"] is True
    assert "key" not in " ".join(body).lower().replace("api_key", "")
    assert "test-key" not in response.text


def test_livekit_token_is_signed_for_the_requested_room(make_client, settings):
    response = make_client().post(
        "/api/v1/livekit/token", json={"identity": "alice", "room": "r-1"}
    )
    assert response.status_code == 200
    body = response.json()
    assert (body["room"], body["identity"], body["url"]) == (
        "r-1",
        "alice",
        settings.LIVEKIT_PUBLIC_URL,
    )
    claims = jwt.decode(
        body["token"], settings.LIVEKIT_API_SECRET.get_secret_value(), algorithms=["HS256"]
    )
    assert claims["sub"] == "alice" and claims["video"]["room"] == "r-1"


def test_livekit_token_generates_names_for_an_empty_body(make_client):
    body = make_client().post("/api/v1/livekit/token", json={}).json()
    assert body["room"].startswith("omnivox-") and body["identity"].startswith("user-")


def test_invoke_returns_the_answer_tools_and_request_id(make_client):
    script = [ai("Checking.", ("web_search", {"query": "capital of France"})), ai("It is Paris.")]
    client = make_client(script, hits=HITS)
    response = client.post(
        "/api/v1/agent/invoke", json={"session_id": "s-1", "message": "capital?"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "session_id": "s-1",
        "answer": "It is Paris.",
        "tools_used": ["web_search"],
        "request_id": response.headers["X-Request-ID"],
    }


def test_invoke_remembers_the_session(make_client):
    client = make_client([ai("first"), ai("second")])
    client.post("/api/v1/agent/invoke", json={"session_id": "mem", "message": "one"})
    client.post("/api/v1/agent/invoke", json={"session_id": "mem", "message": "two"})
    seen = client.app.state.container.runtime.llm.get_model().seen
    texts = [[m.content for m in call if m.type == "human"] for call in seen]
    assert texts == [["one"], ["one", "two"]]


def test_stream_sends_sse_headers_and_ordered_events(make_client):
    script = [ai("Let me check.", ("web_search", {"query": "capital"})), ai("It is Paris.")]
    client = make_client(script, hits=HITS)
    with client.stream(
        "POST", "/api/v1/agent/stream", json={"session_id": "s", "message": "q"}
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-cache"
        assert response.headers["x-accel-buffering"] == "no"
        text = "".join(response.iter_text())
    frames = parse_sse(text)
    names = [name for name, _ in frames]
    assert names[-1] == "final" and names.count("final") == 1
    assert {"node", "tool", "token"} <= set(names)
    assert frames[-1][1] == {"answer": "It is Paris.", "session_id": "s"}


def test_stream_reports_failures_as_a_final_error_event(make_client):
    client = make_client([])  # the scripted model fails immediately
    with client.stream(
        "POST", "/api/v1/agent/stream", json={"session_id": "s", "message": "q"}
    ) as response:
        assert response.status_code == 200
        frames = parse_sse("".join(response.iter_text()))
    name, data = frames[-1]
    assert name == "error" and data["code"] == "llm_error"
    assert data["request_id"] == response.headers["X-Request-ID"]
    assert [n for n, _ in frames].count("error") == 1


def test_knowledge_round_trip_over_http(make_client):
    client = make_client()
    uploaded = client.post(
        "/api/v1/knowledge/documents",
        files={"file": ("pricing.md", PRICING, "text/markdown")},
    )
    assert uploaded.status_code == 200
    assert uploaded.json() == {"source": "pricing.md", "chunks": 1, "characters": len(PRICING)}

    renamed = client.post(
        "/api/v1/knowledge/documents",
        files={"file": ("x.txt", b"The office opens at nine.", "text/plain")},
        data={"source": "office.txt"},
    )
    assert renamed.json()["source"] == "office.txt"

    listed = client.get("/api/v1/knowledge/documents").json()["documents"]
    assert listed == [{"source": "office.txt", "chunks": 1}, {"source": "pricing.md", "chunks": 1}]

    found = client.post(
        "/api/v1/knowledge/search", json={"query": "pricing plan cost", "top_k": 1}
    ).json()
    assert len(found["results"]) == 1
    assert found["results"][0]["source"] == "pricing.md"
    assert set(found["results"][0]) == {"source", "chunk_index", "score", "text"}

    deleted = client.delete("/api/v1/knowledge/documents/pricing.md")
    assert deleted.json() == {"source": "pricing.md", "deleted_chunks": 1}
    assert [d["source"] for d in client.get("/api/v1/knowledge/documents").json()["documents"]] == [
        "office.txt"
    ]


def test_valid_api_key_unlocks_the_api(make_client, make_settings):
    client = make_client([ai("hi")], make_settings(API_KEYS="good-key-123456"))
    response = client.post(
        "/api/v1/agent/invoke",
        json={"session_id": "s", "message": "hello"},
        headers={"X-API-Key": "good-key-123456"},
    )
    assert response.status_code == 200
    assert (
        client.get("/api/v1/info", headers={"X-API-Key": "good-key-123456"}).json()["auth_required"]
        is True
    )


def test_cors_allows_the_gui_origin_and_exposes_the_request_id(make_client):
    client = make_client()
    response = client.options(
        "/api/v1/agent/invoke",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"},
    )
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    simple = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert "x-request-id" in simple.headers["access-control-expose-headers"].lower()
    blocked = client.get("/health", headers={"Origin": "http://evil.test"})
    assert "access-control-allow-origin" not in blocked.headers
