"""Text chat use case: run one user turn through the agent graph."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphRecursionError
from langgraph.graph.state import CompiledStateGraph

from config.logger import get_logger
from config.settings import Settings
from src.ai_models.tracing import Tracing
from src.graph.streaming import SSEEvent, last_answer, stream_graph
from src.graph.trace import build_run_config
from src.utils.exceptions import GraphExecutionError, InvalidInputError, OmniVoxError

logger = get_logger(__name__)

TEXT_CHANNEL_TAG = "text"


@dataclass(frozen=True)
class ChatResult:
    """Answer of one chat turn."""

    session_id: str
    answer: str
    tools_used: list[str]


class ChatService:
    """Runs user messages through the graph with per-session memory."""

    def __init__(self, graph: CompiledStateGraph, settings: Settings, tracing: Tracing) -> None:
        self._graph = graph
        self._settings = settings
        self._tracing = tracing
        self._semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_RUNS)

    async def invoke(self, session_id: str, message: str, request_id: str) -> ChatResult:
        """Run the graph to completion and return the final answer."""
        text = self._validate(message)
        config = self._config(session_id, request_id)
        async with self._semaphore:
            try:
                result = await self._graph.ainvoke({"messages": [HumanMessage(text)]}, config)
            except OmniVoxError:
                raise
            except GraphRecursionError as exc:
                raise GraphExecutionError("The agent hit its step limit") from exc
            except Exception as exc:
                raise GraphExecutionError(f"{type(exc).__name__}: {exc}") from exc
        messages = result["messages"]
        answer = last_answer(messages)
        if not answer:
            raise GraphExecutionError("The graph finished without an answer")
        return ChatResult(session_id, answer, self._tools_used(messages))

    def stream(self, session_id: str, message: str, request_id: str) -> AsyncIterator[SSEEvent]:
        """Start a run and return its SSE events (``final`` or ``error`` comes last).

        The message is validated here, before any event is produced, so a bad message fails
        as a normal error response instead of breaking a stream that already sent its headers.
        """
        text = self._validate(message)
        config = self._config(session_id, request_id)
        return self._events(text, config, session_id, request_id)

    async def _events(
        self, text: str, config: RunnableConfig, session_id: str, request_id: str
    ) -> AsyncIterator[SSEEvent]:
        async with self._semaphore:
            async for event in stream_graph(
                self._graph,
                text,
                config,
                session_id=session_id,
                request_id=request_id,
                max_chars=self._settings.INSPECTOR_MAX_FIELD_CHARS,
            ):
                yield event

    def _config(self, session_id: str, request_id: str):
        return build_run_config(
            self._settings,
            self._tracing,
            session_id=session_id,
            request_id=request_id,
            tags=[TEXT_CHANNEL_TAG],
        )

    def _validate(self, message: str) -> str:
        text = message.strip()
        if not text:
            raise InvalidInputError("The message is empty.")
        if len(text) > self._settings.MAX_INPUT_CHARS:
            raise InvalidInputError(
                f"The message is longer than {self._settings.MAX_INPUT_CHARS} characters."
            )
        return text

    @staticmethod
    def _tools_used(messages: list) -> list[str]:
        """Tool names called during the latest turn, in order, without repeats."""
        start = max((i for i, m in enumerate(messages) if isinstance(m, HumanMessage)), default=0)
        names: list[str] = []
        for message in messages[start:]:
            if isinstance(message, AIMessage):
                names.extend(
                    call["name"] for call in message.tool_calls if call["name"] not in names
                )
        return names
