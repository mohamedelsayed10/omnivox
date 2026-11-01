"""Retriever: ingestion, replacement and similarity search on fakes."""

import pytest

from src.ai_models.embeddings import EmbeddingService
from src.clients.qdrant import QdrantStore
from src.rag.retriever import Retriever
from src.utils.exceptions import ExternalServiceError, InvalidInputError
from tests.fakes import DeterministicEmbeddings

PRICING = "Our pricing plan costs ten dollars per month for each seat. Annual billing is cheaper."
OFFICE = "The Cairo office is located near the river and opens at nine in the morning."


def make_retriever(settings, fake: DeterministicEmbeddings | None = None) -> Retriever:
    fake = fake or DeterministicEmbeddings()
    return Retriever(settings, EmbeddingService(settings, embeddings=fake), QdrantStore(settings))


@pytest.fixture
async def retriever(settings):
    instance = make_retriever(settings)
    yield instance
    await instance.close()


async def test_search_finds_the_relevant_document(retriever):
    await retriever.ingest("pricing.md", PRICING)
    await retriever.ingest("office.md", OFFICE)
    passages = await retriever.search("what does the pricing plan cost per month")
    assert passages[0].source == "pricing.md"
    assert "ten dollars" in passages[0].text
    assert passages[0].score > passages[-1].score or len(passages) == 1


async def test_top_k_limits_results(make_settings):
    retriever = make_retriever(make_settings(RAG_CHUNK_SIZE=120, RAG_CHUNK_OVERLAP=20, RAG_TOP_K=2))
    await retriever.ingest(
        "long.md", " ".join(f"Topic {i} is about pricing detail {i}." for i in range(20))
    )
    assert len(await retriever.search("pricing")) == 2
    assert len(await retriever.search("pricing", top_k=5)) == 5


async def test_score_threshold_drops_unrelated_passages(make_settings):
    retriever = make_retriever(make_settings(RAG_SCORE_THRESHOLD=0.5))
    await retriever.ingest("office.md", OFFICE)
    assert await retriever.search("quantum chromodynamics lattice") == []


async def test_reingesting_replaces_the_previous_chunks(make_settings):
    retriever = make_retriever(make_settings(RAG_CHUNK_SIZE=120, RAG_CHUNK_OVERLAP=20))
    long_text = " ".join(f"Sentence {i} about the product." for i in range(30))
    first = await retriever.ingest("doc.md", long_text)
    assert first.chunks > 3
    second = await retriever.ingest("doc.md", "Short replacement.")
    assert second.chunks == 1
    documents = await retriever.list_documents()
    assert [(d.source, d.chunks) for d in documents] == [("doc.md", 1)]


async def test_failed_embedding_keeps_the_old_document(settings):
    fake = DeterministicEmbeddings()
    retriever = make_retriever(settings, fake)
    await retriever.ingest("doc.md", PRICING)
    fake._fail_with = RuntimeError("embedding service down")
    with pytest.raises(ExternalServiceError):
        await retriever.ingest("doc.md", OFFICE)
    fake._fail_with = None
    assert [d.chunks for d in await retriever.list_documents()] == [1]


async def test_ingest_reports_counts_and_rejects_empty_text(retriever):
    result = await retriever.ingest("a.md", PRICING)
    assert (result.source, result.chunks, result.characters) == ("a.md", 1, len(PRICING))
    with pytest.raises(InvalidInputError):
        await retriever.ingest("b.md", "   ")


async def test_delete_document(retriever):
    await retriever.ingest("a.md", PRICING)
    assert await retriever.delete_document("a.md") == 1
    assert await retriever.list_documents() == []
    assert await retriever.search("pricing") == []
