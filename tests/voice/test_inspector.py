"""Inspector: session and graph activity become ordered trace events on the data channel."""

import asyncio
import json
import time
from types import SimpleNamespace

import pytest
from livekit.agents import llm
from livekit.agents.llm import ChatMessage
from livekit.agents.voice import events
from livekit.agents.voice.events import CloseReason

from src.ai_models.base import ModelInfo
from src.ai_models.tracing import Tracing
from src.utils.trace_events import TRACE_TOPIC, TraceEvent
from src.voice.inspector import MAX_PACKET_BYTES, Inspector

MODELS = [
    ModelInfo("llm", "openai-compatible", "gemini-3-flash-preview", {"host": "example.test"}),
    ModelInfo("stt", "elevenlabs", "scribe_v2_realtime", {}),
]
USER_METRICS = {"transcription_delay": 0.12, "end_of_turn_delay": 0.5}
METRICS = {
    "llm_node_ttft": 0.4,
    "tts_node_ttfb": 0.2,
    "e2e_latency": 1.3,
    "playback_latency": 0.05,
}


class FakeParticipant:
    def __init__(self) -> None:
        self.packets: list[tuple[dict, bool, str]] = []
        self.fail_next = 0

    async def publish_data(self, payload: bytes, *, reliable: bool = True, topic: str = "") -> None:
        if self.fail_next:
            self.fail_next -= 1
            raise RuntimeError("data channel closed")
        self.packets.append((json.loads(payload.decode()), reliable, topic))


class FakeRoom:
    name = "room-1"

    def __init__(self) -> None:
        self.local_participant = FakeParticipant()


class FakeSession:
    def __init__(self) -> None:
        self.handlers: dict[str, object] = {}

    def on(self, name: str, callback=None):
        self.handlers[name] = callback
        return callback

    def fire(self, name: str, event: object) -> None:
        self.handlers[name](event)


@pytest.fixture
def room() -> FakeRoom:
    return FakeRoom()


@pytest.fixture
def session() -> FakeSession:
    return FakeSession()


@pytest.fixture
async def inspector(room, session, settings):
    instance = Inspector(room, settings, Tracing(settings), MODELS)
    instance.attach(session)
    instance.start()
    yield instance
    await instance.aclose()


async def published(inspector: Inspector, room: FakeRoom) -> list[dict]:
    await inspector.aclose()
    return [packet for packet, _, _ in room.local_participant.packets]


def kinds(packets: list[dict]) -> list[str]:
    return [f"{p['source']}.{p['type']}" for p in packets]


async def test_announces_the_session_and_its_models(inspector, room):
    packets = await published(inspector, room)
    assert kinds(packets) == ["session.connected"]
    data = packets[0]["data"]
    assert data["room"] == "room-1"
    assert data["models"]["llm"] == {
        "provider": "openai-compatible",
        "model": "gemini-3-flash-preview",
        "host": "example.test",
    }
    assert room.local_participant.packets[0][1:] == (True, TRACE_TOPIC)
    assert packets[0]["v"] == 1


async def test_user_speech_opens_a_turn_that_ends_when_the_agent_stops_talking(
    inspector, session, room
):
    fire = session.fire
    fire(
        "user_state_changed",
        events.UserStateChangedEvent(old_state="listening", new_state="speaking"),
    )
    fire(
        "user_state_changed",
        events.UserStateChangedEvent(old_state="speaking", new_state="listening"),
    )
    fire(
        "user_state_changed",
        events.UserStateChangedEvent(old_state="listening", new_state="speaking"),
    )
    assert inspector.turn == 1  # a pause inside one question is still the same turn
    fire(
        "agent_state_changed",
        events.AgentStateChangedEvent(old_state="thinking", new_state="speaking"),
    )
    fire(
        "agent_state_changed",
        events.AgentStateChangedEvent(old_state="speaking", new_state="listening"),
    )
    fire(
        "user_state_changed",
        events.UserStateChangedEvent(old_state="listening", new_state="speaking"),
    )
    assert inspector.turn == 2

    packets = await published(inspector, room)
    vad = [p for p in packets if p["source"] == "vad"]
    assert [(p["turn"], p["data"]["state"]) for p in vad] == [
        (1, "speaking"),
        (1, "listening"),
        (1, "speaking"),
        (2, "speaking"),
    ]
    states = [p["data"]["state"] for p in packets if p["type"] == "agent_state"]
    assert states == ["speaking", "listening"]


async def test_transcripts_are_reported_as_interim_and_final_and_truncated(
    make_settings, room, session
):
    settings = make_settings(INSPECTOR_MAX_FIELD_CHARS=50)
    inspector = Inspector(room, settings, Tracing(settings), MODELS)
    inspector.attach(session)
    inspector.start()
    session.fire(
        "user_input_transcribed", events.UserInputTranscribedEvent(transcript="hel", is_final=False)
    )
    session.fire(
        "user_input_transcribed",
        events.UserInputTranscribedEvent(transcript="hello " * 40, is_final=True, language="en"),
    )
    packets = [p for p in await published(inspector, room) if p["source"] == "stt"]
    assert [p["type"] for p in packets] == ["interim", "final"]
    assert packets[0]["data"] == {"text": "hel"}
    assert len(packets[1]["data"]["text"]) == 50 and packets[1]["data"]["language"] == "en"


async def test_a_turn_reports_eot_from_the_user_message_and_the_summary_from_the_reply(
    inspector, session, room
):
    user = ChatMessage(role="user", content=["Capital of France?"], metrics=USER_METRICS)
    reply = ChatMessage(role="assistant", content=["It is Paris."], metrics=METRICS)
    session.fire("conversation_item_added", events.ConversationItemAddedEvent(item=user))
    session.fire("conversation_item_added", events.ConversationItemAddedEvent(item=reply))
    packets = await published(inspector, room)
    assert kinds(packets)[1:] == [
        "session.message",
        "eot.detected",
        "session.message",
        "tts.first_audio",
        "latency.turn_summary",
    ]
    by_type = {p["type"]: p for p in packets}
    assert by_type["detected"]["data"] == {"delay_ms": 500.0, "transcript_delay_ms": 120.0}
    assert by_type["detected"]["duration_ms"] == 500.0
    assert by_type["first_audio"]["data"] == {"ttfb_ms": 200.0}
    assert by_type["turn_summary"]["data"] == {
        "eot_ms": 500.0,
        "llm_ttft_ms": 400.0,
        "tts_ttfb_ms": 200.0,
        "total_ms": 1300.0,
        "playback_ms": 50.0,
    }
    assert by_type["turn_summary"]["duration_ms"] == 1300.0


async def test_the_eot_figure_is_used_for_one_reply_only(inspector, session, room):
    user = ChatMessage(role="user", content=["Hi"], metrics=USER_METRICS)
    session.fire("conversation_item_added", events.ConversationItemAddedEvent(item=user))
    for text in ("First.", "Second."):
        reply = ChatMessage(role="assistant", content=[text], metrics=METRICS)
        session.fire("conversation_item_added", events.ConversationItemAddedEvent(item=reply))
    summaries = [p for p in await published(inspector, room) if p["type"] == "turn_summary"]
    assert [p["data"]["eot_ms"] for p in summaries] == [500.0, None]


async def test_messages_without_metrics_or_text_add_no_latency_events(inspector, session, room):
    session.fire(
        "conversation_item_added",
        events.ConversationItemAddedEvent(item=ChatMessage(role="user", content=["hello"])),
    )
    session.fire(
        "conversation_item_added",
        events.ConversationItemAddedEvent(item=ChatMessage(role="assistant", content=[])),
    )
    assert kinds(await published(inspector, room)) == ["session.connected", "session.message"]


async def test_unmeasured_latencies_are_null_not_negative(inspector, session, room):
    item = ChatMessage(
        role="assistant", content=["Hi."], metrics={"e2e_latency": 0.9, "llm_node_ttft": -1}
    )
    session.fire("conversation_item_added", events.ConversationItemAddedEvent(item=item))
    summary = next(p for p in await published(inspector, room) if p["type"] == "turn_summary")
    assert summary["data"]["llm_ttft_ms"] is None and summary["data"]["total_ms"] == 900.0


async def test_errors_and_close_are_reported(inspector, session, room):
    error = llm.LLMError(
        timestamp=time.time(), label="x", error=Exception("boom key"), recoverable=False
    )
    session.fire("error", events.ErrorEvent(error=error, source=SimpleNamespace()))
    session.fire("close", events.CloseEvent(error=None, reason=CloseReason.ERROR))
    session.fire("agent_false_interruption", events.AgentFalseInterruptionEvent(resumed=True))
    packets = await published(inspector, room)
    error_event = next(p for p in packets if p["source"] == "error")
    assert error_event["data"]["recoverable"] is False and "boom" in error_event["data"]["message"]
    closed = next(p for p in packets if p["type"] == "closed")
    assert "ERROR" in closed["data"]["reason"]
    assert "vad.false_interruption" in kinds(packets)


async def test_events_are_published_in_the_order_they_were_emitted(inspector, room):
    for index in range(30):
        inspector.emit(TraceEvent("graph", "node_start", f"n{index}", {"i": index}))
    packets = await published(inspector, room)
    assert [p["data"]["i"] for p in packets if p["type"] == "node_start"] == list(range(30))


async def test_a_failed_publish_is_logged_and_later_events_still_flow(inspector, room):
    room.local_participant.fail_next = 1
    inspector.emit(TraceEvent("graph", "node_start", "lost", {"i": 0}))
    inspector.emit(TraceEvent("graph", "node_start", "kept", {"i": 1}))
    packets = await published(inspector, room)
    assert [p["data"]["i"] for p in packets if p["type"] == "node_start"] == [1]


async def test_disabled_inspector_publishes_nothing(make_settings, room, session):
    settings = make_settings(INSPECTOR_ENABLED=False)
    inspector = Inspector(room, settings, Tracing(settings), MODELS)
    inspector.attach(session)
    inspector.start()
    session.fire(
        "user_state_changed",
        events.UserStateChangedEvent(old_state="listening", new_state="speaking"),
    )
    await inspector.aclose()
    await asyncio.sleep(0)
    assert room.local_participant.packets == []


async def test_oversized_events_are_slimmed_to_fit_one_packet(inspector, room):
    inspector.emit(
        TraceEvent("tool", "end", "huge", {"result_preview": "x" * (MAX_PACKET_BYTES + 100)})
    )
    packets = await published(inspector, room)
    huge = next(p for p in packets if p["label"] == "huge")
    assert huge["data"] == {"truncated": True}


async def test_graph_handler_events_carry_the_current_turn(inspector, session, room):
    session.fire(
        "user_state_changed",
        events.UserStateChangedEvent(old_state="listening", new_state="speaking"),
    )
    handler = inspector.graph_handler()
    await handler.on_tool_end("result text", run_id=__import__("uuid").uuid4())
    packets = await published(inspector, room)
    tool_event = next(p for p in packets if p["source"] == "tool")
    assert tool_event["turn"] == 1


async def test_greeting_without_a_user_turn_reports_audio_start_but_no_latency_summary(
    inspector, session, room
):
    item = ChatMessage(role="assistant", content=["Hello."], metrics={"tts_node_ttfb": 0.7})
    session.fire("conversation_item_added", events.ConversationItemAddedEvent(item=item))
    packets = await published(inspector, room)
    assert kinds(packets)[1:] == ["session.message", "tts.first_audio"]
