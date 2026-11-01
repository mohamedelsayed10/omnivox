"""Run configuration and the callback handler that turns LangChain events into inspector events."""

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler, BaseCallbackHandler
from langchain_core.messages import BaseMessage, ToolMessage
from langchain_core.outputs import LLMResult
from langchain_core.runnables import RunnableConfig

from config.logger import get_logger
from config.settings import Settings
from src.ai_models.tracing import Tracing
from src.graph.state import NODE_AGENT, ROUTER_AFTER_AGENT
from src.utils.text import truncate
from src.utils.trace_events import TraceEvent

logger = get_logger(__name__)

TraceSink = Callable[[TraceEvent], Awaitable[None] | None]
DEFAULT_MODEL_LABEL = "model"
CANCELLATIONS = (asyncio.CancelledError, GeneratorExit)
RUN_NAME = "omnivox_turn"


def build_run_config(
    settings: Settings,
    tracing: Tracing,
    *,
    session_id: str,
    request_id: str,
    handlers: Sequence[BaseCallbackHandler] = (),
    tags: Sequence[str] = (),
    metadata: dict[str, Any] | None = None,
) -> RunnableConfig:
    """Config for one graph run: thread, step limit, tags, metadata and tracing callbacks."""
    run_metadata = {
        "service": settings.APP_NAME,
        "session_id": session_id,
        "request_id": request_id,
        **(metadata or {}),
    }
    return RunnableConfig(
        run_name=RUN_NAME,
        configurable={"thread_id": session_id},
        recursion_limit=settings.GRAPH_RECURSION_LIMIT,
        tags=[settings.APP_NAME, *tags],
        metadata=run_metadata,
        callbacks=[*tracing.get_callbacks(run_metadata), *handlers],
    )


@dataclass
class _LlmRun:
    started: float
    first_token_sent: bool = False


@dataclass
class _Timer:
    name: str
    started: float = field(default_factory=time.perf_counter)

    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self.started) * 1000


class TraceCallbackHandler(AsyncCallbackHandler):
    """Reports graph nodes, routing, tool calls and model calls to a sink as ``TraceEvent``s."""

    run_inline = True

    def __init__(
        self, sink: TraceSink, *, turn: Callable[[], int] = lambda: 0, max_chars: int = 1500
    ) -> None:
        self._sink = sink
        self._turn = turn
        self._max_chars = max_chars
        self._nodes: dict[UUID, _Timer] = {}
        self._routers: dict[UUID, _Timer] = {}
        self._tools: dict[UUID, _Timer] = {}
        self._llms: dict[UUID, _LlmRun] = {}

    async def _emit(self, event: TraceEvent) -> None:
        event.turn = self._turn()
        result = self._sink(event)
        if inspect.isawaitable(result):
            await result

    def _clip(self, value: Any) -> str:
        return truncate(str(value), self._max_chars)

    # --- graph nodes and routing ---

    async def on_chain_start(
        self,
        serialized: dict[str, Any] | None,
        inputs: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        name = kwargs.get("name")
        node = (metadata or {}).get("langgraph_node")
        if node and name == node:
            self._nodes[run_id] = _Timer(node)
            await self._emit(
                TraceEvent("graph", "node_start", f"Node {node} started", {"node": node})
            )
        elif name == ROUTER_AFTER_AGENT:
            self._routers[run_id] = _Timer(name)

    async def on_chain_end(
        self, outputs: Any, *, run_id: UUID, parent_run_id: UUID | None = None, **kwargs: Any
    ) -> None:
        if timer := self._nodes.pop(run_id, None):
            await self._emit(
                TraceEvent(
                    "graph",
                    "node_end",
                    f"Node {timer.name} finished",
                    {"node": timer.name},
                    duration_ms=timer.elapsed_ms(),
                )
            )
        elif (router := self._routers.pop(run_id, None)) is not None:
            target = outputs if isinstance(outputs, str) else str(outputs)
            await self._emit(
                TraceEvent(
                    "graph",
                    "route",
                    f"Route {NODE_AGENT} -> {target}",
                    {"from": NODE_AGENT, "to": target},
                    duration_ms=router.elapsed_ms(),
                )
            )

    async def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        timer = self._nodes.pop(run_id, None)
        self._routers.pop(run_id, None)
        if timer is not None and isinstance(error, CANCELLATIONS):
            await self._emit(
                TraceEvent(
                    "graph",
                    "node_cancelled",
                    f"Node {timer.name} cancelled",
                    {"node": timer.name},
                    duration_ms=timer.elapsed_ms(),
                )
            )
        elif timer is not None:
            await self._emit(
                TraceEvent(
                    "error",
                    "error",
                    f"Node {timer.name} failed",
                    {"message": self._clip(f"{type(error).__name__}: {error}"), "source": "graph"},
                    duration_ms=timer.elapsed_ms(),
                )
            )

    # --- model calls ---

    async def on_chat_model_start(
        self,
        serialized: dict[str, Any] | None,
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self._llms[run_id] = _LlmRun(started=time.perf_counter())
        model = (metadata or {}).get("ls_model_name") or DEFAULT_MODEL_LABEL
        count = len(messages[0]) if messages else 0
        await self._emit(
            TraceEvent("llm", "start", f"LLM call ({model})", {"model": model, "messages": count})
        )

    async def on_llm_new_token(
        self, token: str, *, chunk: Any = None, run_id: UUID, **kwargs: Any
    ) -> None:
        run = self._llms.get(run_id)
        if run is None or run.first_token_sent or not token:
            return
        run.first_token_sent = True
        ttft = (time.perf_counter() - run.started) * 1000
        await self._emit(
            TraceEvent(
                "llm", "first_token", "First token", {"ttft_ms": round(ttft, 1)}, duration_ms=ttft
            )
        )

    async def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        run = self._llms.pop(run_id, None)
        generation = (
            response.generations[0][0] if response.generations and response.generations[0] else None
        )
        message = getattr(generation, "message", None)
        usage = getattr(message, "usage_metadata", None) or {}
        finish = ((generation.generation_info or {}) if generation else {}).get("finish_reason")
        tool_calls = len(getattr(message, "tool_calls", None) or [])
        await self._emit(
            TraceEvent(
                "llm",
                "end",
                "LLM finished",
                {
                    "input_tokens": usage.get("input_tokens"),
                    "output_tokens": usage.get("output_tokens"),
                    "finish_reason": finish,
                    "tool_calls": tool_calls,
                },
                duration_ms=(time.perf_counter() - run.started) * 1000 if run else None,
            )
        )

    async def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self._llms.pop(run_id, None)
        if isinstance(error, CANCELLATIONS):
            await self._emit(TraceEvent("llm", "cancelled", "LLM call cancelled", {}))
            return
        await self._emit(
            TraceEvent(
                "error",
                "error",
                "LLM call failed",
                {"message": self._clip(f"{type(error).__name__}: {error}"), "source": "llm"},
            )
        )

    # --- tools ---

    async def on_tool_start(
        self,
        serialized: dict[str, Any] | None,
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        inputs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        name = (serialized or {}).get("name") or kwargs.get("name") or "tool"
        self._tools[run_id] = _Timer(name)
        args = {key: self._clip(value) for key, value in (inputs or {"input": input_str}).items()}
        await self._emit(
            TraceEvent("tool", "start", f"Tool {name} called", {"name": name, "args": args})
        )

    async def on_tool_end(
        self, output: Any, *, run_id: UUID, parent_run_id: UUID | None = None, **kwargs: Any
    ) -> None:
        timer = self._tools.pop(run_id, None) or _Timer("tool")
        text = output.content if isinstance(output, ToolMessage) else output
        await self._emit(
            TraceEvent(
                "tool",
                "end",
                f"Tool {timer.name} returned",
                {"name": timer.name, "result_preview": self._clip(text)},
                duration_ms=timer.elapsed_ms(),
            )
        )

    async def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        timer = self._tools.pop(run_id, None) or _Timer("tool")
        if isinstance(error, CANCELLATIONS):
            await self._emit(
                TraceEvent(
                    "tool",
                    "cancelled",
                    f"Tool {timer.name} cancelled",
                    {"name": timer.name},
                    duration_ms=timer.elapsed_ms(),
                )
            )
            return
        await self._emit(
            TraceEvent(
                "tool",
                "error",
                f"Tool {timer.name} failed",
                {"name": timer.name, "message": self._clip(f"{type(error).__name__}: {error}")},
                duration_ms=timer.elapsed_ms(),
            )
        )
