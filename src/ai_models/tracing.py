"""LangSmith tracing: a no-op when ``TRACING_PROVIDER=none``. Errors are logged, never raised."""

import uuid
from datetime import datetime, timezone
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from config.logger import get_logger
from config.settings import Settings

logger = get_logger(__name__)


class Tracing:
    """Builds tracer callbacks and records runs for models that LangChain does not wrap."""

    def __init__(self, settings: Settings) -> None:
        self._project = settings.LANGSMITH_PROJECT
        self._client: Any | None = None
        if settings.TRACING_PROVIDER == "langsmith" and settings.LANGSMITH_API_KEY is not None:
            try:
                from langsmith import Client

                self._client = Client(api_key=settings.LANGSMITH_API_KEY.get_secret_value())
            except Exception as exc:
                logger.warning("LangSmith client could not be created: %s", type(exc).__name__)

    @property
    def enabled(self) -> bool:
        """True when runs are being sent to LangSmith."""
        return self._client is not None

    def get_callbacks(self, metadata: dict[str, Any] | None = None) -> list[BaseCallbackHandler]:
        """Callbacks to put in a ``RunnableConfig``; empty when tracing is off."""
        if self._client is None:
            return []
        try:
            from langchain_core.tracers.langchain import LangChainTracer

            return [LangChainTracer(project_name=self._project, client=self._client)]
        except Exception as exc:
            logger.warning("LangSmith tracer could not be created: %s", type(exc).__name__)
            return []

    def record_run(
        self,
        name: str,
        *,
        run_type: str,
        inputs: dict[str, Any],
        outputs: dict[str, Any],
        started_at: datetime,
        metadata: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        """Record one finished run (for example an STT or TTS call reported by LiveKit metrics)."""
        if self._client is None:
            return
        try:
            self._client.create_run(
                id=uuid.uuid4(),
                name=name,
                run_type=run_type,
                inputs=inputs,
                outputs=outputs,
                start_time=started_at,
                end_time=datetime.now(timezone.utc),
                error=error,
                project_name=self._project,
                extra={"metadata": metadata or {}},
            )
        except Exception as exc:
            logger.warning("LangSmith run %s was not recorded: %s", name, type(exc).__name__)

    def flush(self) -> None:
        """Send queued runs; call on shutdown."""
        if self._client is None:
            return
        try:
            self._client.flush()
        except Exception as exc:
            logger.warning("LangSmith flush failed: %s", type(exc).__name__)
