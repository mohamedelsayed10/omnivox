"""STT, TTS, VAD and turn detection factories: provider switch, configuration errors, options."""

import pytest
from livekit.agents import inference
from livekit.agents.types import NOT_GIVEN
from livekit.plugins import elevenlabs, openai
from openai import omit

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


@pytest.mark.parametrize(("configured", "expected"), [(None, "mp3"), ("pcm", "pcm")])
def test_tts_openai_format_passes_the_response_format(make_settings, configured, expected):
    settings = make_settings(
        TTS_PROVIDER="openai",
        TTS_BASE_URL="http://localhost:8002/v1",
        TTS_RESPONSE_FORMAT=configured,
    )
    plugin = TextToSpeech(settings).build()
    assert plugin._opts.response_format == expected


def test_tts_openai_format_passes_rate_speed_and_instructions(make_settings):
    settings = make_settings(
        TTS_PROVIDER="openai",
        TTS_BASE_URL="http://localhost:8002/v1",
        TTS_SAMPLE_RATE=22_050,
        TTS_SPEED=1.25,
        TTS_INSTRUCTIONS="Speak calmly.",
    )
    plugin = TextToSpeech(settings).build()
    assert plugin.sample_rate == 22_050
    assert plugin._opts.speed == 1.25
    assert plugin._opts.instructions == "Speak calmly."


def test_tts_openai_format_defaults_match_the_plugin(make_settings):
    plugin = TextToSpeech(
        make_settings(TTS_PROVIDER="openai", TTS_BASE_URL="http://localhost:8002/v1")
    ).build()
    assert (plugin.sample_rate, plugin._opts.speed, plugin._opts.instructions) == (
        24_000,
        1.0,
        None,
    )


def test_stt_openai_format_passes_prompt_and_temperature(make_settings):
    settings = make_settings(
        STT_PROVIDER="openai",
        STT_BASE_URL="http://localhost:8001/v1",
        STT_PROMPT="Names: Ahmed, Mona.",
        STT_TEMPERATURE=0.2,
    )
    opts = SpeechToText(settings).build()._opts
    assert opts.prompt == "Names: Ahmed, Mona."
    assert opts.temperature == 0.2


def test_stt_openai_format_leaves_prompt_and_temperature_unset_by_default(make_settings):
    settings = make_settings(STT_PROVIDER="openai", STT_BASE_URL="http://localhost:8001/v1")
    opts = SpeechToText(settings).build()._opts
    assert isinstance(opts.prompt, type(NOT_GIVEN)) and isinstance(
        opts.temperature, type(NOT_GIVEN)
    )


def test_tts_openai_format_can_omit_the_voice(make_settings):
    settings = make_settings(
        TTS_PROVIDER="openai", TTS_BASE_URL="http://localhost:8002/v1", TTS_VOICE="none"
    )
    assert TextToSpeech(settings).build()._opts.voice is omit
    named = make_settings(
        TTS_PROVIDER="openai", TTS_BASE_URL="http://localhost:8002/v1", TTS_VOICE="af"
    )
    assert TextToSpeech(named).build()._opts.voice == "af"


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
