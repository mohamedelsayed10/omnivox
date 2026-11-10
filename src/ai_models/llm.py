"""LLM service: the only code that builds or calls chat models (any OpenAI-compatible endpoint)."""

from collections import OrderedDict
from collections.abc import AsyncIterator, Sequence
from typing import Any
from urllib.parse import urlparse

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from openai import DefaultAsyncHttpxClient
from pydantic import PrivateAttr

from config.logger import get_logger
from config.settings import Settings
from src.ai_models.base import PLACEHOLDER_API_KEY, AIModel, ModelInfo, classify_provider_error
from src.utils.exceptions import (
    InvalidInputError,
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
    OmniVoxError,
)

logger = get_logger(__name__)

FINISH_FILTERED = "content_filter"
FINISH_TRUNCATED = "length"
GEMINI_HOST_MARKER = "generativelanguage.googleapis.com"
OPENROUTER_HOST_MARKER = "openrouter.ai"
# Documented value that tells Gemini to skip signature validation for a replayed call.
SIGNATURE_BYPASS = "skip_thought_signature_validator"
SIGNATURE_CACHE_SIZE = 512


class GeminiChatOpenAI(ChatOpenAI):
    """ChatOpenAI that replays Gemini 3 thought signatures on tool calls.

    Gemini returns a signature in ``tool_calls[].extra_content.google.thought_signature`` and
    rejects the next request (HTTP 400) when a replayed tool call lacks it. LangChain drops the
    field, so signatures are remembered per tool call id while streaming and put back into the
    outgoing payload. Calls with an unknown id (for example after a restart) get the bypass value.
    """

    _signatures: OrderedDict[str, str] = PrivateAttr(default_factory=OrderedDict)

    def _convert_chunk_to_generation_chunk(
        self, chunk: dict, default_chunk_class: type, base_generation_info: dict | None
    ) -> Any:
        self._remember_signatures(chunk)
        return super()._convert_chunk_to_generation_chunk(
            chunk, default_chunk_class, base_generation_info
        )

    def _get_request_payload(self, input_: Any, *, stop: list[str] | None = None, **kwargs: Any):
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        for message in payload.get("messages", []):
            for call in message.get("tool_calls") or []:
                signature = self._signatures.get(call.get("id", ""), SIGNATURE_BYPASS)
                call.setdefault("extra_content", {"google": {"thought_signature": signature}})
        return payload

    def _remember_signatures(self, chunk: dict) -> None:
        for choice in chunk.get("choices") or []:
            for call in (choice.get("delta") or {}).get("tool_calls") or []:
                extra = call.get("extra_content") or {}
                signature = (extra.get("google") or {}).get("thought_signature")
                if signature and call.get("id"):
                    self._signatures[call["id"]] = signature
                    while len(self._signatures) > SIGNATURE_CACHE_SIZE:
                        self._signatures.popitem(last=False)


def effective_thinking(settings: Settings) -> bool | None:
    """The thinking switch for the configured model, or ``None`` when nothing should be sent.

    The switch applies only to models whose name contains one of the fragments in
    ``OPENAI_THINKING_MODELS`` (default ``qwen,gemma``, compared case-insensitively; ``*`` means
    every model). Other models, Gemini for example, never receive the parameter.
    """
    thinking = settings.OPENAI_ENABLE_THINKING
    if thinking is None:
        return None
    fragments = settings.thinking_models_list
    name = settings.OPENAI_MODEL.lower()
    if "*" in fragments or any(fragment in name for fragment in fragments):
        return thinking
    return None


def thinking_extra_body(settings: Settings) -> dict[str, Any] | None:
    """``extra_body`` that switches thinking on or off.

    Qwen, Gemma and similar models served by vLLM read ``enable_thinking`` from
    ``chat_template_kwargs``. OpenRouter does not forward that field for every model; it has its
    own ``reasoning`` parameter, which is added when the endpoint is OpenRouter. ``None`` (setting
    left blank, or a model outside ``OPENAI_THINKING_MODELS``) sends nothing and the model default
    applies.
    """
    thinking = effective_thinking(settings)
    if thinking is None:
        return None
    body: dict[str, Any] = {"chat_template_kwargs": {"enable_thinking": thinking}}
    if OPENROUTER_HOST_MARKER in settings.OPENAI_BASE_URL:
        body["reasoning"] = {"enabled": thinking}
    return body


def request_extra_body(settings: Settings) -> dict[str, Any] | None:
    """Everything the OpenAI schema has no field for: the thinking switch and vLLM sampling.

    ``top_k``, ``min_p`` and ``repetition_penalty`` are vLLM extensions of the chat API, so they
    travel in ``extra_body``; each is sent only when its setting is not blank.
    """
    body = dict(thinking_extra_body(settings) or {})
    extras = {
        "top_k": settings.OPENAI_TOP_K,
        "min_p": settings.OPENAI_MIN_P,
        "repetition_penalty": settings.OPENAI_REPETITION_PENALTY,
    }
    body.update({name: value for name, value in extras.items() if value is not None})
    return body or None


def build_chat_model(settings: Settings) -> ChatOpenAI:
    """Create the chat client from settings. Retries and timeout live in the client itself.

    Each client gets its own HTTP client: LangChain would otherwise share a cached one whose
    connections belong to the first event loop, which breaks when another loop (a later voice
    session) uses it.
    """
    if settings.OPENAI_ENABLE_THINKING is not None and effective_thinking(settings) is None:
        logger.info(
            "OPENAI_ENABLE_THINKING is ignored: %s is not matched by OPENAI_THINKING_MODELS (%s)",
            settings.OPENAI_MODEL,
            settings.OPENAI_THINKING_MODELS,
        )
    client_class = (
        GeminiChatOpenAI if GEMINI_HOST_MARKER in settings.OPENAI_BASE_URL else ChatOpenAI
    )
    return client_class(
        model=settings.OPENAI_MODEL,
        api_key=settings.OPENAI_API_KEY.get_secret_value() or PLACEHOLDER_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
        temperature=settings.OPENAI_TEMPERATURE,
        max_tokens=settings.OPENAI_MAX_TOKENS,
        top_p=settings.OPENAI_TOP_P,
        presence_penalty=settings.OPENAI_PRESENCE_PENALTY,
        frequency_penalty=settings.OPENAI_FREQUENCY_PENALTY,
        seed=settings.OPENAI_SEED,
        reasoning_effort=settings.OPENAI_REASONING_EFFORT,
        extra_body=request_extra_body(settings),
        timeout=settings.REQUEST_TIMEOUT,
        max_retries=settings.MAX_RETRIES,
        streaming=True,
        stream_usage=True,
        http_async_client=DefaultAsyncHttpxClient(timeout=settings.REQUEST_TIMEOUT),
    )


def message_text(message: BaseMessage) -> str:
    """Plain text of a message whose content may be a string or a list of content blocks."""
    content = message.content
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return "".join(parts)


class LLMService(AIModel):
    """Async access to the chat model with input limits, error mapping and output checks."""

    kind = "llm"

    def __init__(self, settings: Settings, *, model: BaseChatModel | None = None) -> None:
        self._settings = settings
        self._owns_model = model is None
        self._model = model or build_chat_model(settings)

    @property
    def info(self) -> ModelInfo:
        host = urlparse(self._settings.OPENAI_BASE_URL).netloc
        return ModelInfo(
            kind=self.kind,
            provider="openai-compatible",
            model=self._settings.OPENAI_MODEL,
            details={
                "host": host,
                "reasoning_effort": self._settings.OPENAI_REASONING_EFFORT,
                "thinking": effective_thinking(self._settings),
            },
        )

    async def aclose(self) -> None:
        """Close the HTTP client this service created (not one injected by a test)."""
        client = getattr(self._model, "http_async_client", None) if self._owns_model else None
        if client is not None:
            await client.aclose()

    def get_model(self) -> BaseChatModel:
        """The underlying chat model, for graph nodes that bind tools themselves."""
        return self._model

    async def ainvoke(
        self,
        messages: Sequence[BaseMessage],
        *,
        tools: Sequence[Any] | None = None,
        config: RunnableConfig | None = None,
    ) -> AIMessage:
        """Run the model once and return a validated assistant message."""
        self._check_input(messages)
        runnable = self._model.bind_tools(list(tools)) if tools else self._model
        async with self.traced("ainvoke", messages=len(messages)) as outputs:
            try:
                result = await runnable.ainvoke(list(messages), config=config)
            except OmniVoxError:
                raise
            except Exception as exc:
                raise self._map_error(exc) from exc
            if not isinstance(result, AIMessage):
                raise LLMError(f"Unexpected model result type {type(result).__name__}")
            self._check_output(result)
            usage = result.usage_metadata or {}
            outputs["input_tokens"] = usage.get("input_tokens")
            outputs["output_tokens"] = usage.get("output_tokens")
            return result

    async def astream(
        self, messages: Sequence[BaseMessage], *, config: RunnableConfig | None = None
    ) -> AsyncIterator[str]:
        """Yield the reply text as it is generated."""
        self._check_input(messages)
        produced = False
        async with self.traced("astream", messages=len(messages)):
            try:
                async for chunk in self._model.astream(list(messages), config=config):
                    text = message_text(chunk)
                    if text:
                        produced = True
                        yield text
            except OmniVoxError:
                raise
            except Exception as exc:
                raise self._map_error(exc) from exc
        if not produced:
            raise LLMError("The model returned an empty stream")

    def _check_input(self, messages: Sequence[BaseMessage]) -> None:
        limit = self._settings.MAX_INPUT_CHARS
        for message in messages:
            if isinstance(message, HumanMessage) and len(message_text(message)) > limit:
                raise InvalidInputError(f"Message is longer than {limit} characters.")

    @staticmethod
    def _check_output(result: AIMessage) -> None:
        finish = (result.response_metadata or {}).get("finish_reason")
        has_text = bool(message_text(result).strip())
        if not has_text and not result.tool_calls:
            if finish == FINISH_FILTERED:
                raise LLMError("The provider blocked the response (content filter)")
            raise LLMError(f"The model returned empty output (finish_reason={finish})")
        if finish == FINISH_TRUNCATED:
            logger.warning("Model output was truncated by the token limit")

    @staticmethod
    def _map_error(exc: Exception) -> LLMError:
        kind = classify_provider_error(exc)
        detail = f"{type(exc).__name__}: {exc}"
        if kind == "timeout":
            return LLMTimeoutError(detail)
        if kind == "rate_limit":
            return LLMRateLimitError(detail)
        return LLMError(detail)
