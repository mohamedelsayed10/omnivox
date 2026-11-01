"""Web search tool (DuckDuckGo through the ``ddgs`` client)."""

from urllib.parse import urlparse

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from config.logger import get_logger
from src.clients.web_search import WebSearchClient
from src.prompts.agent import (
    WEB_EMPTY_RESULT,
    WEB_QUERY_DESCRIPTION,
    WEB_RESULT_TEMPLATE,
    WEB_TOOL_DESCRIPTION,
    WEB_TOOL_NAME,
    WEB_UNAVAILABLE_RESULT,
)
from src.utils.exceptions import ExternalServiceError
from src.utils.text import escape_tags, truncate

logger = get_logger(__name__)

SNIPPET_MAX_CHARS = 400
QUERY_MAX_CHARS = 300


class WebSearchArgs(BaseModel):
    """Arguments the model supplies."""

    query: str = Field(min_length=2, max_length=QUERY_MAX_CHARS, description=WEB_QUERY_DESCRIPTION)


def make_web_search_tool(client: WebSearchClient) -> BaseTool:
    """Build the tool; failures return a short safe message instead of raising."""

    async def web_search(query: str) -> str:
        try:
            hits = await client.search(query)
        except ExternalServiceError as exc:
            logger.warning("web_search failed: %s", exc)
            return WEB_UNAVAILABLE_RESULT
        if not hits:
            return WEB_EMPTY_RESULT
        return "\n".join(
            WEB_RESULT_TEMPLATE.format(
                site=escape_tags(urlparse(hit.url).netloc),
                title=escape_tags(hit.title),
                snippet=escape_tags(truncate(hit.snippet, SNIPPET_MAX_CHARS)),
            )
            for hit in hits
        )

    return StructuredTool.from_function(
        coroutine=web_search,
        name=WEB_TOOL_NAME,
        description=WEB_TOOL_DESCRIPTION,
        args_schema=WebSearchArgs,
    )
