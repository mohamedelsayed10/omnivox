"""Graph streaming: SSE event order, terminal events and cancellation."""

import asyncio
import json
from contextlib import aclosing

from langchain_core.messages import AIMessage, HumanMessage

from src.graph.streaming import SSEEvent, error_event, last_answer, stream_graph
from src.graph.trace import build_run_config
from src.utils.exceptions import GraphExecutionError, LLMError
from src.utils.models import SearchHit
from tests.fakes import ai, build_runtime

HITS = [SearchHit("Paris", "https://example.org/paris", "Paris is the capital of France.")]


async def run(runtime, text: str = "capital?") -> list[SSEEvent]:
    config = build_run_config(runtime.settings, runtime.tracing, session_id="s-1", request_id="r-1")
    graph = runtime.build_graph()
    return [
        event
        async for event in stream_graph(
            graph, text, config, session_id="s-1", request_id="r-1", max_chars=200
        )
    ]


async def test_tool_turn_streams_nodes_tools_tokens_then_final(settings):
    script = [ai("Let me check.", ("web_search", {"query": "capital"})), ai("It is Paris.")]
    events = await run(build_runtime(settings, script, hits=HITS))
    kinds = [e.event for e in events]
    assert kinds[-1] == "final" and kinds.count("final") == 1 and "error" not in kinds
    assert kinds[0] == "node" and events[0].data == {"name": "agent", "phase": "start"}
    spoken = "".join(e.data["text"] for e in events if e.event == "token")
    assert spoken.startswith("Let me check.") and spoken.endswith("It is Paris.")

    tool_frames = [e.data for e in events if e.event == "tool"]
    assert [f["phase"] for f in tool_frames] == ["start", "end"]
    assert tool_frames[0]["args"] == {"query": "capital"}
    assert tool_frames[1]["result_preview"].startswith("<web_result")

    node_frames = [(e.data["name"], e.data["phase"]) for e in events if e.event == "node"]
    assert node_frames == [
        ("agent", "start"),
        ("agent", "end"),
        ("tools", "start"),
        ("tools", "end"),
        ("agent", "start"),
        ("agent", "end"),
    ]
    first_tool = kinds.index("tool")
    assert kinds.index("token") < first_tool  # the preamble is spoken before the tool runs
    assert events[-1].data == {"answer": "It is Paris.", "session_id": "s-1"}


async def test_plain_answer_has_no_tool_frames(settings):
    events = await run(build_runtime(settings, [ai("Hello friend.")]))
    assert [e.event for e in events if e.event != "token"] == ["node", "node", "final"]


async def test_llm_failure_ends_with_one_safe_error_event(settings):
    events = await run(build_runtime(settings, []))  # model raises AssertionError -> LLMError
    assert events[-1].event == "error"
    assert [e.event for e in events].count("error") == 1
    assert events[-1].data["code"] == "llm_error"
    assert events[-1].data["request_id"] == "r-1"
    assert "scripted model" not in json.dumps(events[-1].data)


async def test_step_limit_ends_with_a_graph_error(make_settings):
    runtime = build_runtime(
        make_settings(GRAPH_RECURSION_LIMIT=4), [ai("", ("web_search", {"query": "x"}))], loop=True
    )
    events = await run(runtime)
    assert events[-1].event == "error" and events[-1].data["code"] == "graph_error"


async def test_closing_the_consumer_cancels_the_run(settings):
    runtime = build_runtime(settings, [ai("one two three four five six seven eight")])
    config = build_run_config(settings, runtime.tracing, session_id="s", request_id="r")
    before = set(asyncio.all_tasks())
    stream = stream_graph(
        runtime.build_graph(), "hi", config, session_id="s", request_id="r", max_chars=100
    )
    async with aclosing(stream):
        first = await anext(stream)
        assert first.event == "node"
    await asyncio.sleep(0.1)  # let the cancellation propagate
    leftover = [t for t in asyncio.all_tasks() - before if not t.done()]
    assert leftover == []


def test_sse_frame_encoding():
    frame = SSEEvent("token", {"text": "héllo"}).encode()
    assert frame == 'event: token\ndata: {"text": "héllo"}\n\n'


def test_error_event_hides_internal_detail():
    event = error_event(LLMError("provider said: key AIza123 invalid"), "r-9")
    assert event.data == {
        "code": "llm_error",
        "message": "The language model request failed.",
        "request_id": "r-9",
    }
    unknown = error_event(RuntimeError("secret internals"), "r-9")
    assert unknown.data["code"] == "internal_error" and "secret" not in json.dumps(unknown.data)
    assert error_event(GraphExecutionError("x"), "r").data["code"] == "graph_error"


def test_last_answer_skips_tool_requests():
    messages = [
        HumanMessage("q"),
        AIMessage("final text"),
        ai("", ("t", {})),
    ]
    assert last_answer(messages) == "final text"
    assert last_answer([HumanMessage("q")]) == ""
