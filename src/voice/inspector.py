"""Inspector: turns session and graph activity into trace events and publishes them to the room."""

import asyncio
import json
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from livekit import rtc
from livekit.agents import AgentSession
from livekit.agents.voice import events

from config.logger import get_logger
from config.settings import Settings
from src.ai_models.base import ModelInfo
from src.ai_models.tracing import Tracing
from src.graph.trace import TraceCallbackHandler
from src.utils.text import truncate
from src.utils.trace_events import TRACE_TOPIC, TraceEvent

logger = get_logger(__name__)

# Reliable data packets are limited to about 15 KiB; stay below that.
MAX_PACKET_BYTES = 14_000
SECONDS_TO_MS = 1000.0
ASSISTANT_ROLE = "assistant"
USER_ROLE = "user"
TURN_RUN_NAME = "voice.turn"
_STOP = object()


def _ms(seconds: float | None) -> float | None:
    """Seconds to rounded milliseconds; ``None`` and negative (unmeasured) values stay ``None``."""
    if seconds is None or seconds < 0:
        return None
    return round(seconds * SECONDS_TO_MS, 1)


class Inspector:
    """Publishes ordered ``TraceEvent``s on the ``omnivox.trace`` data topic of the room."""

    def __init__(
        self,
        room: rtc.Room,
        settings: Settings,
        tracing: Tracing,
        models: list[ModelInfo],
    ) -> None:
        self._room = room
        self._settings = settings
        self._tracing = tracing
        self._models = models
        self._queue: asyncio.Queue[Any] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._turn = 0
        self._turn_open = False
        self._pending_eot: tuple[float | None, float | None] = (None, None)

    @property
    def turn(self) -> int:
        """Number of the current turn (0 before the user first speaks)."""
        return self._turn

    def start(self) -> None:
        """Begin publishing and announce the session and its models."""
        if self._settings.INSPECTOR_ENABLED and self._task is None:
            self._task = asyncio.create_task(self._publish_loop(), name="inspector-publisher")
        self.emit(
            TraceEvent(
                "session",
                "connected",
                "Agent joined the room",
                {
                    "room": self._room.name,
                    "models": {
                        m.kind: {"provider": m.provider, "model": m.model, **m.details}
                        for m in self._models
                    },
                },
            )
        )

    async def aclose(self) -> None:
        """Flush queued events and stop the publisher."""
        if self._task is None:
            return
        self._queue.put_nowait(_STOP)
        try:
            await asyncio.wait_for(self._task, timeout=5)
        except asyncio.TimeoutError:
            self._task.cancel()
        self._task = None

    def graph_handler(self) -> TraceCallbackHandler:
        """Callback handler that reports graph nodes, routing, tools and LLM calls."""
        return TraceCallbackHandler(
            self.emit,
            turn=lambda: self._turn,
            max_chars=self._settings.INSPECTOR_MAX_FIELD_CHARS,
        )

    def emit(self, event: TraceEvent) -> None:
        """Queue an event for publishing. Never blocks and never raises."""
        event.turn = event.turn or self._turn
        logger.debug("trace %s.%s turn=%d", event.source, event.type, event.turn)
        if self._task is not None:
            self._queue.put_nowait(event)

    def attach(self, session: AgentSession) -> None:
        """Subscribe to every session event the inspector reports."""
        session.on("user_state_changed", self._on_user_state)
        session.on("agent_state_changed", self._on_agent_state)
        session.on("user_input_transcribed", self._on_transcript)
        session.on("conversation_item_added", self._on_item)
        session.on("agent_false_interruption", self._on_false_interruption)
        session.on("error", self._on_error)
        session.on("close", self._on_close)

    # --- session events ---

    def _on_user_state(self, event: events.UserStateChangedEvent) -> None:
        if event.new_state == "speaking" and not self._turn_open:
            self._turn += 1
            self._turn_open = True
        self.emit(
            TraceEvent(
                "vad",
                "user_state",
                f"User {event.new_state}",
                {"state": event.new_state, "previous": event.old_state},
            )
        )

    def _on_agent_state(self, event: events.AgentStateChangedEvent) -> None:
        if event.old_state == "speaking" and event.new_state in ("listening", "idle"):
            self._turn_open = False
        self.emit(
            TraceEvent(
                "session",
                "agent_state",
                f"Agent {event.new_state}",
                {"state": event.new_state, "previous": event.old_state},
            )
        )

    def _on_transcript(self, event: events.UserInputTranscribedEvent) -> None:
        data: dict[str, Any] = {
            "text": truncate(event.transcript, self._settings.INSPECTOR_MAX_FIELD_CHARS)
        }
        if event.is_final and event.language:
            data["language"] = str(event.language)
        self.emit(
            TraceEvent(
                "stt",
                "final" if event.is_final else "interim",
                "Transcript" if event.is_final else "Partial transcript",
                data,
            )
        )

    def _on_item(self, event: events.ConversationItemAddedEvent) -> None:
        item = event.item
        text = getattr(item, "text_content", None)
        if getattr(item, "type", None) != "message" or not text:
            return
        self.emit(
            TraceEvent(
                "session",
                "message",
                f"{item.role} message",
                {
                    "role": item.role,
                    "text": truncate(text, self._settings.INSPECTOR_MAX_FIELD_CHARS),
                },
            )
        )
        metrics = getattr(item, "metrics", None)
        if item.role == USER_ROLE and metrics:
            self._user_metrics(metrics)
        elif item.role == ASSISTANT_ROLE and metrics:
            self._turn_metrics(metrics)

    def _on_false_interruption(self, event: events.AgentFalseInterruptionEvent) -> None:
        self.emit(TraceEvent("vad", "false_interruption", "False interruption, resuming", {}))

    def _on_error(self, event: events.ErrorEvent) -> None:
        error = event.error
        self.emit(
            TraceEvent(
                "error",
                "error",
                f"{type(event.source).__name__} error",
                {
                    "message": truncate(str(error), self._settings.INSPECTOR_MAX_FIELD_CHARS),
                    "source": type(event.source).__name__,
                    "recoverable": getattr(error, "recoverable", None),
                },
            )
        )

    def _on_close(self, event: events.CloseEvent) -> None:
        self.emit(TraceEvent("session", "closed", "Session closed", {"reason": str(event.reason)}))

    # --- per-turn latency ---

    def _user_metrics(self, metrics: Mapping[str, Any]) -> None:
        """Report how long the end-of-turn model waited after the user stopped talking."""
        eot = _ms(metrics.get("end_of_turn_delay"))
        transcription = _ms(metrics.get("transcription_delay"))
        self._pending_eot = (eot, transcription)
        if eot is not None:
            self.emit(
                TraceEvent(
                    "eot",
                    "detected",
                    "End of turn",
                    {"delay_ms": eot, "transcript_delay_ms": transcription},
                    duration_ms=eot,
                )
            )

    def _turn_metrics(self, metrics: Mapping[str, Any]) -> None:
        """Report the TTS and total latency LiveKit measured for the reply."""
        eot, _ = self._pending_eot
        self._pending_eot = (None, None)
        ttft = _ms(metrics.get("llm_node_ttft"))
        ttfb = _ms(metrics.get("tts_node_ttfb"))
        total = _ms(metrics.get("e2e_latency"))
        if ttfb is not None:
            self.emit(
                TraceEvent("tts", "first_audio", "First audio", {"ttfb_ms": ttfb}, duration_ms=ttfb)
            )
        if eot is None and total is None:
            return  # no user turn behind this reply (the greeting), nothing to summarize
        summary = {
            "eot_ms": eot,
            "llm_ttft_ms": ttft,
            "tts_ttfb_ms": ttfb,
            "total_ms": total,
            "playback_ms": _ms(metrics.get("playback_latency")),
        }
        self.emit(TraceEvent("latency", "turn_summary", "Turn latency", summary, duration_ms=total))
        self._record_turn(summary, total)

    def _record_turn(self, summary: dict[str, float | None], total_ms: float | None) -> None:
        """Mirror the turn into LangSmith, so STT, LLM and TTS latency is traced there too."""
        started = datetime.now(timezone.utc) - timedelta(milliseconds=total_ms or 0)
        self._tracing.record_run(
            TURN_RUN_NAME,
            run_type="chain",
            inputs={"turn": self._turn},
            outputs=summary,
            started_at=started,
            metadata={"room": self._room.name},
        )

    # --- publishing ---

    async def _publish_loop(self) -> None:
        while (item := await self._queue.get()) is not _STOP:
            payload = self._encode(item)
            try:
                await self._room.local_participant.publish_data(
                    payload, reliable=True, topic=TRACE_TOPIC
                )
            except Exception as exc:
                logger.warning("Inspector publish failed: %s: %s", type(exc).__name__, exc)

    @staticmethod
    def _encode(event: TraceEvent) -> bytes:
        payload = json.dumps(event.to_dict(), ensure_ascii=False).encode()
        if len(payload) > MAX_PACKET_BYTES:
            slim = TraceEvent(
                event.source,
                event.type,
                event.label,
                {"truncated": True},
                event.duration_ms,
                event.turn,
                event.ts,
                event.id,
            )
            payload = json.dumps(slim.to_dict()).encode()
        return payload
