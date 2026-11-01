"""STT, TTS, VAD and turn detection factories: provider switch, configuration errors, options."""

import pytest
from livekit.agents import inference
from livekit.plugins import elevenlabs, openai

from src.ai_models.asr import PLACEHOLDER_API_KEY, SpeechToText
from src.ai_models.tts import TextToSpeech
from src.ai_models.turn import TurnDetection
from src.ai_models.vad import VoiceActivityDetector
from src.utils.exceptions import ConfigurationError


def test_stt_elevenlabs_is_the_default_and_streams(settings):
    plugin = SpeechToText(settings).build()
    assert isinstance(plugin, elevenlabs.STT)
    assert plugin.model == "scribe_v2_realtime"
    assert plugin.capabilities.streaming is True


def test_stt_openai_format_uses_any_compatible_server(make_settings):
    settings = make_settings(
        STT_PROVIDER="openai",
        STT_BASE_URL="http://localhost:8001/v1",
        STT_MODEL="openai/whisper-large-v3",
        STT_LANGUAGE="ar",
    )
    plugin = SpeechToText(settings).build()
    assert isinstance(plugin, openai.STT)
    assert plugin.model == "openai/whisper-large-v3"
    assert SpeechToText(settings).info.details["host"] == "localhost:8001"


def test_stt_openai_without_a_key_uses_the_placeholder_for_self_hosted_servers(make_settings):
    settings = make_settings(STT_PROVIDER="openai", STT_BASE_URL="http://localhost:8001/v1")
    assert settings.STT_API_KEY is None
    SpeechToText(settings).build()
    assert PLACEHOLDER_API_KEY == "EMPTY"


@pytest.mark.parametrize(
    "overrides",
    [
        {"ELEVENLABS_API_KEY": None},
        {"STT_PROVIDER": "openai"},
    ],
)
def test_stt_incomplete_configuration(make_settings, overrides):
    with pytest.raises(ConfigurationError):
        SpeechToText(make_settings(**overrides)).build()


def test_tts_elevenlabs_is_the_default(settings):
    plugin = TextToSpeech(settings).build()
    assert isinstance(plugin, elevenlabs.TTS)
    assert plugin.model == "eleven_v4_turbo"
    assert TextToSpeech(settings).info.details["voice"] == settings.TTS_VOICE


def test_tts_openai_format_uses_any_compatible_server(make_settings):
    settings = make_settings(
        TTS_PROVIDER="openai",
        TTS_BASE_URL="http://localhost:8002/v1",
        TTS_MODEL="kokoro",
        TTS_VOICE="af",
    )
    plugin = TextToSpeech(settings).build()
    assert isinstance(plugin, openai.TTS)
    assert plugin.model == "kokoro"


@pytest.mark.parametrize("overrides", [{"ELEVENLABS_API_KEY": None}, {"TTS_PROVIDER": "openai"}])
def test_tts_incomplete_configuration(make_settings, overrides):
    with pytest.raises(ConfigurationError):
        TextToSpeech(make_settings(**overrides)).build()


def test_speech_infos_carry_no_secrets(settings):
    text = f"{SpeechToText(settings).info} {TextToSpeech(settings).info}"
    assert "not-real" not in text


def test_vad_loads_locally_with_configured_thresholds(make_settings):
    settings = make_settings(VAD_ACTIVATION_THRESHOLD=0.6, VAD_MIN_SILENCE_DURATION=0.4)
    vad = VoiceActivityDetector(settings).load()
    assert vad.capabilities.update_interval > 0
    assert VoiceActivityDetector(settings).info.details["activation_threshold"] == 0.6


def test_turn_detection_audio_mode_uses_the_local_mini_model(settings):
    options = TurnDetection(settings).options()
    detector = options["turn_detection"]
    assert isinstance(detector, inference.TurnDetector)
    assert detector.model == "turn-detector-v1-mini"
    assert options["endpointing"] == {"mode": "fixed", "min_delay": 0.5, "max_delay": 3.0}
    assert options["interruption"] == {"enabled": True, "mode": "vad"}
    assert options["preemptive_generation"] == {"enabled": False}


@pytest.mark.parametrize("mode", ["vad", "stt"])
def test_turn_detection_simple_modes(make_settings, mode):
    options = TurnDetection(make_settings(TURN_DETECTOR=mode)).options()
    assert options["turn_detection"] == mode


def test_turn_detection_follows_interruption_and_delay_settings(make_settings):
    settings = make_settings(
        ALLOW_INTERRUPTIONS=False,
        MIN_ENDPOINTING_DELAY=0.2,
        MAX_ENDPOINTING_DELAY=1.5,
        PREEMPTIVE_GENERATION=True,
    )
    options = TurnDetection(settings).options()
    assert options["interruption"]["enabled"] is False
    assert options["endpointing"]["min_delay"] == 0.2
    assert options["endpointing"]["max_delay"] == 1.5
    assert options["preemptive_generation"]["enabled"] is True
