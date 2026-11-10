"""Text-to-speech: native ElevenLabs streaming, or any OpenAI-compatible speech server."""

from urllib.parse import urlparse

from livekit.agents import tts
from livekit.agents.types import NOT_GIVEN
from livekit.plugins import elevenlabs, openai
from openai import omit

from config.settings import Settings
from src.ai_models.base import PLACEHOLDER_API_KEY, AIModel, ModelInfo
from src.utils.exceptions import ConfigurationError

# TTS_VOICE value for OpenAI-format servers that have a default voice and reject any voice name.
NO_VOICE = "none"


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
        plugin = openai.TTS(
            model=settings.TTS_MODEL,
            voice=settings.TTS_VOICE,
            base_url=settings.TTS_BASE_URL,
            api_key=key,
            response_format=settings.TTS_RESPONSE_FORMAT or NOT_GIVEN,
            sample_rate=settings.TTS_SAMPLE_RATE,
            speed=settings.TTS_SPEED,
            instructions=settings.TTS_INSTRUCTIONS or NOT_GIVEN,
        )
        if settings.TTS_VOICE.lower() == NO_VOICE:
            # The plugin always sends a voice; the SDK drops an ``omit`` value from the request.
            plugin.update_options(voice=omit)
        return plugin
