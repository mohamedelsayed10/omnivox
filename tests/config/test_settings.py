"""Settings: parity with .env.example, defaults, validation and secret handling."""

import re

import pytest
from pydantic import ValidationError

from config.settings import Settings
from tests.conftest import ROOT

ENV_LINE = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")


def env_example_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if match := ENV_LINE.match(line):
            values[match.group(1)] = match.group(2)
    return values


def test_env_example_and_settings_fields_match_both_ways():
    example = set(env_example_values())
    fields = set(Settings.model_fields)
    assert fields - example == set(), "Settings fields missing from .env.example"
    assert example - fields == set(), ".env.example keys that Settings does not read"


def test_env_example_is_portable_across_pydantic_compose_and_systemd():
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        assert ENV_LINE.match(line), f"not a plain KEY=VALUE line: {line}"
        assert not line.startswith("export "), line
        value = line.partition("=")[2]
        assert not value.startswith(("'", '"')), f"quoted value: {line}"
        assert " #" not in value, f"inline comment: {line}"


def test_env_example_loads_with_only_secrets_added(tmp_path, monkeypatch):
    for key in env_example_values():
        monkeypatch.delenv(key, raising=False)
    path = tmp_path / ".env"
    path.write_text(
        (ROOT / ".env.example")
        .read_text(encoding="utf-8")
        .replace("OPENAI_API_KEY=", "OPENAI_API_KEY=test-key-1234567890"),
        encoding="utf-8",
    )
    loaded = Settings(_env_file=path)
    assert loaded.OPENAI_MODEL == "gemini-3-flash-preview"
    assert loaded.OPENAI_BASE_URL.startswith("https://generativelanguage.googleapis.com")
    assert loaded.EMBEDDING_MODEL == "embed-v5.0-fast"
    assert loaded.TTS_MODEL == "eleven_v4_turbo"
    assert loaded.STT_MODEL == "scribe_v2_realtime"
    assert loaded.OPENAI_MAX_TOKENS is None  # blank means unset
    assert loaded.API_KEYS.get_secret_value() == ""


def test_defaults(settings):
    assert settings.PORT == 8100
    assert settings.API_PREFIX == "/api/v1"
    assert settings.TURN_DETECTOR == "audio"
    assert settings.auth_required is False
    assert settings.cors_origins_list == ["http://localhost:5173"]


def test_api_keys_and_cors_are_split_on_commas(make_settings):
    custom = make_settings(
        API_KEYS="alpha-key-12345, beta-key-67890 ,", CORS_ORIGINS="http://a.test, http://b.test"
    )
    assert custom.api_keys_list == ["alpha-key-12345", "beta-key-67890"]
    assert custom.auth_required is True
    assert custom.cors_origins_list == ["http://a.test", "http://b.test"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"PORT": 0},
        {"OPENAI_TEMPERATURE": 3.5},
        {"STT_PROVIDER": "whisper"},
        {"LOG_FORMAT": "xml"},
        {"APP_ENV": "staging"},
        {"API_PREFIX": "api"},
        {"ROOT_PATH": "omnivox"},
        {"RAG_CHUNK_SIZE": 200, "RAG_CHUNK_OVERLAP": 200},
        {"MIN_ENDPOINTING_DELAY": 5.0, "MAX_ENDPOINTING_DELAY": 1.0},
        {"TRACING_PROVIDER": "langsmith"},
        {"TRACING_PROVIDER": "langfuse"},
    ],
)
def test_invalid_values_are_rejected(make_settings, overrides):
    with pytest.raises(ValidationError):
        make_settings(**overrides)


def test_missing_required_values_fail_fast_with_the_field_name(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LIVEKIT_API_SECRET", raising=False)
    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None)
    text = str(caught.value)
    assert "OPENAI_API_KEY" in text and "LIVEKIT_API_SECRET" in text


def test_blank_environment_values_mean_unset(monkeypatch):
    monkeypatch.setenv("OPENAI_MAX_TOKENS", "")
    monkeypatch.setenv("PORT", "")
    loaded = Settings(_env_file=None)
    assert loaded.OPENAI_MAX_TOKENS is None
    assert loaded.PORT == 8100


def test_secrets_never_appear_in_repr_or_dump(settings):
    assert settings.OPENAI_API_KEY.get_secret_value() not in repr(settings)
    assert settings.OPENAI_API_KEY.get_secret_value() not in str(settings.model_dump())
    assert "test-key-not-real-0123456789" in settings.secret_values()


def test_thinking_switch_accepts_true_false_and_blank(make_settings, monkeypatch):
    assert make_settings().OPENAI_ENABLE_THINKING is None
    assert make_settings(OPENAI_ENABLE_THINKING=False).OPENAI_ENABLE_THINKING is False
    monkeypatch.setenv("OPENAI_ENABLE_THINKING", "false")
    assert Settings(_env_file=None).OPENAI_ENABLE_THINKING is False
    monkeypatch.setenv("OPENAI_ENABLE_THINKING", "")
    assert Settings(_env_file=None).OPENAI_ENABLE_THINKING is None
