"""Shared wiring for both composition roots (the API app and the voice worker).

Builds the model clients, retriever and tool list once; each root adds what is specific to it.
"""

from dataclasses import dataclass

from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph

from config.settings import Settings
from src.ai_models.embeddings import EmbeddingService
from src.ai_models.llm import LLMService
from src.ai_models.tracing import Tracing
from src.clients.qdrant import QdrantStore
from src.clients.web_search import WebSearchClient
from src.graph.builder import build_graph
from src.graph.tools import build_tools
from src.rag.retriever import Retriever


@dataclass
class Runtime:
    """Long-lived objects shared by every request or voice session of a process."""

    settings: Settings
    tracing: Tracing
    llm: LLMService
    embeddings: EmbeddingService
    retriever: Retriever
    web_search: WebSearchClient
    tools: list[BaseTool]

    def build_graph(self, checkpointer: BaseCheckpointSaver | None = None) -> CompiledStateGraph:
        """Compile the agent graph; without a checkpointer it keeps no state between runs."""
        return build_graph(
            llm=self.llm, tools=self.tools, settings=self.settings, checkpointer=checkpointer
        )

    async def aclose(self) -> None:
        """Release connections and flush traces."""
        await self.retriever.close()
        await self.embeddings.aclose()
        await self.llm.aclose()
        self.tracing.flush()


def build_runtime(settings: Settings) -> Runtime:
    """Create the shared objects from settings. Makes no network calls."""
    tracing = Tracing(settings)
    llm = LLMService(settings)
    embeddings = EmbeddingService(settings)
    retriever = Retriever(settings, embeddings, QdrantStore(settings))
    web_search = WebSearchClient(settings)
    tools = build_tools(retriever=retriever, web_search=web_search)
    return Runtime(
        settings=settings,
        tracing=tracing,
        llm=llm,
        embeddings=embeddings,
        retriever=retriever,
        web_search=web_search,
        tools=tools,
    )
