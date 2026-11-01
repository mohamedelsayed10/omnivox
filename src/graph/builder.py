"""Wires the agent graph: agent <-> tools until the model answers without a tool call."""

from collections.abc import Sequence
from typing import Literal

from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from config.settings import Settings
from src.ai_models.llm import LLMService
from src.graph.nodes.agent import make_agent_node
from src.graph.nodes.tools import make_tools_node
from src.graph.state import GRAPH_NAME, NODE_AGENT, NODE_TOOLS, AgentState


def route_after_agent(state: AgentState) -> Literal["tools", "__end__"]:
    """Run tools when the model asked for them, otherwise finish."""
    last = state["messages"][-1]
    return NODE_TOOLS if isinstance(last, AIMessage) and last.tool_calls else END


def build_graph(
    *,
    llm: LLMService,
    tools: Sequence[BaseTool],
    settings: Settings,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Compile the graph. Pass a checkpointer for thread memory, none for a stateless graph."""
    graph = StateGraph(AgentState)
    graph.add_node(NODE_AGENT, make_agent_node(llm, tools, settings))
    graph.add_node(NODE_TOOLS, make_tools_node(tools))
    graph.add_edge(START, NODE_AGENT)
    graph.add_conditional_edges(NODE_AGENT, route_after_agent, [NODE_TOOLS, END])
    graph.add_edge(NODE_TOOLS, NODE_AGENT)
    return graph.compile(checkpointer=checkpointer, name=GRAPH_NAME)
