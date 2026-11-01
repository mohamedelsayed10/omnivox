"""Text-to-speech: native ElevenLabs streaming, or any OpenAI-compatible speech server."""

from urllib.parse import urlparse

from livekit.agents import tts
from livekit.plugins import elevenlabs, openai

from config.settings import Settings
from src.ai_models.asr import PLACEHOLDER_API_KEY
from src.ai_models.base import AIModel, ModelInfo
from src.utils.exceptions import ConfigurationError


class TextToSpeech(AIModel):
    """Builds the LiveKit TTS plugin selected by ``TTS_PROVIDER``."""

    kind = "tts"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def info(self) -> ModelInfo:
        settings = self._settings
        details: dict[str, str | None] = {"voice": settings.TTS_VOICE}
        if settings.TTS_BASE_URL:
            details["host"] = urlparse(settings.TTS_BASE_URL).netloc
        return ModelInfo(self.kind, settings.TTS_PROVIDER, settings.TTS_MODEL, details)

    def build(self) -> tts.TTS:
        """Create the TTS plugin; raises ``ConfigurationError`` when its settings are incomplete."""
        settings = self._settings
        if settings.TTS_PROVIDER == "elevenlabs":
            if settings.ELEVENLABS_API_KEY is None:
                raise ConfigurationError(
                    "ELEVENLABS_API_KEY is required for TTS_PROVIDER=elevenlabs."
                )
            return elevenlabs.TTS(
                model=settings.TTS_MODEL,
                voice_id=settings.TTS_VOICE,
                api_key=settings.ELEVENLABS_API_KEY.get_secret_value(),
            )
        if not settings.TTS_BASE_URL:
            raise ConfigurationError("TTS_BASE_URL is required for TTS_PROVIDER=openai.")
        key = (
            settings.TTS_API_KEY.get_secret_value() if settings.TTS_API_KEY else PLACEHOLDER_API_KEY
        )
        return openai.TTS(
            model=settings.TTS_MODEL,
            voice=settings.TTS_VOICE,
            base_url=settings.TTS_BASE_URL,
            api_key=key,
        )
