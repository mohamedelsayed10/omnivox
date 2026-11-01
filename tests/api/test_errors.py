"""Every row of the error table: status, code, request id, and no leaked internals."""

import pytest

from src.utils.exceptions import (
    ConfigurationError,
    ExternalServiceError,
    GraphExecutionError,
    InvalidInputError,
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
    NotFoundError,
)

SECRET = "AIza" + "S" * 35
CHAT_BODY = {"session_id": "s", "message": "hello"}


def raising(error: Exception):
    async def fail(*args, **kwargs):
        raise error

    return fail


@pytest.mark.parametrize(
    "error,status,code",
    [
        (InvalidInputError("Bad input for the client."), 400, "invalid_input"),
        (NotFoundError("No such thing."), 404, "not_found"),
        (LLMTimeoutError(f"provider timeout {SECRET}"), 504, "llm_timeout"),
        (LLMRateLimitError(f"429 from provider {SECRET}"), 429, "llm_rate_limited"),
        (LLMError(f"provider body: key={SECRET}"), 502, "llm_error"),
        (
            ExternalServiceError(f"qdrant at http://10.0.0.5 failed {SECRET}"),
            502,
            "external_service_error",
        ),
        (GraphExecutionError(f"node exploded {SECRET}"), 500, "graph_error"),
        (ConfigurationError("Embeddings are not configured."), 503, "service_not_configured"),
        (RuntimeError(f"unexpected {SECRET}"), 500, "internal_error"),
    ],
)
def test_domain_and_unexpected_errors_map_to_the_standard_body(
    make_client, monkeypatch, error, status, code
):
    client = make_client()
    monkeypatch.setattr(client.app.state.container.chat, "invoke", raising(error))
    response = client.post("/api/v1/agent/invoke", json=CHAT_BODY)

    assert response.status_code == status
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == code
    assert body["error"]["request_id"] == response.headers["X-Request-ID"]
    assert SECRET not in response.text and "10.0.0.5" not in response.text
    assert "Traceback" not in response.text
    if not getattr(error, "expose_message", False):
        assert body["error"]["message"] == getattr(
            error, "default_message", "An internal error occurred."
        )


def test_client_facing_messages_are_exposed_for_input_errors(make_client, monkeypatch):
    client = make_client()
    monkeypatch.setattr(
        client.app.state.container.chat,
        "invoke",
        raising(InvalidInputError("Too long, shorten it.")),
    )
    assert (
        client.post("/api/v1/agent/invoke", json=CHAT_BODY).json()["error"]["message"]
        == "Too long, shorten it."
    )


def test_missing_and_wrong_api_keys_are_unauthorized(make_client, make_settings):
    client = make_client([], make_settings(API_KEYS="first-key-123456,second-key-654321"))
    for headers in (
        {},
        {"X-API-Key": "wrong"},
        {"X-API-Key": "first-key-12345"},
        {"X-API-Key": bytes([0xE9])},
    ):
        response = client.post("/api/v1/agent/invoke", json=CHAT_BODY, headers=headers)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthorized"
        assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
    assert client.get("/api/v1/info", headers={"X-API-Key": "second-key-654321"}).status_code == 200


def test_unauthorized_requests_never_reach_the_services(make_client, make_settings):
    client = make_client([], make_settings(API_KEYS="first-key-123456"))
    client.post("/api/v1/agent/invoke", json=CHAT_BODY)
    assert client.app.state.container.runtime.llm.get_model().seen == []


def test_unsupported_upload_is_an_invalid_input_error(make_client):
    response = make_client().post(
        "/api/v1/knowledge/documents", files={"file": ("photo.png", b"data", "image/png")}
    )
    assert response.status_code == 400 and response.json()["error"]["code"] == "invalid_input"


def test_search_without_an_embedding_key_is_service_not_configured(make_client, make_settings):
    client = make_client([], make_settings(EMBEDDING_API_KEY=None), embeddings=None)
    container = client.app.state.container
    container.runtime.embeddings._embeddings = None  # the fake client is only for configured setups
    response = client.post("/api/v1/knowledge/search", json={"query": "pricing"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_not_configured"


def test_unknown_route_and_method(make_client):
    client = make_client()
    missing = client.get("/api/v1/nothing-here")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"
    wrong_method = client.get("/api/v1/agent/invoke")
    assert wrong_method.status_code == 405
    assert wrong_method.json()["error"]["code"] == "method_not_allowed"
    assert wrong_method.json()["error"]["request_id"] == wrong_method.headers["X-Request-ID"]


def test_deleting_a_missing_document_is_404(make_client):
    response = make_client().delete("/api/v1/knowledge/documents/ghost.md")
    assert response.status_code == 404 and response.json()["error"]["code"] == "not_found"


def test_oversized_bodies_are_rejected_with_413(make_client, make_settings):
    client = make_client([], make_settings(MAX_BODY_BYTES=1024))
    declared = client.post(
        "/api/v1/agent/invoke", content=b"x" * 2048, headers={"Content-Type": "application/json"}
    )
    assert declared.status_code == 413
    assert declared.json()["error"]["code"] == "payload_too_large"
    assert declared.json()["error"]["request_id"] == declared.headers["X-Request-ID"]

    def chunks():
        for _ in range(4):
            yield b"y" * 600

    chunked = client.post(
        "/api/v1/agent/invoke", content=chunks(), headers={"Content-Type": "application/json"}
    )
    assert chunked.status_code == 413


def test_error_responses_leave_the_service_usable(make_client, monkeypatch):
    client = make_client()
    original = client.app.state.container.chat.invoke
    monkeypatch.setattr(client.app.state.container.chat, "invoke", raising(RuntimeError("once")))
    assert client.post("/api/v1/agent/invoke", json=CHAT_BODY).status_code == 500
    monkeypatch.setattr(client.app.state.container.chat, "invoke", original)
    assert client.get("/health").status_code == 200


def test_a_message_over_the_configured_limit_is_a_normal_error_on_the_stream_route(
    make_client, make_settings
):
    client = make_client([], make_settings(MAX_INPUT_CHARS=10))
    response = client.post("/api/v1/agent/stream", json={"session_id": "s", "message": "x" * 11})
    assert response.status_code == 400  # not a 200 stream that breaks halfway
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == "invalid_input"
