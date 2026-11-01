"""Knowledge-base search tool (Qdrant through the retriever)."""

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from config.logger import get_logger
from src.prompts.agent import (
    KNOWLEDGE_EMPTY_RESULT,
    KNOWLEDGE_QUERY_DESCRIPTION,
    KNOWLEDGE_TOOL_DESCRIPTION,
    KNOWLEDGE_TOOL_NAME,
    KNOWLEDGE_UNAVAILABLE_RESULT,
    PASSAGE_TEMPLATE,
)
from src.rag.retriever import Retriever
from src.utils.exceptions import ConfigurationError, ExternalServiceError
from src.utils.text import escape_tags

logger = get_logger(__name__)

QUERY_MAX_CHARS = 300


class KnowledgeSearchArgs(BaseModel):
    """Arguments the model supplies."""

    query: str = Field(
        min_length=2, max_length=QUERY_MAX_CHARS, description=KNOWLEDGE_QUERY_DESCRIPTION
    )


def make_knowledge_search_tool(retriever: Retriever) -> BaseTool:
    """Build the tool; an unavailable knowledge base returns a short safe message."""

    async def knowledge_search(query: str) -> str:
        try:
            passages = await retriever.search(query)
        except (ConfigurationError, ExternalServiceError) as exc:
            logger.warning("knowledge_search unavailable: %s", exc)
            return KNOWLEDGE_UNAVAILABLE_RESULT
        if not passages:
            return KNOWLEDGE_EMPTY_RESULT
        return "\n".join(
            PASSAGE_TEMPLATE.format(
                source=escape_tags(passage.source),
                score=passage.score,
                text=escape_tags(passage.text),
            )
            for passage in passages
        )

    return StructuredTool.from_function(
        coroutine=knowledge_search,
        name=KNOWLEDGE_TOOL_NAME,
        description=KNOWLEDGE_TOOL_DESCRIPTION,
        args_schema=KnowledgeSearchArgs,
    )
