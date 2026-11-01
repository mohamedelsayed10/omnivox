"""Runs the graph and converts its activity into typed SSE events.

Event order: ``node``/``tool``/``token`` events as they happen, then exactly one ``final`` or
``error``. Cancelling the consumer (client disconnect) cancels the graph run.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphRecursionError
from langgraph.graph.state import CompiledStateGraph

from config.logger import get_logger
from src.ai_models.llm import message_text
from src.graph.state import NODE_AGENT
from src.graph.trace import TraceCallbackHandler
from src.utils.exceptions import GraphExecutionError, OmniVoxError
from src.utils.trace_events import TraceEvent

logger = get_logger(__name__)

SSEEventName = Literal["token", "node", "tool", "final", "error"]
_DONE = object()


@dataclass(frozen=True)
class SSEEvent:
    """One server-sent event."""

    event: SSEEventName
    data: dict[str, Any]

    def encode(self) -> str:
        """Wire format of the frame."""
        return f"event: {self.event}\ndata: {json.dumps(self.data, ensure_ascii=False)}\n\n"


def last_answer(messages: list[Any]) -> str:
    """Text of the last assistant message that is not a tool request."""
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not message.tool_calls:
            return message_text(message).strip()
    return ""


def _from_trace(event: TraceEvent) -> SSEEvent | None:
    data = event.data
    if event.source == "graph" and event.type in ("node_start", "node_end"):
        payload: dict[str, Any] = {
            "name": data["node"],
            "phase": "start" if event.type == "node_start" else "end",
        }
        if event.duration_ms is not None:
            payload["duration_ms"] = round(event.duration_ms, 1)
        return SSEEvent("node", payload)
    if event.source == "tool":
        phase = {"start": "start", "end": "end", "error": "error"}[event.type]
        payload = {"name": data["name"], "phase": phase}
        if "args" in data:
            payload["args"] = data["args"]
        if "result_preview" in data:
            payload["result_preview"] = data["result_preview"]
        if event.duration_ms is not None:
            payload["duration_ms"] = round(event.duration_ms, 1)
        return SSEEvent("tool", payload)
    return None


def error_event(exc: BaseException, request_id: str) -> SSEEvent:
    """Safe ``error`` frame: domain errors expose their public message, others stay generic."""
    if isinstance(exc, GraphRecursionError):
        exc = GraphExecutionError("Step limit reached")
    if not isinstance(exc, OmniVoxError):
        logger.error("Unhandled %s in stream: %s", type(exc).__name__, exc, exc_info=exc)
        exc = OmniVoxError()
    else:
        logger.error("%s in stream: %s", type(exc).__name__, exc)
    return SSEEvent(
        "error", {"code": exc.code, "message": exc.public_message, "request_id": request_id}
    )


async def stream_graph(
    graph: CompiledStateGraph,
    text: str,
    config: RunnableConfig,
    *,
    session_id: str,
    request_id: str,
    max_chars: int,
) -> AsyncIterator[SSEEvent]:
    """Run one user turn and yield SSE events, always ending with ``final`` or ``error``."""
    queue: asyncio.Queue[Any] = asyncio.Queue()

    def on_trace(event: TraceEvent) -> None:
        if (frame := _from_trace(event)) is not None:
            queue.put_nowait(frame)

    handler = TraceCallbackHandler(on_trace, max_chars=max_chars)
    run_config: RunnableConfig = {
        **config,
        "callbacks": [*(config.get("callbacks") or []), handler],
    }

    async def run() -> None:
        state: dict[str, Any] = {}
        try:
            async for mode, payload in graph.astream(
                {"messages": [HumanMessage(text)]}, run_config, stream_mode=["messages", "values"]
            ):
                if mode == "values":
                    state = payload
                    continue
                chunk, meta = payload
                is_agent_text = isinstance(chunk, AIMessageChunk) and (
                    meta.get("langgraph_node") == NODE_AGENT
                )
                if is_agent_text and (token := message_text(chunk)):
                    queue.put_nowait(SSEEvent("token", {"text": token}))
            answer = last_answer(state.get("messages", []))
            if not answer:
                raise GraphExecutionError("The graph finished without an answer")
            queue.put_nowait(SSEEvent("final", {"answer": answer, "session_id": session_id}))
        except Exception as exc:
            queue.put_nowait(error_event(exc, request_id))
        finally:
            queue.put_nowait(_DONE)

    task = asyncio.create_task(run())
    try:
        while (item := await queue.get()) is not _DONE:
            yield item
    finally:
        task.cancel()
