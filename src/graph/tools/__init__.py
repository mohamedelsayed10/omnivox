"""Tool allow-list: the only tools the agent can call."""

from langchain_core.tools import BaseTool

from src.clients.web_search import WebSearchClient
from src.graph.tools.knowledge_search import make_knowledge_search_tool
from src.graph.tools.web_search import make_web_search_tool
from src.rag.retriever import Retriever


def build_tools(*, retriever: Retriever, web_search: WebSearchClient) -> list[BaseTool]:
    """Create the registered tools. Add a new tool here and nowhere else."""
    return [make_knowledge_search_tool(retriever), make_web_search_tool(web_search)]
