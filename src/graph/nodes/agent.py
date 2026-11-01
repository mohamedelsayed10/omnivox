"""The agent node: prompt, history window and the model call with tools bound."""

import time
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timezone

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    trim_messages,
)
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool

from config.logger import get_logger
from config.settings import Settings
from src.ai_models.llm import LLMService
from src.graph.state import NODE_AGENT, AgentState
from src.prompts.agent import AGENT_PROMPT

logger = get_logger(__name__)

TIME_FORMAT = "%A, %d %B %Y, %H:%M UTC"

AgentNode = Callable[[AgentState, RunnableConfig], Awaitable[dict[str, list[AIMessage]]]]


def _current_turn(history: list[BaseMessage]) -> list[BaseMessage]:
    """Messages from the latest user message on, so a small window never empties the context."""
    start = max((i for i, m in enumerate(history) if isinstance(m, HumanMessage)), default=0)
    return history[start:]


def make_agent_node(llm: LLMService, tools: Sequence[BaseTool], settings: Settings) -> AgentNode:
    """Create the node. Incoming system messages are dropped: the prompt module owns them."""

    async def agent(state: AgentState, config: RunnableConfig) -> dict[str, list[AIMessage]]:
        started = time.perf_counter()
        history = [m for m in state["messages"] if not isinstance(m, SystemMessage)]
        window = trim_messages(
            history,
            max_tokens=settings.GRAPH_MAX_HISTORY_MESSAGES,
            token_counter=len,
            strategy="last",
            start_on="human",
        )
        if not window:
            window = _current_turn(history)
        prompt = await AGENT_PROMPT.ainvoke(
            {
                "messages": window,
                "current_datetime": datetime.now(timezone.utc).strftime(TIME_FORMAT),
            }
        )
        logger.info("%s: start (history=%d messages)", NODE_AGENT, len(window))
        reply = await llm.ainvoke(prompt.to_messages(), tools=tools, config=config)
        logger.info(
            "%s: done in %.0f ms (tool_calls=%d)",
            NODE_AGENT,
            (time.perf_counter() - started) * 1000,
            len(reply.tool_calls),
        )
        return {"messages": [reply]}

    return agent
