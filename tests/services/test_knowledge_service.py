"""Knowledge service: upload validation, source naming and lifecycle."""

import pytest

from src.services.knowledge_service import KnowledgeService
from src.utils.exceptions import InvalidInputError, NotFoundError
from tests.fakes import build_runtime
from tests.rag.test_loaders import make_pdf

PRICING = b"Our pricing plan costs ten dollars per month for each seat."


def make_service(settings) -> KnowledgeService:
    runtime = build_runtime(settings, [])
    return KnowledgeService(runtime.retriever, settings)


async def test_text_upload_round_trip(settings):
    service = make_service(settings)
    result = await service.ingest("pricing.md", PRICING)
    assert (result.source, result.chunks) == ("pricing.md", 1)
    assert [(d.source, d.chunks) for d in await service.list_documents()] == [("pricing.md", 1)]
    passages = await service.search("pricing plan cost")
    assert passages and passages[0].source == "pricing.md"
    assert await service.delete("pricing.md") == 1
    assert await service.list_documents() == []


async def test_pdf_upload(settings):
    result = await make_service(settings).ingest("report.pdf", make_pdf("Quarterly revenue grew"))
    assert result.chunks == 1


async def test_explicit_source_name_wins_and_paths_are_stripped(settings):
    service = make_service(settings)
    result = await service.ingest("upload.txt", PRICING, "../../etc/Pricing Notes.txt")
    assert result.source == "Pricing Notes.txt"
    windows = await service.ingest("upload.txt", PRICING, "C:\\docs\\notes\x00.txt")
    assert windows.source == "notes.txt"


async def test_source_name_is_bounded(settings):
    result = await make_service(settings).ingest("a.txt", PRICING, "n" * 500)
    assert len(result.source) == 200


async def test_oversized_upload_is_rejected(make_settings):
    service = make_service(make_settings(RAG_MAX_UPLOAD_BYTES=10))
    with pytest.raises(InvalidInputError, match="larger"):
        await service.ingest("a.txt", b"x" * 11)


@pytest.mark.parametrize("filename", ["", "..", "/"])
async def test_documents_need_a_name(settings, filename):
    with pytest.raises(InvalidInputError):
        await make_service(settings).ingest(filename, PRICING)


async def test_unsupported_type_is_a_client_error(settings):
    with pytest.raises(InvalidInputError, match="Unsupported"):
        await make_service(settings).ingest("image.png", b"data")


async def test_deleting_a_missing_document_is_not_found(settings):
    with pytest.raises(NotFoundError, match=r"missing\.md"):
        await make_service(settings).delete("missing.md")
