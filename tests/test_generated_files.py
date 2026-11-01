"""Files under docs/api_integration/ are generated, so they must match the code."""

import json

from fastapi.testclient import TestClient

from scripts.export_schemas import build_collection, build_enums, build_files, render
from src.app import create_app
from tests.conftest import ROOT


def test_generated_files_are_up_to_date():
    for path, content in build_files().items():
        assert path.exists(), f"{path} is missing: run `make schemas`"
        assert path.read_text(encoding="utf-8") == render(content), (
            f"{path} is stale: run `make schemas`"
        )


def test_request_schema_reflects_the_models():
    schema = json.loads(
        (ROOT / "docs/api_integration/schemas/request_schema.json").read_text("utf-8")
    )
    assert set(schema) == {"TokenRequest", "ChatRequest", "KnowledgeSearchRequest"}
    assert schema["ChatRequest"]["additionalProperties"] is False
    assert set(schema["ChatRequest"]["required"]) == {"message", "session_id"}


def test_enums_cover_every_error_code_and_event_kind():
    enums = build_enums()
    assert {
        "validation_error",
        "invalid_input",
        "unauthorized",
        "llm_timeout",
        "llm_rate_limited",
        "llm_error",
        "external_service_error",
        "graph_error",
        "internal_error",
    } <= set(enums["error_codes"])
    assert enums["sse_events"] == ["token", "node", "tool", "final", "error"]
    assert "latency" in enums["trace_sources"] and enums["trace_topic"] == "omnivox.trace"
    assert enums["stt_providers"] == ["elevenlabs", "openai"]


def test_collection_has_every_documented_endpoint(settings):
    app = create_app(settings)
    documented = {
        (method.upper(), path)
        for path, operations in TestClient(app).get("/openapi.json").json()["paths"].items()
        for method in operations
    }
    in_collection = set()
    for item in build_collection()["item"]:
        request = item["request"]
        path = "/" + "/".join(request["url"]["path"])
        in_collection.add((request["method"], path))
    # {source} is a path parameter in the API and a sample value in the collection.
    normalized = {(m, p.replace("{source}", "pricing.md")) for m, p in documented}
    assert normalized == in_collection


def test_collection_uses_variables_and_the_v21_schema():
    collection = build_collection()
    assert collection["info"]["schema"].endswith("v2.1.0/collection.json")
    assert {v["key"] for v in collection["variable"]} == {"base_url", "api_key"}
    for item in collection["item"]:
        assert item["request"]["url"]["raw"].startswith("{{base_url}}/")
