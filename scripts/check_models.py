"""Live smoke test of the configured models, through the project's own service classes.

Reads ``.env`` exactly like the app, then calls the real LLM, embedding, TTS and STT servers:

1. LLM: a plain reply, the time to the first streamed token, and a tool call.
2. Embeddings: vector size, and a matching passage must outscore an unrelated one.
3. TTS: synthesizes a sentence and reports the time to the first audio frame.
4. STT: transcribes that same audio and compares the text with the input (round trip).

It is not part of the offline suite (``make test`` never touches the network).

    uv run python scripts/check_models.py
    uv run python scripts/check_models.py --text "Hello, how are you today?"
"""

import argparse
import asyncio
import difflib
import re
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool

from config.settings import Settings, get_settings
from src.ai_models.asr import SpeechToText
from src.ai_models.embeddings import EmbeddingService
from src.ai_models.llm import LLMService, effective_thinking, message_text
from src.ai_models.tts import TextToSpeech

TEXT_ARABIC = "مرحبا، أريد أن أعرف كم تستغرق الفترة التجريبية المجانية."
TEXT_ENGLISH = "Hello, I would like to know how long the free trial lasts."
PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)
SIMILARITY_PASS = 0.8


@tool
def get_weather(city: str) -> str:
    """Get the current weather for a city."""
    return f"Sunny in {city}"


def normalize(text: str) -> str:
    return " ".join(PUNCTUATION.sub(" ", text).lower().split())


class Report:
    """Collects one line per check and remembers whether any failed."""

    def __init__(self) -> None:
        self.failed = False

    async def run(self, name: str, check: Callable[[], Awaitable[str]]) -> None:
        started = time.perf_counter()
        try:
            detail = await check()
            status = "PASS"
        except Exception as exc:  # a smoke test reports every failure and keeps going
            detail = f"{type(exc).__name__}: {exc}"
            status = "FAIL"
            self.failed = True
        elapsed = time.perf_counter() - started
        print(f"[{status}] {name:<22} {elapsed:6.2f}s  {detail}")


async def check_llm(settings: Settings, report: Report) -> None:
    llm = LLMService(settings)
    thinking = effective_thinking(settings)
    print(f"\nLLM  {llm.info.model} @ {llm.info.details['host']} (thinking={thinking})")

    async def plain() -> str:
        reply = await llm.ainvoke([HumanMessage("Reply with one short sentence about the sea.")])
        text = message_text(reply).strip()
        if "<think>" in text:
            raise AssertionError("reply contains thinking text")
        usage = reply.usage_metadata or {}
        tokens = f"{usage.get('input_tokens')}/{usage.get('output_tokens')}"
        return f"{text[:70]!r} tokens in/out={tokens}"

    async def first_token() -> str:
        started = time.perf_counter()
        count = 0
        first = 0.0
        async for _ in llm.astream([SystemMessage("Be brief."), HumanMessage("Count to five.")]):
            if count == 0:
                first = time.perf_counter() - started
            count += 1
        return f"time to first token {first * 1000:.0f} ms, {count} chunks"

    async def tool_call() -> str:
        reply = await llm.ainvoke(
            [HumanMessage("What is the weather in Cairo right now?")], tools=[get_weather]
        )
        if not reply.tool_calls:
            raise AssertionError(f"no tool call, got {message_text(reply)[:60]!r}")
        call = reply.tool_calls[0]
        return f"{call['name']}({call['args']})"

    await report.run("llm reply", plain)
    await report.run("llm first token", first_token)
    await report.run("llm tool call", tool_call)
    await llm.aclose()


async def check_embeddings(settings: Settings, report: Report) -> None:
    service = EmbeddingService(settings)
    print(f"\nEMB  {service.info.model} @ {service.info.details['host']}")
    passages = [
        "The free trial lasts 21 days and needs no credit card.",
        "Call recordings are deleted automatically after 90 days.",
    ]

    async def ranking() -> str:
        if not service.configured:
            raise AssertionError("EMBEDDING_API_KEY is not set")
        dimension = await service.dimension()
        vectors = await service.aembed_documents(passages)
        query = await service.aembed_query("How long is the free trial?")
        scores = [sum(a * b for a, b in zip(query, vector, strict=True)) for vector in vectors]
        norms = [sum(v * v for v in vector) ** 0.5 for vector in vectors]
        query_norm = sum(v * v for v in query) ** 0.5
        cosine = [s / (n * query_norm) for s, n in zip(scores, norms, strict=True)]
        if cosine[0] <= cosine[1]:
            raise AssertionError(f"wrong passage ranked first: {cosine}")
        return f"{dimension} dimensions, cosine match {cosine[0]:.2f} vs other {cosine[1]:.2f}"

    await report.run("embedding ranking", ranking)
    await service.aclose()


async def check_speech(settings: Settings, report: Report, text: str) -> None:
    tts_model = TextToSpeech(settings)
    stt_model = SpeechToText(settings)
    print(f"\nTTS  {tts_model.info.provider}/{tts_model.info.model} {tts_model.info.details}")
    print(f"STT  {stt_model.info.provider}/{stt_model.info.model} {stt_model.info.details}")
    frames: list = []

    async def synthesize() -> str:
        plugin = tts_model.build()
        started = time.perf_counter()
        first = 0.0
        try:
            async with plugin.synthesize(text) as stream:
                async for event in stream:
                    if not frames:
                        first = time.perf_counter() - started
                    frames.append(event.frame)
        finally:
            await plugin.aclose()
        if not frames:
            raise AssertionError("the server returned no audio")
        seconds = sum(frame.duration for frame in frames)
        return f"first audio {first * 1000:.0f} ms, {seconds:.1f}s of audio, {len(frames)} frames"

    async def transcribe() -> str:
        if not frames:
            raise AssertionError("skipped: no audio from the TTS check")
        plugin = stt_model.build()
        try:
            event = await plugin.recognize(frames)
        finally:
            await plugin.aclose()
        heard = event.alternatives[0].text.strip()
        ratio = difflib.SequenceMatcher(None, normalize(text), normalize(heard)).ratio()
        if ratio < SIMILARITY_PASS:
            raise AssertionError(f"similarity {ratio:.2f} (heard {heard!r})")
        return f"similarity {ratio:.2f}, heard {heard!r}"

    await report.run("tts synthesize", synthesize)
    await report.run("stt round trip", transcribe)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--text", help="sentence for the TTS to STT round trip")
    parser.add_argument("--skip", nargs="*", choices=["llm", "embeddings", "speech"], default=[])
    args = parser.parse_args()

    settings = get_settings()
    text = args.text or (TEXT_ARABIC if settings.STT_LANGUAGE == "ar" else TEXT_ENGLISH)
    report = Report()
    if "llm" not in args.skip:
        await check_llm(settings, report)
    if "embeddings" not in args.skip:
        await check_embeddings(settings, report)
    if "speech" not in args.skip:
        await check_speech(settings, report, text)
    print("\nSome checks failed." if report.failed else "\nAll checks passed.")
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
