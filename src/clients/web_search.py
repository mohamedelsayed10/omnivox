"""DuckDuckGo web search through the ``ddgs`` package (synchronous, run in a worker thread)."""

import asyncio

from ddgs import DDGS
from ddgs.exceptions import DDGSException

from config.logger import get_logger
from config.settings import Settings
from src.utils.exceptions import ExternalServiceError
from src.utils.models import SearchHit

logger = get_logger(__name__)

# Slack on top of the library timeout, so the library gets to fail first with a clear error.
THREAD_TIMEOUT_MARGIN = 2.0


class WebSearchClient:
    """Async web search with a hard time limit."""

    def __init__(self, settings: Settings) -> None:
        self._timeout = settings.WEB_SEARCH_TIMEOUT
        self._region = settings.WEB_SEARCH_REGION
        self._max_results = settings.WEB_SEARCH_MAX_RESULTS

    async def search(self, query: str, *, max_results: int | None = None) -> list[SearchHit]:
        """Return up to ``max_results`` hits for ``query``."""
        limit = max_results or self._max_results
        try:
            raw = await asyncio.wait_for(
                asyncio.to_thread(self._search_sync, query, limit),
                timeout=self._timeout + THREAD_TIMEOUT_MARGIN,
            )
        except asyncio.TimeoutError as exc:
            raise ExternalServiceError("Web search timed out") from exc
        except DDGSException as exc:
            raise ExternalServiceError(f"Web search failed: {type(exc).__name__}: {exc}") from exc
        return [
            SearchHit(
                title=str(item.get("title", "")).strip(),
                url=str(item.get("href", "")).strip(),
                snippet=str(item.get("body", "")).strip(),
            )
            for item in raw
        ]

    def _search_sync(self, query: str, limit: int) -> list[dict]:
        with DDGS(timeout=int(self._timeout)) as ddgs:
            return list(ddgs.text(query, region=self._region, max_results=limit))
