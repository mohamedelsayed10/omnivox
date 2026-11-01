"""Qdrant store on the in-memory engine."""

import pytest
from qdrant_client.http.exceptions import ResponseHandlingException

from src.clients.qdrant import QdrantStore, point_id
from src.utils.exceptions import ExternalServiceError

DIM = 4
A = [1.0, 0.0, 0.0, 0.0]
B = [0.0, 1.0, 0.0, 0.0]
C = [0.7, 0.7, 0.0, 0.0]


@pytest.fixture
async def store(settings):
    instance = QdrantStore(settings)
    yield instance
    await instance.close()


async def test_search_on_a_missing_collection_is_empty(store):
    assert await store.search(A, top_k=3, score_threshold=None) == []
    assert await store.list_documents() == []
    assert await store.delete_document("nothing") == 0


async def test_upsert_search_orders_by_similarity(store):
    await store.ensure_collection(DIM)
    await store.upsert("doc-a", ["about a", "also a"], [A, C])
    await store.upsert("doc-b", ["about b"], [B])
    hits = await store.search(A, top_k=3, score_threshold=None)
    assert [(h.source, h.chunk_index) for h in hits] == [("doc-a", 0), ("doc-a", 1), ("doc-b", 0)]
    assert hits[0].text == "about a"
    assert hits[0].score >= hits[1].score >= hits[2].score


async def test_score_threshold_filters_weak_matches(store):
    await store.ensure_collection(DIM)
    await store.upsert("doc-a", ["about a"], [A])
    await store.upsert("doc-b", ["about b"], [B])
    hits = await store.search(A, top_k=5, score_threshold=0.9)
    assert [h.source for h in hits] == ["doc-a"]


async def test_ensure_collection_is_idempotent_and_checks_dimension(store):
    await store.ensure_collection(DIM)
    await store.ensure_collection(DIM)
    with pytest.raises(ExternalServiceError, match="4-dimension"):
        await store.ensure_collection(DIM + 1)


async def test_list_and_delete_documents(store):
    await store.ensure_collection(DIM)
    await store.upsert("doc-a", ["1", "2", "3"], [A, B, C])
    await store.upsert("doc-b", ["1"], [B])
    listed = await store.list_documents()
    assert [(d.source, d.chunks) for d in listed] == [("doc-a", 3), ("doc-b", 1)]
    assert await store.delete_document("doc-a") == 3
    assert [d.source for d in await store.list_documents()] == ["doc-b"]
    assert await store.delete_document("doc-a") == 0


async def test_upserting_the_same_chunk_overwrites_it(store):
    await store.ensure_collection(DIM)
    await store.upsert("doc", ["old"], [A])
    await store.upsert("doc", ["new"], [A])
    hits = await store.search(A, top_k=5, score_threshold=None)
    assert [h.text for h in hits] == ["new"]


def test_point_ids_are_stable_and_distinct():
    assert point_id("doc", 0) == point_id("doc", 0)
    assert point_id("doc", 0) != point_id("doc", 1)
    assert point_id("doc", 0) != point_id("other", 0)


async def test_server_errors_become_external_service_errors(store, monkeypatch):
    async def failing(*args, **kwargs):
        raise ResponseHandlingException(ConnectionError("refused"))

    monkeypatch.setattr(store._client, "collection_exists", failing)
    with pytest.raises(ExternalServiceError, match="Qdrant"):
        await store.search(A, top_k=1, score_threshold=None)
    with pytest.raises(ExternalServiceError):
        await store.list_documents()
