"""Test doubles: scripted chat model, deterministic embeddings and a fake web search."""

import json
import math
import re
import zlib
from collections.abc import Iterator
from contextlib import AsyncExitStack
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field, PrivateAttr

from config.settings import Settings
from src.ai_models.embeddings import EmbeddingService
from src.ai_models.llm import LLMService
from src.ai_models.tracing import Tracing
from src.api.deps import Container
from src.clients.qdrant import QdrantStore
from src.composition import Runtime
from src.graph.tools import build_tools
from src.rag.retriever import Retriever
from src.services.chat_service import ChatService
from src.services.knowledge_service import KnowledgeService
from src.services.livekit_service import LiveKitService
from src.utils.models import SearchHit

EMBEDDING_DIMENSION = 256
STOPWORDS = frozenset(
    {"the", "a", "an", "is", "in", "at", "of", "and", "for", "to", "what", "does", "each"}
)
WORD = re.compile(r"[a-z0-9]+")


def ai(text: str = "", *tool_calls: tuple[str, dict[str, Any]], finish: str = "stop") -> AIMessage:
    """Scripted assistant reply, optionally requesting tool calls."""
    return AIMessage(
        content=text,
        tool_calls=[
            {"name": name, "args": args, "id": f"call_{index}", "type": "tool_call"}
            for index, (name, args) in enumerate(tool_calls)
        ],
        response_metadata={"finish_reason": finish},
    )


class ScriptedChatModel(BaseChatModel):
    """Returns the scripted replies in order; the last one repeats when ``loop`` is set."""

    script: list[AIMessage]
    loop: bool = False
    seen: list[list[BaseMessage]] = Field(default_factory=list)
    _index: int = PrivateAttr(default=0)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChatModel":
        return self

    def _next(self, messages: list[BaseMessage]) -> AIMessage:
        self.seen.append(list(messages))
        if self._index >= len(self.script):
            if not self.loop:
                raise AssertionError("The scripted model ran out of replies")
            return self.script[-1].model_copy(update={"id": None})
        reply = self.script[self._index]
        self._index += 1
        return reply.model_copy(update={"id": None})

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._next(messages))])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        reply = self._next(messages)
        text = reply.content if isinstance(reply.content, str) else ""
        for word in re.findall(r"\S+\s*", text):
            chunk = ChatGenerationChunk(message=AIMessageChunk(content=word))
            if run_manager:
                run_manager.on_llm_new_token(word, chunk=chunk)
            yield chunk
        if reply.tool_calls:
            calls = [
                {"name": c["name"], "args": json.dumps(c["args"]), "id": c["id"], "index": i}
                for i, c in enumerate(reply.tool_calls)
            ]
            yield ChatGenerationChunk(message=AIMessageChunk(content="", tool_call_chunks=calls))
        finish = (reply.response_metadata or {}).get("finish_reason", "stop")
        yield ChatGenerationChunk(
            message=AIMessageChunk(
                content="",
                response_metadata={"finish_reason": finish},
                usage_metadata={"input_tokens": 7, "output_tokens": 3, "total_tokens": 10},
            ),
            generation_info={"finish_reason": finish},
        )


class DeterministicEmbeddings(Embeddings):
    """Bag-of-words hashing: texts sharing words get similar vectors. Records every call."""

    def __init__(self, fail_with: Exception | None = None) -> None:
        self.batches: list[list[str]] = []
        self.queries: list[str] = []
        self._fail_with = fail_with

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * EMBEDDING_DIMENSION
        for word in WORD.findall(text.lower()):
            if word in STOPWORDS:
                continue
            vector[zlib.crc32(word.encode()) % EMBEDDING_DIMENSION] += 1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if self._fail_with:
            raise self._fail_with
        self.batches.append(list(texts))
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        if self._fail_with:
            raise self._fail_with
        self.queries.append(text)
        return self._vector(text)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embed_documents(texts)

    async def aembed_query(self, text: str) -> list[float]:
        return self.embed_query(text)


class FakeWebSearch:
    """Stands in for ``WebSearchClient``."""

    def __init__(self, hits: list[SearchHit] | None = None, error: Exception | None = None) -> None:
        self.hits = hits if hits is not None else []
        self.error = error
        self.queries: list[str] = []

    async def search(self, query: str, *, max_results: int | None = None) -> list[SearchHit]:
        self.queries.append(query)
        if self.error:
            raise self.error
        return self.hits


def build_runtime(
    settings: Settings,
    script: list[AIMessage],
    *,
    hits: list[SearchHit] | None = None,
    loop: bool = False,
    embeddings: DeterministicEmbeddings | None = None,
) -> Runtime:
    """A runtime made of fakes and an in-memory Qdrant."""
    model = ScriptedChatModel(script=script, loop=loop)
    embedding_service = EmbeddingService(
        settings, embeddings=embeddings or DeterministicEmbeddings()
    )
    retriever = Retriever(settings, embedding_service, QdrantStore(settings))
    web_search = FakeWebSearch(hits)
    return Runtime(
        settings=settings,
        tracing=Tracing(settings),
        llm=LLMService(settings, model=model),
        embeddings=embedding_service,
        retriever=retriever,
        web_search=web_search,  # type: ignore[arg-type]
        tools=build_tools(retriever=retriever, web_search=web_search),  # type: ignore[arg-type]
    )


async def build_container(
    settings: Settings, stack: AsyncExitStack, script: list[AIMessage], **kwargs: Any
) -> Container:
    """A container wired like production but running on fakes."""
    runtime = build_runtime(settings, script, **kwargs)
    graph = runtime.build_graph(InMemorySaver())
    return Container(
        settings=settings,
        runtime=runtime,
        chat=ChatService(graph, settings, runtime.tracing),
        knowledge=KnowledgeService(runtime.retriever, settings),
        livekit=LiveKitService(settings),
    )
