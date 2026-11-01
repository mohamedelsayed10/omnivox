"""Typed inspector events: what the agent did internally, in the shape the GUI consumes."""

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

TRACE_TOPIC = "omnivox.trace"
TRACE_VERSION = 1

TraceSource = Literal[
    "session", "vad", "stt", "eot", "graph", "tool", "llm", "tts", "latency", "error"
]


@dataclass
class TraceEvent:
    """One inspector event. ``to_dict`` is the wire format sent over the LiveKit data channel."""

    source: TraceSource
    type: str
    label: str
    data: dict[str, Any] = field(default_factory=dict)
    duration_ms: float | None = None
    turn: int = 0
    ts: int = field(default_factory=lambda: int(time.time() * 1000))
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def to_dict(self) -> dict[str, Any]:
        """Wire representation (``v`` is the schema version)."""
        payload: dict[str, Any] = {
            "v": TRACE_VERSION,
            "id": self.id,
            "ts": self.ts,
            "turn": self.turn,
            "source": self.source,
            "type": self.type,
            "label": self.label,
            "data": self.data,
        }
        if self.duration_ms is not None:
            payload["duration_ms"] = round(self.duration_ms, 1)
        return payload
