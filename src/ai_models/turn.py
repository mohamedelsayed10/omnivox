"""End-of-turn detection and turn handling options for the voice session."""

from livekit.agents import TurnHandlingOptions, inference

from config.settings import Settings
from src.ai_models.base import AIModel, ModelInfo

# The mini audio model runs locally; the full "v1" model needs LiveKit Inference credentials.
LOCAL_TURN_MODEL_VERSION = "v1-mini"


class TurnDetection(AIModel):
    """Chooses how the end of the user's turn is decided (``TURN_DETECTOR``)."""

    kind = "turn"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def info(self) -> ModelInfo:
        mode = self._settings.TURN_DETECTOR
        model = f"livekit-turn-detector-{LOCAL_TURN_MODEL_VERSION}" if mode == "audio" else mode
        return ModelInfo(
            kind=self.kind,
            provider="livekit" if mode == "audio" else mode,
            model=model,
            details={
                "min_endpointing_delay": self._settings.MIN_ENDPOINTING_DELAY,
                "max_endpointing_delay": self._settings.MAX_ENDPOINTING_DELAY,
            },
        )

    def options(self) -> TurnHandlingOptions:
        """Turn handling options for ``AgentSession``."""
        settings = self._settings
        detection = (
            inference.TurnDetector(version=LOCAL_TURN_MODEL_VERSION)
            if settings.TURN_DETECTOR == "audio"
            else settings.TURN_DETECTOR
        )
        return TurnHandlingOptions(
            turn_detection=detection,
            endpointing={
                "mode": "fixed",
                "min_delay": settings.MIN_ENDPOINTING_DELAY,
                "max_delay": settings.MAX_ENDPOINTING_DELAY,
            },
            interruption={"enabled": settings.ALLOW_INTERRUPTIONS, "mode": "vad"},
            preemptive_generation={"enabled": settings.PREEMPTIVE_GENERATION},
        )
