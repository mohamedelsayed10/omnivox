"""Health endpoint, request ids and request validation."""

import pytest

from tests.fakes import ai


def test_health_payload(make_client):
    response = make_client().get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok" and body["service"] == "omnivox"
    assert set(body) == {"status", "service", "version", "env", "uptime_seconds"}
    assert body["uptime_seconds"] >= 0


def test_health_needs_no_api_key_and_makes_no_model_calls(make_client, make_settings):
    client = make_client([], make_settings(API_KEYS="secret-key-123456"))
    assert client.get("/health").status_code == 200
    assert client.app.state.container.runtime.llm.get_model().seen == []


def test_request_id_is_generated_echoed_and_sanitized(make_client):
    client = make_client()
    generated = client.get("/health").headers["X-Request-ID"]
    assert len(generated) == 32
    assert (
        client.get("/health", headers={"X-Request-ID": "trace-abc.123"}).headers["X-Request-ID"]
        == "trace-abc.123"
    )
    replaced = client.get("/health", headers={"X-Request-ID": "bad id with spaces"}).headers[
        "X-Request-ID"
    ]
    assert replaced != "bad id with spaces" and len(replaced) == 32


@pytest.mark.parametrize(
    "path,body,field",
    [
        ("/api/v1/agent/invoke", {"message": "hi"}, "session_id"),
        ("/api/v1/agent/invoke", {"session_id": "s"}, "message"),
        ("/api/v1/agent/invoke", {"session_id": "s", "message": "hi", "extra": 1}, "extra"),
        ("/api/v1/agent/invoke", {"session_id": "bad id!", "message": "hi"}, "session_id"),
        ("/api/v1/agent/invoke", {"session_id": "s" * 65, "message": "hi"}, "session_id"),
        ("/api/v1/agent/invoke", {"session_id": "s", "message": "   "}, "message"),
        ("/api/v1/agent/invoke", {"session_id": "s", "message": "x" * 20001}, "message"),
        ("/api/v1/agent/stream", {"session_id": "s", "message": 5}, "message"),
        ("/api/v1/knowledge/search", {"query": ""}, "query"),
        ("/api/v1/knowledge/search", {"query": "q", "top_k": 0}, "top_k"),
        ("/api/v1/knowledge/search", {"query": "q", "top_k": 21}, "top_k"),
        ("/api/v1/livekit/token", {"identity": "has space"}, "identity"),
        ("/api/v1/livekit/token", {"room": "r" * 65}, "room"),
        ("/api/v1/livekit/token", {"unknown": True}, "unknown"),
    ],
)
def test_invalid_bodies_get_the_validation_error_schema(make_client, path, body, field):
    response = make_client().post(path, json=body)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["request_id"] == response.headers["X-Request-ID"]
    assert field in {part for issue in error["details"] for part in issue["loc"]}
    assert all(set(issue) == {"loc", "msg", "type"} for issue in error["details"])  # no input echo


def test_malformed_json_is_a_validation_error(make_client):
    response = make_client().post(
        "/api/v1/agent/invoke", content=b"{not json", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422 and response.json()["error"]["code"] == "validation_error"


def test_unknown_input_never_reaches_the_model(make_client):
    client = make_client([ai("never")])
    client.post("/api/v1/agent/invoke", json={"session_id": "s", "message": "hi", "extra": 1})
    assert client.app.state.container.runtime.llm.get_model().seen == []
