"""Manual smoke test against the real providers. Needs real keys in .env; not part of pytest.

Run with ``make smoke`` or ``uv run python scripts/smoke_models.py``. Prints PASS, FAIL or SKIP
per component and exits non-zero when any check fails. Never prints secrets or full responses.
"""

import asyncio
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import tool
from livekit import rtc
from livekit.agents import stt as lk_stt
from livekit.agents.utils import http_context

from config.settings import Settings, get_settings
from src.ai_models.asr import SpeechToText
from src.ai_models.embeddings import EmbeddingService
from src.ai_models.llm import LLMService
from src.ai_models.tts import TextToSpeech
from src.ai_models.turn import TurnDetection
from src.ai_models.vad import VoiceActivityDetector
from src.utils.exceptions import ConfigurationError

SPOKEN_TEXT = "The quick brown fox jumps over the lazy dog."
STT_TARGET_RATE = 16000
STT_WAIT_SECONDS = 20


class Skip(Exception):
    """Raised by a check that cannot run with the current configuration."""


@tool
def lookup_code(topic: str) -> str:
    """Return the access code for a topic."""
    return "The access code is 4242."


async def check_llm(settings: Settings) -> str:
    llm = LLMService(settings)
    history = [
        HumanMessage("Use the lookup_code tool for the topic 'vault', then tell me the code.")
    ]
    first = await llm.ainvoke(history, tools=[lookup_code])
    if not first.tool_calls:
        raise AssertionError("model did not call the tool")
    history.append(first)
    history.extend(
        ToolMessage(content=lookup_code.invoke(call["args"]), tool_call_id=call["id"])
        for call in first.tool_calls
    )
    final = await llm.ainvoke(history, tools=[lookup_code])
    if "4242" not in str(final.content):
        raise AssertionError("final answer does not contain the tool result")
    return f"model={settings.OPENAI_MODEL} tool round trip ok"


async def check_embeddings(settings: Settings) -> str:
    service = EmbeddingService(settings)
    if not service.configured:
        raise Skip("EMBEDDING_API_KEY is not set")
    vectors = await service.aembed_documents(["alpha", "beta"])
    return f"model={settings.EMBEDDING_MODEL} dimension={len(vectors[0])}"


async def check_qdrant(settings: Settings) -> str:
    from qdrant_client import AsyncQdrantClient

    key = settings.QDRANT_API_KEY.get_secret_value() if settings.QDRANT_API_KEY else None
    client = AsyncQdrantClient(url=settings.QDRANT_URL, api_key=key)
    try:
        collections = await client.get_collections()
    finally:
        await client.close()
    return f"reachable, {len(collections.collections)} collection(s)"


async def check_vad_and_turn(settings: Settings) -> str:
    VoiceActivityDetector(settings).load()
    options = TurnDetection(settings).options()
    return f"silero loaded, turn_detection={type(options['turn_detection']).__name__}"


async def synthesize(settings: Settings) -> rtc.AudioFrame:
    plugin = TextToSpeech(settings).build()
    frames: list[rtc.AudioFrame] = []
    async for event in plugin.synthesize(SPOKEN_TEXT):
        frames.append(event.frame)
    if not frames:
        raise AssertionError("TTS returned no audio")
    return rtc.combine_audio_frames(frames)


async def check_tts(settings: Settings) -> str:
    if settings.TTS_PROVIDER == "elevenlabs" and settings.ELEVENLABS_API_KEY is None:
        raise Skip("ELEVENLABS_API_KEY is not set")
    started = time.perf_counter()
    audio = await synthesize(settings)
    seconds = audio.samples_per_channel / audio.sample_rate
    return (
        f"model={settings.TTS_MODEL} {seconds:.1f}s of audio at {audio.sample_rate} Hz "
        f"in {time.perf_counter() - started:.1f}s"
    )


async def check_stt(settings: Settings) -> str:
    if settings.STT_PROVIDER == "elevenlabs" and settings.ELEVENLABS_API_KEY is None:
        raise Skip("ELEVENLABS_API_KEY is not set")
    audio = await synthesize(settings)
    plugin = SpeechToText(settings).build()
    stream = plugin.stream()
    resampler = rtc.AudioResampler(
        audio.sample_rate, STT_TARGET_RATE, num_channels=audio.num_channels
    )
    for frame in [*resampler.push(bytearray(audio.data)), *resampler.flush()]:
        stream.push_frame(frame)
    silence = rtc.AudioFrame.create(STT_TARGET_RATE, 1, STT_TARGET_RATE)  # one second
    stream.push_frame(silence)
    stream.end_input()

    async def final_text() -> str:
        async for event in stream:
            if event.type == lk_stt.SpeechEventType.FINAL_TRANSCRIPT and event.alternatives:
                return event.alternatives[0].text
        return ""

    text = await asyncio.wait_for(final_text(), timeout=STT_WAIT_SECONDS)
    await stream.aclose()
    if "fox" not in text.lower():
        raise AssertionError(f"transcript does not match the spoken sentence ({len(text)} chars)")
    return f"model={settings.STT_MODEL} transcript matched"


CHECKS: list[tuple[str, Callable[[Settings], Awaitable[str]]]] = [
    ("llm", check_llm),
    ("embeddings", check_embeddings),
    ("qdrant", check_qdrant),
    ("vad+turn", check_vad_and_turn),
    ("tts", check_tts),
    ("stt", check_stt),
]


async def main() -> int:
    settings = get_settings()
    failures = 0
    async with http_context.open():
        for name, check in CHECKS:
            try:
                detail = await check(settings)
                print(f"PASS  {name:<11} {detail}")
            except (Skip, ConfigurationError) as exc:
                print(f"SKIP  {name:<11} {exc}")
            except Exception as exc:
                failures += 1
                print(f"FAIL  {name:<11} {type(exc).__name__}: {str(exc)[:300]}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
