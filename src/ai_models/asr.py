"""Speech-to-text: native ElevenLabs streaming, or any OpenAI-compatible transcription server."""

from urllib.parse import urlparse

from livekit.agents import stt
from livekit.agents.types import NOT_GIVEN
from livekit.plugins import elevenlabs, openai

from config.settings import Settings
from src.ai_models.base import PLACEHOLDER_API_KEY, AIModel, ModelInfo
from src.utils.exceptions import ConfigurationError


class SpeechToText(AIModel):
    """Builds the LiveKit STT plugin selected by ``STT_PROVIDER``."""

    kind = "stt"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def info(self) -> ModelInfo:
        settings = self._settings
        details: dict[str, str | None] = {"language": settings.STT_LANGUAGE}
        if settings.STT_BASE_URL:
            details["host"] = urlparse(settings.STT_BASE_URL).netloc
        return ModelInfo(self.kind, settings.STT_PROVIDER, settings.STT_MODEL, details)

    def build(self) -> stt.STT:
        """Create the STT plugin; raises ``ConfigurationError`` when its settings are incomplete."""
        settings = self._settings
        if settings.STT_PROVIDER == "elevenlabs":
            if settings.ELEVENLABS_API_KEY is None:
                raise ConfigurationError(
                    "ELEVENLABS_API_KEY is required for STT_PROVIDER=elevenlabs."
                )
            return elevenlabs.STT(
                model=settings.STT_MODEL,
                api_key=settings.ELEVENLABS_API_KEY.get_secret_value(),
                language_code=settings.STT_LANGUAGE or NOT_GIVEN,
            )
        if not settings.STT_BASE_URL:
            raise ConfigurationError("STT_BASE_URL is required for STT_PROVIDER=openai.")
        key = (
            settings.STT_API_KEY.get_secret_value() if settings.STT_API_KEY else PLACEHOLDER_API_KEY
        )
        return openai.STT(
            model=settings.STT_MODEL,
            base_url=settings.STT_BASE_URL,
            api_key=key,
            language=settings.STT_LANGUAGE or "en",
            detect_language=not settings.STT_LANGUAGE,
            prompt=settings.STT_PROMPT or NOT_GIVEN,
            temperature=NOT_GIVEN if settings.STT_TEMPERATURE is None else settings.STT_TEMPERATURE,
        )
