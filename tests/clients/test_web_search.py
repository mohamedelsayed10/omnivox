"""Web search client around ddgs."""

import time
from typing import ClassVar

import pytest
from ddgs.exceptions import DDGSException

from src.clients import web_search
from src.clients.web_search import WebSearchClient
from src.utils.exceptions import ExternalServiceError


class FakeDDGS:
    results: ClassVar[list[dict]] = []
    error: Exception | None = None
    delay: float = 0.0
    calls: ClassVar[list[dict]] = []

    def __init__(self, timeout: int = 5) -> None:
        self.timeout = timeout

    def __enter__(self) -> "FakeDDGS":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def text(self, query: str, region: str, max_results: int) -> list[dict]:
        FakeDDGS.calls.append({"query": query, "region": region, "max_results": max_results})
        time.sleep(FakeDDGS.delay)
        if FakeDDGS.error:
            raise FakeDDGS.error
        return FakeDDGS.results[:max_results]


@pytest.fixture(autouse=True)
def fake_ddgs(monkeypatch):
    FakeDDGS.results, FakeDDGS.error, FakeDDGS.delay, FakeDDGS.calls = [], None, 0.0, []
    monkeypatch.setattr(web_search, "DDGS", FakeDDGS)
    return FakeDDGS


async def test_results_are_mapped_and_limited(make_settings):
    FakeDDGS.results = [
        {"title": f" T{i} ", "href": f"https://site{i}.test/x", "body": f"Body {i}"}
        for i in range(8)
    ]
    client = WebSearchClient(make_settings(WEB_SEARCH_MAX_RESULTS=3, WEB_SEARCH_REGION="uk-en"))
    hits = await client.search("python news")
    assert [h.title for h in hits] == ["T0", "T1", "T2"]
    assert hits[0].url == "https://site0.test/x" and hits[0].snippet == "Body 0"
    assert FakeDDGS.calls == [{"query": "python news", "region": "uk-en", "max_results": 3}]


async def test_explicit_max_results_wins(settings):
    FakeDDGS.results = [{"title": "t", "href": "h", "body": "b"}] * 10
    assert len(await WebSearchClient(settings).search("q", max_results=2)) == 2


async def test_library_errors_become_external_service_errors(settings):
    FakeDDGS.error = DDGSException("rate limited")
    with pytest.raises(ExternalServiceError, match="rate limited"):
        await WebSearchClient(settings).search("q")


async def test_a_hung_search_times_out(make_settings, monkeypatch):
    monkeypatch.setattr(web_search, "THREAD_TIMEOUT_MARGIN", 0.0)
    FakeDDGS.delay = 0.6
    client = WebSearchClient(make_settings(WEB_SEARCH_TIMEOUT=0.1))
    with pytest.raises(ExternalServiceError, match="timed out"):
        await client.search("q")
