"""Checkpointer factory."""

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from src.graph.memory import open_checkpointer
from src.graph.trace import build_run_config
from tests.fakes import ai, build_runtime


async def test_memory_backend_is_the_default(settings):
    async with open_checkpointer(settings) as saver:
        assert isinstance(saver, InMemorySaver)


async def test_sqlite_backend_keeps_threads_across_reopen(make_settings, tmp_path):
    settings = make_settings(
        GRAPH_MEMORY_BACKEND="sqlite", GRAPH_MEMORY_URL=str(tmp_path / "nested" / "memory.sqlite")
    )
    runtime = build_runtime(settings, [ai("first answer"), ai("second answer")])
    config = build_run_config(settings, runtime.tracing, session_id="persisted", request_id="r")

    async with open_checkpointer(settings) as saver:
        assert isinstance(saver, AsyncSqliteSaver)
        await runtime.build_graph(saver).ainvoke({"messages": [HumanMessage("one")]}, config)

    async with open_checkpointer(settings) as saver:
        result = await runtime.build_graph(saver).ainvoke(
            {"messages": [HumanMessage("two")]}, config
        )
    assert [m.content for m in result["messages"]] == [
        "one",
        "first answer",
        "two",
        "second answer",
    ]
