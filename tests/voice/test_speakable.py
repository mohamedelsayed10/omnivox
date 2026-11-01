"""The caller must hear the assistant's words, never raw tool output."""

import pytest
from langchain_core.messages import AIMessageChunk, HumanMessage, ToolMessage
from livekit.agents import llm
from livekit.plugins import langchain

from src.graph.trace import build_run_config
from src.utils.exceptions import LLMError
from src.utils.models import SearchHit
from src.voice.speakable import SpeakableGraph, is_speakable
from tests.fakes import ai, build_runtime

HITS = [SearchHit("Paris", "https://example.org/paris", "SECRET-RESULT-TEXT about Paris.")]


def test_only_agent_assistant_text_is_speakable():
    agent = {"langgraph_node": "agent"}
    assert is_speakable((AIMessageChunk(content="Hello"), agent))
    assert not is_speakable((AIMessageChunk(content="Hello"), {"langgraph_node": "tools"}))
    assert not is_speakable((ToolMessage("results", tool_call_id="c"), {"langgraph_node": "tools"}))
    assert not is_speakable((ToolMessage("results", tool_call_id="c"), agent))
    assert not is_speakable((HumanMessage("hi"), agent))
    assert not is_speakable("Hello")
    assert not is_speakable((AIMessageChunk(content="x"), None))


async def spoken_text(runtime, wrap: bool) -> str:
    graph = runtime.build_graph()
    config = build_run_config(runtime.settings, runtime.tracing, session_id="s", request_id="r")
    adapter = langchain.LLMAdapter(SpeakableGraph(graph) if wrap else graph, config=config)
    context = llm.ChatContext()
    context.add_message(role="user", content="What is the capital of France?")
    spoken = []
    async with adapter.chat(chat_ctx=context) as stream:
        async for chunk in stream:
            if chunk.delta and chunk.delta.content:
                spoken.append(chunk.delta.content)
    return "".join(spoken)


async def test_the_adapter_speaks_the_answer_and_not_the_search_results(settings):
    script = [
        ai("Let me check. ", ("web_search", {"query": "capital of France"})),
        ai("It is Paris."),
    ]
    text = await spoken_text(build_runtime(settings, script, hits=HITS), wrap=True)
    assert text.replace(" ", "") == "Letmecheck.ItisParis."
    assert "SECRET-RESULT-TEXT" not in text and "web_result" not in text


async def test_without_the_filter_the_adapter_would_read_tool_output_aloud(settings):
    """Documents the upstream behavior that SpeakableGraph exists to prevent."""
    script = [
        ai("Let me check. ", ("web_search", {"query": "capital of France"})),
        ai("It is Paris."),
    ]
    text = await spoken_text(build_runtime(settings, script, hits=HITS), wrap=False)
    assert "SECRET-RESULT-TEXT" in text


async def test_a_graph_failure_still_reaches_the_caller_of_the_adapter(settings):
    runtime = build_runtime(settings, [])  # the scripted model fails on the first call
    with pytest.raises(LLMError):
        await spoken_text(runtime, wrap=True)


def test_other_attributes_pass_through_to_the_graph(settings):
    graph = build_runtime(settings, [ai("x")]).build_graph()
    assert SpeakableGraph(graph).name == graph.name
