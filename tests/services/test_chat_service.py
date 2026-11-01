"""Chat service: invoke, stream, validation and error mapping."""

import pytest

from src.graph.streaming import SSEEvent
from src.services.chat_service import ChatService
from src.utils.exceptions import GraphExecutionError, InvalidInputError, LLMError
from src.utils.models import SearchHit
from tests.fakes import ai, build_runtime

HITS = [SearchHit("Paris", "https://example.org/paris", "Paris is the capital of France.")]


def make_service(settings, script, **kwargs) -> tuple[ChatService, object]:
    from langgraph.checkpoint.memory import InMemorySaver

    runtime = build_runtime(settings, script, **kwargs)
    return ChatService(runtime.build_graph(InMemorySaver()), settings, runtime.tracing), runtime


async def test_invoke_returns_answer_and_tools_used(settings):
    script = [
        ai("Checking.", ("web_search", {"query": "capital"}), ("web_search", {"query": "other"})),
        ai("It is Paris."),
    ]
    service, _ = make_service(settings, script, hits=HITS)
    result = await service.invoke("s-1", "  What is the capital of France?  ", "req-1")
    assert result.session_id == "s-1"
    assert result.answer == "It is Paris."
    assert result.tools_used == ["web_search"]


async def test_tools_used_only_lists_the_latest_turn(settings):
    script = [ai("", ("web_search", {"query": "a"})), ai("First."), ai("Second, no tools.")]
    service, _ = make_service(settings, script, hits=HITS)
    assert (await service.invoke("s", "one", "r")).tools_used == ["web_search"]
    assert (await service.invoke("s", "two", "r")).tools_used == []


async def test_sessions_are_isolated_and_remembered(settings):
    service, runtime = make_service(settings, [ai("a1"), ai("a2"), ai("b1")])
    await service.invoke("alice", "hello", "r")
    await service.invoke("alice", "again", "r")
    await service.invoke("bob", "hi", "r")
    model = runtime.llm.get_model()
    from langchain_core.messages import HumanMessage

    humans = [[m.content for m in call if isinstance(m, HumanMessage)] for call in model.seen]
    assert humans == [["hello"], ["hello", "again"], ["hi"]]


@pytest.mark.parametrize("message", ["", "   \n\t "])
async def test_blank_messages_are_rejected(settings, message):
    service, _ = make_service(settings, [ai("never")])
    with pytest.raises(InvalidInputError):
        await service.invoke("s", message, "r")


async def test_oversized_messages_are_rejected_before_any_model_call(make_settings):
    settings = make_settings(MAX_INPUT_CHARS=20)
    service, runtime = make_service(settings, [ai("never")])
    with pytest.raises(InvalidInputError, match="20"):
        await service.invoke("s", "x" * 21, "r")
    assert runtime.llm.get_model().seen == []


async def test_llm_errors_propagate_unchanged(settings):
    service, _ = make_service(settings, [])  # the scripted model fails on the first call
    with pytest.raises(LLMError):
        await service.invoke("s", "hi", "r")


async def test_step_limit_becomes_a_graph_error(make_settings):
    settings = make_settings(GRAPH_RECURSION_LIMIT=4)
    service, _ = make_service(settings, [ai("", ("web_search", {"query": "x"}))], loop=True)
    with pytest.raises(GraphExecutionError, match="step limit"):
        await service.invoke("s", "loop", "r")


async def test_stream_yields_events_ending_with_final(settings):
    service, _ = make_service(settings, [ai("Hello there.")])
    events = [event async for event in service.stream("s", "hi", "r")]
    assert all(isinstance(event, SSEEvent) for event in events)
    assert events[-1].event == "final" and events[-1].data["answer"] == "Hello there."


async def test_stream_validates_before_producing_any_event(settings):
    service, _ = make_service(settings, [ai("never")])
    with pytest.raises(InvalidInputError):
        service.stream("s", " ", "r")  # raises at the call, not on first iteration
