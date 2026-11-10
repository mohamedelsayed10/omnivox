"""Embedding service: batching, order, dimension probe, error mapping and configuration."""

import pytest

from src.ai_models.base import PLACEHOLDER_API_KEY
from src.ai_models.embeddings import EmbeddingService, build_embeddings
from src.utils.exceptions import ConfigurationError, ExternalServiceError
from tests.fakes import EMBEDDING_DIMENSION, DeterministicEmbeddings


async def test_documents_are_split_into_batches_and_keep_their_order(make_settings):
    fake = DeterministicEmbeddings()
    service = EmbeddingService(make_settings(EMBEDDING_BATCH_SIZE=2), embeddings=fake)
    texts = ["alpha one", "beta two", "gamma three", "delta four", "epsilon five"]
    vectors = await service.aembed_documents(texts)
    assert sorted(len(batch) for batch in fake.batches) == [1, 2, 2]
    assert vectors == [fake._vector(text) for text in texts]


async def test_no_texts_means_no_calls(settings):
    fake = DeterministicEmbeddings()
    assert await EmbeddingService(settings, embeddings=fake).aembed_documents([]) == []
    assert fake.batches == []


async def test_query_embedding(settings):
    fake = DeterministicEmbeddings()
    vector = await EmbeddingService(settings, embeddings=fake).aembed_query("hello world")
    assert len(vector) == EMBEDDING_DIMENSION
    assert fake.queries == ["hello world"]


async def test_dimension_is_probed_once(settings):
    fake = DeterministicEmbeddings()
    service = EmbeddingService(settings, embeddings=fake)
    assert await service.dimension() == EMBEDDING_DIMENSION
    assert await service.dimension() == EMBEDDING_DIMENSION
    assert len(fake.queries) == 1


@pytest.mark.parametrize("method", ["documents", "query"])
async def test_provider_errors_become_external_service_errors(settings, method):
    service = EmbeddingService(settings, embeddings=DeterministicEmbeddings(RuntimeError("boom")))
    with pytest.raises(ExternalServiceError) as caught:
        if method == "documents":
            await service.aembed_documents(["x"])
        else:
            await service.aembed_query("x")
    assert isinstance(caught.value.__cause__, RuntimeError)


async def test_missing_key_raises_configuration_error_only_when_used(make_settings):
    settings = make_settings(EMBEDDING_API_KEY=None)
    service = EmbeddingService(settings)
    assert service.configured is False
    with pytest.raises(ConfigurationError):
        await service.aembed_query("x")


def test_client_uses_the_openai_compatible_endpoint(settings):
    client = build_embeddings(settings)
    assert client.openai_api_base == "https://api.cohere.ai/compatibility/v1"
    assert client.model == "embed-v5.0-fast"
    assert client.check_embedding_ctx_length is False
    assert client.chunk_size == settings.EMBEDDING_BATCH_SIZE
    assert client.dimensions is None


async def test_prefixes_go_in_front_of_queries_and_documents(make_settings):
    fake = DeterministicEmbeddings()
    settings = make_settings(
        EMBEDDING_QUERY_PREFIX="query: ", EMBEDDING_DOCUMENT_PREFIX="passage: "
    )
    service = EmbeddingService(settings, embeddings=fake)
    await service.aembed_query("hello")
    await service.aembed_documents(["alpha", "beta"])
    assert fake.queries == ["query: hello"]
    assert [text for batch in fake.batches for text in batch] == ["passage: alpha", "passage: beta"]


async def test_without_prefixes_texts_are_sent_unchanged(settings):
    fake = DeterministicEmbeddings()
    service = EmbeddingService(settings, embeddings=fake)
    await service.aembed_query("hello")
    await service.aembed_documents(["alpha"])
    assert fake.queries == ["hello"]
    assert fake.batches == [["alpha"]]


def test_a_custom_endpoint_needs_no_key(make_settings):
    settings = make_settings(
        EMBEDDING_API_KEY=None, EMBEDDING_BASE_URL="http://vllm.internal:8001/v1"
    )
    assert EmbeddingService(settings).configured is True
    assert build_embeddings(settings).openai_api_key.get_secret_value() == PLACEHOLDER_API_KEY


def test_the_default_endpoint_still_needs_a_key_even_with_a_trailing_slash(make_settings):
    settings = make_settings(
        EMBEDDING_API_KEY=None, EMBEDDING_BASE_URL="https://api.cohere.ai/compatibility/v1/"
    )
    assert EmbeddingService(settings).configured is False
    with pytest.raises(ConfigurationError):
        build_embeddings(settings)


def test_dimensions_setting_reaches_the_client(make_settings):
    assert build_embeddings(make_settings(EMBEDDING_DIMENSIONS=512)).dimensions == 512


def test_info_names_the_host_not_the_key(settings):
    info = EmbeddingService(settings, embeddings=DeterministicEmbeddings()).info
    assert info.details["host"] == "api.cohere.ai"
    assert "not-real" not in str(info)


async def test_embedding_service_closes_the_client_it_created(settings):
    service = EmbeddingService(settings)
    client = service._client()
    assert client.http_async_client is not build_embeddings(settings).http_async_client
    await service.aclose()
    assert client.http_async_client.is_closed
    await EmbeddingService(settings, embeddings=DeterministicEmbeddings()).aclose()
