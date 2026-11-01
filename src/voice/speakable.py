"""Keeps tool output out of the caller's ears.

LiveKit's LangChain adapter speaks every message the graph streams. LangGraph's ``messages``
stream also carries the finished ``ToolMessage`` of each tool call, so without a filter the raw
search results would be read aloud. ``SpeakableGraph`` forwards only the assistant text written
by the agent node.
"""

from collections.abc import AsyncIterator
from contextlib import aclosing
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk
from langgraph.graph.state import CompiledStateGraph

from src.graph.state import NODE_AGENT


def is_speakable(item: Any) -> bool:
    """True for a ``(message, metadata)`` pair that holds assistant text from the agent node."""
    if not (isinstance(item, tuple) and len(item) == 2):
        return False
    message, metadata = item
    from_agent = isinstance(metadata, dict) and metadata.get("langgraph_node") == NODE_AGENT
    return from_agent and isinstance(message, AIMessage | AIMessageChunk)


class SpeakableGraph:
    """Wraps a compiled graph so ``astream(..., stream_mode="messages")`` yields only speech."""

    def __init__(self, graph: CompiledStateGraph) -> None:
        self._graph = graph

    def astream(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        """Stream the graph, dropping everything the caller should not hear."""
        return self._speakable(self._graph.astream(*args, **kwargs))

    async def _speakable(self, stream: AsyncIterator[Any]) -> AsyncIterator[Any]:
        async with aclosing(stream):
            async for item in stream:
                if is_speakable(item):
                    yield item

    def __getattr__(self, name: str) -> Any:
        return getattr(self._graph, name)
