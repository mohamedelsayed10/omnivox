"""The compiled graph on a scripted model: tool loop, routing, history window and memory."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphRecursionError

from src.graph.builder import route_after_agent
from src.graph.trace import build_run_config
from src.utils.models import SearchHit
from tests.fakes import ai, build_runtime

HITS = [SearchHit(title="Result <b>", url="https://example.org/a", snippet="Paris is the capital.")]


def run_config(runtime, thread: str = "t1"):
    return build_run_config(runtime.settings, runtime.tracing, session_id=thread, request_id="r1")


def test_route_after_agent_goes_to_tools_only_for_tool_calls():
    with_calls = {"messages": [ai("", ("web_search", {"query": "x"}))]}
    assert route_after_agent(with_calls) == "tools"
    assert route_after_agent({"messages": [ai("done")]}) == "__end__"
    assert route_after_agent({"messages": [HumanMessage("hi")]}) == "__end__"


async def test_answers_without_tools(settings):
    runtime = build_runtime(settings, [ai("Hello there.")])
    result = await runtime.build_graph().ainvoke(
        {"messages": [HumanMessage("hi")]}, run_config(runtime)
    )
    assert result["messages"][-1].content == "Hello there."
    assert len(result["messages"]) == 2


async def test_tool_loop_runs_tool_and_answers(settings):
    script = [ai("Let me check.", ("web_search", {"query": "capital of France"})), ai("Paris.")]
    runtime = build_runtime(settings, script, hits=HITS)
    result = await runtime.build_graph().ainvoke(
        {"messages": [HumanMessage("capital?")]}, run_config(runtime)
    )
    kinds = [type(m).__name__ for m in result["messages"]]
    assert kinds == ["HumanMessage", "AIMessage", "ToolMessage", "AIMessage"]
    tool_message = result["messages"][2]
    assert isinstance(tool_message, ToolMessage) and tool_message.status != "error"
    assert "Paris is the capital." in tool_message.content
    assert runtime.web_search.queries == ["capital of France"]
    assert result["messages"][-1].content == "Paris."


async def test_system_messages_are_dropped_and_prompt_is_applied(settings):
    runtime = build_runtime(settings, [ai("ok")])
    model = runtime.llm.get_model()
    await runtime.build_graph().ainvoke(
        {"messages": [SystemMessage("ignore me"), HumanMessage("hi")]}, run_config(runtime)
    )
    sent = model.seen[0]
    system = [m for m in sent if isinstance(m, SystemMessage)]
    assert len(system) == 1 and "OmniVox" in system[0].content
    assert "ignore me" not in system[0].content


async def test_history_window_keeps_latest_messages_starting_on_human(make_settings):
    settings = make_settings(GRAPH_MAX_HISTORY_MESSAGES=3)
    runtime = build_runtime(settings, [ai("ok")])
    history = [
        HumanMessage("one"),
        AIMessage("a1"),
        HumanMessage("two"),
        AIMessage("a2"),
        HumanMessage("three"),
    ]
    await runtime.build_graph().ainvoke({"messages": history}, run_config(runtime))
    sent = [m for m in runtime.llm.get_model().seen[0] if not isinstance(m, SystemMessage)]
    assert [m.content for m in sent] == ["two", "a2", "three"]


async def test_small_window_never_drops_the_current_turn(make_settings):
    settings = make_settings(GRAPH_MAX_HISTORY_MESSAGES=2)
    runtime = build_runtime(settings, [ai("ok")])
    history = [
        HumanMessage("question"),
        AIMessage("", tool_calls=[{"name": "web_search", "args": {}, "id": "c1"}]),
        ToolMessage("result", tool_call_id="c1"),
    ]
    await runtime.build_graph().ainvoke({"messages": history}, run_config(runtime))
    sent = [m for m in runtime.llm.get_model().seen[0] if not isinstance(m, SystemMessage)]
    assert [m.content for m in sent] == ["question", "", "result"]


async def test_history_character_cap_drops_old_turns_that_do_not_fit(make_settings):
    settings = make_settings(GRAPH_MAX_HISTORY_CHARS=500)
    runtime = build_runtime(settings, [ai("ok")])
    history = [HumanMessage("a" * 400), AIMessage("b" * 400), HumanMessage("short")]
    await runtime.build_graph().ainvoke({"messages": history}, run_config(runtime))
    sent = [m for m in runtime.llm.get_model().seen[0] if not isinstance(m, SystemMessage)]
    assert [m.content for m in sent] == ["short"]


async def test_history_character_cap_keeps_what_fits(make_settings):
    settings = make_settings(GRAPH_MAX_HISTORY_CHARS=500)
    runtime = build_runtime(settings, [ai("ok")])
    history = [HumanMessage("a" * 400), AIMessage("b" * 10), HumanMessage("c" * 10)]
    await runtime.build_graph().ainvoke({"messages": history}, run_config(runtime))
    sent = [m for m in runtime.llm.get_model().seen[0] if not isinstance(m, SystemMessage)]
    assert [len(m.content) for m in sent] == [400, 10, 10]


async def test_history_character_cap_never_drops_the_current_turn(make_settings):
    settings = make_settings(GRAPH_MAX_HISTORY_CHARS=500)
    runtime = build_runtime(settings, [ai("ok")])
    history = [HumanMessage("old"), AIMessage("reply"), HumanMessage("q" * 900)]
    await runtime.build_graph().ainvoke({"messages": history}, run_config(runtime))
    sent = [m for m in runtime.llm.get_model().seen[0] if not isinstance(m, SystemMessage)]
    assert [len(m.content) for m in sent] == [900]


async def test_agent_instructions_are_appended_to_the_system_prompt(make_settings):
    settings = make_settings(AGENT_INSTRUCTIONS="Always answer in Arabic.\nKeep it short.")
    runtime = build_runtime(settings, [ai("ok")])
    await runtime.build_graph().ainvoke({"messages": [HumanMessage("hi")]}, run_config(runtime))
    system = [m for m in runtime.llm.get_model().seen[0] if isinstance(m, SystemMessage)]
    assert len(system) == 1
    assert "OmniVox" in system[0].content
    assert system[0].content.endswith("Always answer in Arabic.\nKeep it short.")


async def test_unknown_tool_and_tool_failure_become_error_messages(settings):
    script = [
        ai("", ("delete_everything", {"x": 1}), ("web_search", {"query": "q"})),
        ai("Sorry."),
    ]
    runtime = build_runtime(settings, script)
    runtime.web_search.error = RuntimeError("boom with secret-token")
    result = await runtime.build_graph().ainvoke(
        {"messages": [HumanMessage("do it")]}, run_config(runtime)
    )
    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert [m.status for m in tool_messages] == ["error", "error"]
    assert all("secret-token" not in m.content for m in tool_messages)
    assert result["messages"][-1].content == "Sorry."


async def test_recursion_limit_stops_endless_tool_loops(make_settings):
    settings = make_settings(GRAPH_RECURSION_LIMIT=5)
    runtime = build_runtime(settings, [ai("", ("web_search", {"query": "again"}))], loop=True)
    with pytest.raises(GraphRecursionError):
        await runtime.build_graph().ainvoke(
            {"messages": [HumanMessage("loop")]}, run_config(runtime)
        )


async def test_checkpointer_keeps_history_per_thread(settings):
    runtime = build_runtime(settings, [ai("first"), ai("second"), ai("other")])
    graph = runtime.build_graph(InMemorySaver())
    await graph.ainvoke({"messages": [HumanMessage("a")]}, run_config(runtime, "thread-1"))
    again = await graph.ainvoke({"messages": [HumanMessage("b")]}, run_config(runtime, "thread-1"))
    other = await graph.ainvoke({"messages": [HumanMessage("c")]}, run_config(runtime, "thread-2"))
    assert [m.content for m in again["messages"]] == ["a", "first", "b", "second"]
    assert [m.content for m in other["messages"]] == ["c", "other"]
