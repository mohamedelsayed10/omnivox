"""Framework-free domain errors. The API layer maps them to HTTP responses."""

from typing import Any


class OmniVoxError(Exception):
    """Base class. ``public_message`` is safe to show to clients; ``str(exc)`` is for logs only."""

    code = "internal_error"
    default_message = "An internal error occurred."
    expose_message = False

    def __init__(self, message: str | None = None, *, details: Any | None = None) -> None:
        super().__init__(message or self.default_message)
        self.details = details

    @property
    def public_message(self) -> str:
        """Message returned to API clients."""
        return str(self) if self.expose_message else self.default_message


class InvalidInputError(OmniVoxError):
    """Input rejected by a business rule. The message is written for the client."""

    code = "invalid_input"
    default_message = "The request is invalid."
    expose_message = True


class NotFoundError(OmniVoxError):
    """The requested item does not exist. The message is written for the client."""

    code = "not_found"
    default_message = "The requested item was not found."
    expose_message = True


class UnauthorizedError(OmniVoxError):
    """Missing or wrong API key."""

    code = "unauthorized"
    default_message = "Missing or invalid API key."


class LLMError(OmniVoxError):
    """The model call failed or returned unusable output."""

    code = "llm_error"
    default_message = "The language model request failed."


class LLMTimeoutError(LLMError):
    """The model call timed out."""

    code = "llm_timeout"
    default_message = "The language model timed out."


class LLMRateLimitError(LLMError):
    """The model provider rejected the call because of rate limits."""

    code = "llm_rate_limited"
    default_message = "The language model is rate limited. Try again shortly."


class ExternalServiceError(OmniVoxError):
    """A dependency such as Qdrant, the embedding API or web search failed."""

    code = "external_service_error"
    default_message = "An external service request failed."


class GraphExecutionError(OmniVoxError):
    """The agent graph failed or hit its step limit."""

    code = "graph_error"
    default_message = "The agent could not complete the request."


class ConfigurationError(OmniVoxError):
    """A feature was used while its configuration is missing."""

    code = "service_not_configured"
    default_message = "This feature is not configured on the server."
    expose_message = True
