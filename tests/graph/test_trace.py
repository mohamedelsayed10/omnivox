"""Run config and the callback handler that feeds the inspector."""

import asyncio
from uuid import uuid4

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.tracers.langchain import LangChainTracer

from src.ai_models.tracing import Tracing
from src.graph.trace import TraceCallbackHandler, build_run_config
from src.utils.exceptions import LLMError
from src.utils.models import SearchHit
from src.utils.trace_events import TraceEvent
from tests.fakes import ai, build_runtime

HITS = [SearchHit("Paris", "https://example.org/paris", "Paris is the capital of France.")]


def test_run_config_carries_thread_limit_tags_and_metadata(make_settings):
    settings = make_settings(GRAPH_RECURSION_LIMIT=9)
    config = build_run_config(
        settings,
        Tracing(settings),
        session_id="s-1",
        request_id="r-1",
        tags=["voice"],
        metadata={"k": 1},
    )
    assert config["configurable"] == {"thread_id": "s-1"}
    assert config["recursion_limit"] == 9
    assert config["tags"] == ["omnivox", "voice"]
    assert config["metadata"] == {
        "service": "omnivox",
        "session_id": "s-1",
        "request_id": "r-1",
        "k": 1,
    }
    assert config["callbacks"] == []


def test_run_config_adds_tracer_and_handlers_when_tracing_is_on(make_settings):
    settings = make_settings(
        TRACING_PROVIDER="langsmith", LANGSMITH_API_KEY="lsv2_pt_dummy_dummy_dummy_dummy"
    )
    handler = TraceCallbackHandler(lambda event: None)
    config = build_run_config(
        settings, Tracing(settings), session_id="s", request_id="r", handlers=[handler]
    )
    assert isinstance(config["callbacks"][0], LangChainTracer)
    assert config["callbacks"][1] is handler


async def collect(runtime, script_user: str, *, stream: bool = False, turn=lambda: 0):
    events: list[TraceEvent] = []
    handler = TraceCallbackHandler(events.append, turn=turn, max_chars=40)
    config = build_run_config(
        runtime.settings, runtime.tracing, session_id="s", request_id="r", handlers=[handler]
    )
    graph = runtime.build_graph()
    state = {"messages": [HumanMessage(script_user)]}
    if stream:
        async for _ in graph.astream(state, config, stream_mode="messages"):
            pass
    else:
        await graph.ainvoke(state, config)
    return events


def names(events: list[TraceEvent]) -> list[str]:
    return [f"{e.source}.{e.type}" for e in events]


async def test_tool_run_reports_nodes_routes_tools_and_llm_in_order(settings):
    script = [ai("Checking.", ("web_search", {"query": "capital of France"})), ai("Paris.")]
    events = await collect(build_runtime(settings, script, hits=HITS), "capital?", stream=True)
    assert names(events) == [
        "graph.node_start",  # agent
        "llm.start",
        "llm.first_token",
        "llm.end",
        "graph.route",  # the router runs inside the agent node: agent -> tools
        "graph.node_end",
        "graph.node_start",  # tools
        "tool.start",
        "tool.end",
        "graph.node_end",
        "graph.node_start",  # agent
        "llm.start",
        "llm.first_token",
        "llm.end",
        "graph.route",  # agent -> end
        "graph.node_end",
    ]
    assert [e.data["node"] for e in events if e.type == "node_start"] == ["agent", "tools", "agent"]
    routes = [(e.data["from"], e.data["to"]) for e in events if e.type == "route"]
    assert routes == [("agent", "tools"), ("agent", "__end__")]


async def test_tool_events_carry_args_preview_and_duration(settings):
    script = [ai("", ("web_search", {"query": "capital of France"})), ai("Paris.")]
    events = await collect(build_runtime(settings, script, hits=HITS), "capital?")
    start = next(e for e in events if e.source == "tool" and e.type == "start")
    end = next(e for e in events if e.source == "tool" and e.type == "end")
    assert start.data == {"name": "web_search", "args": {"query": "capital of France"}}
    assert end.data["name"] == "web_search"
    assert end.data["result_preview"].startswith("<web_result")
    assert len(end.data["result_preview"]) <= 40  # max_chars from the handler
    assert end.duration_ms is not None and end.duration_ms >= 0


async def test_llm_end_reports_usage_and_finish_reason(settings):
    events = await collect(build_runtime(settings, [ai("Hello there friend.")]), "hi", stream=True)
    end = next(e for e in events if e.source == "llm" and e.type == "end")
    assert end.data["input_tokens"] == 7 and end.data["output_tokens"] == 3
    assert end.data["finish_reason"] == "stop"
    first = next(e for e in events if e.type == "first_token")
    assert first.data["ttft_ms"] >= 0


async def test_events_are_stamped_with_the_current_turn(settings):
    events = await collect(build_runtime(settings, [ai("ok")]), "hi", turn=lambda: 4)
    assert events and {e.turn for e in events} == {4}


async def test_failures_are_reported_as_error_events(settings):
    runtime = build_runtime(settings, [])  # the scripted model raises on the first call
    handler_events: list[TraceEvent] = []
    handler = TraceCallbackHandler(handler_events.append)
    config = build_run_config(
        settings, runtime.tracing, session_id="s", request_id="r", handlers=[handler]
    )
    with pytest.raises(LLMError):
        await runtime.build_graph().ainvoke({"messages": [HumanMessage("hi")]}, config)
    errors = [e for e in handler_events if e.source == "error"]
    assert errors and errors[0].data["source"] in {"llm", "graph"}


async def test_async_sinks_are_awaited(settings):
    seen: list[str] = []

    async def sink(event: TraceEvent) -> None:
        seen.append(event.type)

    handler = TraceCallbackHandler(sink)
    runtime = build_runtime(settings, [ai("ok")])
    config = build_run_config(
        settings, runtime.tracing, session_id="s", request_id="r", handlers=[handler]
    )
    await runtime.build_graph().ainvoke({"messages": [HumanMessage("hi")]}, config)
    assert "node_start" in seen and "node_end" in seen


async def test_cancellations_are_reported_as_cancelled_not_as_errors():
    events: list[TraceEvent] = []
    handler = TraceCallbackHandler(events.append)
    node, llm, tool = uuid4(), uuid4(), uuid4()
    await handler.on_chain_start(
        None, {}, run_id=node, metadata={"langgraph_node": "agent"}, name="agent"
    )
    await handler.on_chat_model_start(None, [[]], run_id=llm)
    await handler.on_tool_start({"name": "web_search"}, "q", run_id=tool, inputs={"query": "q"})
    cancel = asyncio.CancelledError("user spoke again")
    await handler.on_tool_error(cancel, run_id=tool)
    await handler.on_llm_error(cancel, run_id=llm)
    await handler.on_chain_error(cancel, run_id=node)
    assert names(events)[-3:] == ["tool.cancelled", "llm.cancelled", "graph.node_cancelled"]
    assert all(e.source != "error" for e in events)
