"""The tools node: runs the tool calls of the last assistant message in parallel."""

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool

from config.logger import get_logger
from src.graph.state import NODE_TOOLS, AgentState
from src.prompts.agent import TOOL_ERROR_RESULT, UNKNOWN_TOOL_RESULT

logger = get_logger(__name__)

ToolsNode = Callable[[AgentState, RunnableConfig], Awaitable[dict[str, list[ToolMessage]]]]


def make_tools_node(tools: Sequence[BaseTool]) -> ToolsNode:
    """Create the node over an explicit allow-list; bad calls and tool errors become messages."""
    registry = {tool.name: tool for tool in tools}

    async def run_tools(state: AgentState, config: RunnableConfig) -> dict[str, list[ToolMessage]]:
        started = time.perf_counter()
        last = state["messages"][-1]
        calls = last.tool_calls if isinstance(last, AIMessage) else []
        logger.info("%s: start (%d call(s))", NODE_TOOLS, len(calls))
        results = await asyncio.gather(*(_run_call(registry, call, config) for call in calls))
        logger.info("%s: done in %.0f ms", NODE_TOOLS, (time.perf_counter() - started) * 1000)
        return {"messages": list(results)}

    return run_tools


async def _run_call(
    registry: dict[str, BaseTool], call: dict[str, Any], config: RunnableConfig
) -> ToolMessage:
    name, call_id = call["name"], call["id"]
    tool = registry.get(name)
    if tool is None:
        logger.warning("Model requested unknown tool %s", name)
        return ToolMessage(UNKNOWN_TOOL_RESULT, tool_call_id=call_id, name=name, status="error")
    try:
        output = await tool.ainvoke(call["args"], config)
    except Exception as exc:
        logger.warning("Tool %s failed: %s: %s", name, type(exc).__name__, exc)
        return ToolMessage(TOOL_ERROR_RESULT, tool_call_id=call_id, name=name, status="error")
    return ToolMessage(str(output), tool_call_id=call_id, name=name)
