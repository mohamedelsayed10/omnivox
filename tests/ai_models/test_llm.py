"""LLM service: input limits, error mapping, output checks, client config and Gemini signatures."""

import httpx
import openai
import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.ai_models.llm import (
    SIGNATURE_BYPASS,
    GeminiChatOpenAI,
    LLMService,
    build_chat_model,
    message_text,
    thinking_extra_body,
)
from src.utils.exceptions import (
    InvalidInputError,
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from tests.fakes import ScriptedChatModel, ai

REQUEST = httpx.Request("POST", "https://llm.test/v1/chat/completions")


class RaisingModel(ScriptedChatModel):
    error: Exception

    def _generate(self, *args, **kwargs):
        raise self.error

    def _stream(self, *args, **kwargs):
        raise self.error


def service_raising(settings, error: Exception) -> LLMService:
    return LLMService(settings, model=RaisingModel(script=[], error=error))


async def test_ainvoke_returns_the_assistant_message(settings):
    llm = LLMService(settings, model=ScriptedChatModel(script=[ai("Hello.")]))
    reply = await llm.ainvoke([HumanMessage("hi")])
    assert reply.content == "Hello."


async def test_ainvoke_passes_tools_through(settings):
    llm = LLMService(settings, model=ScriptedChatModel(script=[ai("", ("lookup", {"q": "x"}))]))
    reply = await llm.ainvoke([HumanMessage("hi")], tools=[object()])
    assert reply.tool_calls[0]["name"] == "lookup"


async def test_input_longer_than_limit_is_rejected_before_calling_the_model(make_settings):
    settings = make_settings(MAX_INPUT_CHARS=10)
    model = ScriptedChatModel(script=[ai("never")])
    with pytest.raises(InvalidInputError):
        await LLMService(settings, model=model).ainvoke([HumanMessage("x" * 11)])
    assert model.seen == []


@pytest.mark.parametrize(
    "error,expected",
    [
        (openai.APITimeoutError(request=REQUEST), LLMTimeoutError),
        (TimeoutError("slow"), LLMTimeoutError),
        (
            openai.RateLimitError(
                "limit", response=httpx.Response(429, request=REQUEST), body=None
            ),
            LLMRateLimitError,
        ),
        (
            openai.APIStatusError("bad", response=httpx.Response(500, request=REQUEST), body=None),
            LLMError,
        ),
        (openai.APIConnectionError(request=REQUEST), LLMError),
        (RuntimeError("anything"), LLMError),
    ],
)
async def test_provider_errors_map_to_domain_errors(settings, error, expected):
    with pytest.raises(expected) as caught:
        await service_raising(settings, error).ainvoke([HumanMessage("hi")])
    assert type(caught.value) is expected
    assert isinstance(caught.value.__cause__, type(error))


async def test_empty_output_is_an_error(settings):
    llm = LLMService(settings, model=ScriptedChatModel(script=[ai("   ")]))
    with pytest.raises(LLMError, match="empty"):
        await llm.ainvoke([HumanMessage("hi")])


async def test_filtered_output_is_an_error(settings):
    llm = LLMService(settings, model=ScriptedChatModel(script=[ai("", finish="content_filter")]))
    with pytest.raises(LLMError, match="blocked"):
        await llm.ainvoke([HumanMessage("hi")])


async def test_truncated_but_non_empty_output_is_returned(settings):
    llm = LLMService(
        settings, model=ScriptedChatModel(script=[ai("Partial answ", finish="length")])
    )
    assert (await llm.ainvoke([HumanMessage("hi")])).content == "Partial answ"


async def test_tool_call_without_text_is_valid_output(settings):
    llm = LLMService(settings, model=ScriptedChatModel(script=[ai("", ("t", {}))]))
    assert (await llm.ainvoke([HumanMessage("hi")])).tool_calls


async def test_astream_yields_text_pieces(settings):
    llm = LLMService(settings, model=ScriptedChatModel(script=[ai("one two three")]))
    pieces = [piece async for piece in llm.astream([HumanMessage("hi")])]
    assert "".join(pieces) == "one two three"
    assert len(pieces) == 3


async def test_astream_with_no_text_is_an_error(settings):
    llm = LLMService(settings, model=ScriptedChatModel(script=[ai("")]))
    with pytest.raises(LLMError):
        [piece async for piece in llm.astream([HumanMessage("hi")])]


async def test_astream_maps_provider_errors(settings):
    llm = service_raising(settings, openai.APITimeoutError(request=REQUEST))
    with pytest.raises(LLMTimeoutError):
        [piece async for piece in llm.astream([HumanMessage("hi")])]


def test_message_text_handles_content_blocks():
    message = AIMessage(content=[{"type": "text", "text": "a"}, "b", {"type": "image_url"}])
    assert message_text(message) == "ab"


def test_info_has_no_secrets(settings):
    info = LLMService(settings, model=ScriptedChatModel(script=[])).info
    assert info.model == settings.OPENAI_MODEL
    assert "key" not in str(info).lower().replace("openai-compatible", "")


def test_client_is_configured_from_settings(make_settings):
    settings = make_settings(
        MAX_RETRIES=5, REQUEST_TIMEOUT=12, OPENAI_REASONING_EFFORT="minimal", OPENAI_MAX_TOKENS=300
    )
    model = build_chat_model(settings)
    assert isinstance(model, GeminiChatOpenAI)
    assert model.max_retries == 5
    assert model.request_timeout == 12
    assert model.reasoning_effort == "minimal"
    assert model.max_tokens == 300
    assert model.model_name == "gemini-3-flash-preview"
    assert model.streaming is True


def test_other_providers_get_the_plain_client(make_settings):
    model = build_chat_model(
        make_settings(OPENAI_BASE_URL="http://localhost:8000/v1", OPENAI_MODEL="local-model")
    )
    assert type(model).__name__ == "ChatOpenAI"
    assert model.model_name == "local-model"


def replayed_tool_call_payload(model: GeminiChatOpenAI) -> list[dict]:
    history = [
        HumanMessage("hi"),
        AIMessage(
            content="", tool_calls=[{"name": "t", "args": {}, "id": "call_9", "type": "tool_call"}]
        ),
    ]
    payload = model._get_request_payload(history)
    return payload["messages"][1]["tool_calls"]


def test_replayed_tool_calls_get_the_bypass_signature_when_none_was_seen(make_settings):
    model = build_chat_model(make_settings())
    (call,) = replayed_tool_call_payload(model)
    assert call["extra_content"] == {"google": {"thought_signature": SIGNATURE_BYPASS}}


def test_streamed_signatures_are_remembered_and_replayed(make_settings):
    model = build_chat_model(make_settings())
    model._remember_signatures(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "id": "call_9",
                                "function": {"name": "t", "arguments": "{}"},
                                "extra_content": {
                                    "google": {"thought_signature": "real-signature"}
                                },
                            }
                        ]
                    }
                }
            ]
        }
    )
    (call,) = replayed_tool_call_payload(model)
    assert call["extra_content"]["google"]["thought_signature"] == "real-signature"


def test_signature_cache_is_bounded(make_settings, monkeypatch):
    monkeypatch.setattr("src.ai_models.llm.SIGNATURE_CACHE_SIZE", 3)
    model = build_chat_model(make_settings())
    for index in range(10):
        model._remember_signatures(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "id": f"c{index}",
                                    "extra_content": {"google": {"thought_signature": f"s{index}"}},
                                }
                            ]
                        }
                    }
                ]
            }
        )
    assert list(model._signatures) == ["c7", "c8", "c9"]


async def test_every_service_owns_its_http_client_and_closes_it(make_settings):
    first, second = LLMService(make_settings()), LLMService(make_settings())
    client_a, client_b = first.get_model().http_async_client, second.get_model().http_async_client
    assert client_a is not None and client_a is not client_b  # no sharing across event loops
    await first.aclose()
    assert client_a.is_closed and not client_b.is_closed
    await second.aclose()


async def test_injected_models_are_never_closed_by_the_service(settings):
    model = ScriptedChatModel(script=[])
    await LLMService(settings, model=model).aclose()  # nothing to close, must not raise


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        (False, {"chat_template_kwargs": {"enable_thinking": False}}),
        (True, {"chat_template_kwargs": {"enable_thinking": True}}),
    ],
)
def test_thinking_switch_becomes_chat_template_kwargs(make_settings, value, expected):
    settings = make_settings(OPENAI_ENABLE_THINKING=value)
    assert thinking_extra_body(settings) == expected
    model = build_chat_model(settings)
    assert model.extra_body == expected
    payload = model._get_request_payload([HumanMessage("hi")])
    assert payload.get("extra_body") == expected


@pytest.mark.parametrize("value", [False, True])
def test_openrouter_also_gets_its_own_reasoning_parameter(make_settings, value):
    settings = make_settings(
        OPENAI_BASE_URL="https://openrouter.ai/api/v1/",
        OPENAI_MODEL="nvidia/nemotron-3.5-lightning:free",
        OPENAI_ENABLE_THINKING=value,
    )
    assert thinking_extra_body(settings) == {
        "chat_template_kwargs": {"enable_thinking": value},
        "reasoning": {"enabled": value},
    }
    payload = build_chat_model(settings)._get_request_payload([HumanMessage("hi")])
    assert payload["extra_body"]["reasoning"] == {"enabled": value}


def test_other_hosts_do_not_get_the_openrouter_parameter(make_settings):
    settings = make_settings(
        OPENAI_BASE_URL="http://localhost:8000/v1", OPENAI_ENABLE_THINKING=False
    )
    assert "reasoning" not in thinking_extra_body(settings)


def test_thinking_switch_works_for_any_openai_compatible_host(make_settings):
    settings = make_settings(
        OPENAI_BASE_URL="http://vllm.internal:8000/v1",
        OPENAI_MODEL="Qwen/Qwen3-8B",
        OPENAI_ENABLE_THINKING=False,
        OPENAI_REASONING_EFFORT=None,
    )
    model = build_chat_model(settings)
    assert type(model).__name__ == "ChatOpenAI"  # not the Gemini subclass
    assert model.extra_body == {"chat_template_kwargs": {"enable_thinking": False}}
    assert model.reasoning_effort is None


def test_service_info_reports_the_thinking_switch(make_settings):
    info = LLMService(
        make_settings(OPENAI_ENABLE_THINKING=False), model=ScriptedChatModel(script=[])
    ).info
    assert info.details["thinking"] is False
