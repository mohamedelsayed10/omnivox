"""Graph state and node names."""

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

NODE_AGENT = "agent"
NODE_TOOLS = "tools"
ROUTER_AFTER_AGENT = "route_after_agent"
GRAPH_NAME = "omnivox_agent"


class AgentState(TypedDict):
    """Conversation messages; ``add_messages`` appends instead of replacing."""

    messages: Annotated[list[AnyMessage], add_messages]
