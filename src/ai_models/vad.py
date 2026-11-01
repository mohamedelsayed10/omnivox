"""Voice activity detection (Silero, runs locally on CPU)."""

from livekit.agents import vad
from livekit.plugins import silero

from config.settings import Settings
from src.ai_models.base import AIModel, ModelInfo


class VoiceActivityDetector(AIModel):
    """Loads the Silero VAD model with the configured thresholds."""

    kind = "vad"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def info(self) -> ModelInfo:
        return ModelInfo(
            kind=self.kind,
            provider="silero",
            model="silero-vad",
            details={
                "activation_threshold": self._settings.VAD_ACTIVATION_THRESHOLD,
                "min_silence_duration": self._settings.VAD_MIN_SILENCE_DURATION,
            },
        )

    def load(self) -> vad.VAD:
        """Load the ONNX model. Blocking: call from process prewarm, not from the event loop."""
        return silero.VAD.load(
            activation_threshold=self._settings.VAD_ACTIVATION_THRESHOLD,
            min_speech_duration=self._settings.VAD_MIN_SPEECH_DURATION,
            min_silence_duration=self._settings.VAD_MIN_SILENCE_DURATION,
        )
