"""Typed application settings, loaded from the environment and an optional ``.env`` file."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ReasoningEffort = Literal["minimal", "low", "medium", "high"]
MIN_SECRET_LENGTH = 6  # shorter values would mangle ordinary log text when masked

DEFAULT_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
DEFAULT_EMBEDDING_BASE_URL = "https://api.cohere.ai/compatibility/v1"
# A .env line cannot hold a newline, and the file parser trims trailing spaces.
ESCAPES = {"\\n": "\n", "\\t": "\t", "\\s": " "}


def same_url(left: str, right: str) -> bool:
    """True when two base URLs differ only by a trailing slash."""
    return left.rstrip("/") == right.rstrip("/")


class Settings(BaseSettings):
    """Every configurable value of the service. Field names equal environment variable names."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        case_sensitive=False,
    )

    # --- App ---
    APP_NAME: str = "omnivox"
    APP_ENV: Literal["development", "production"] = "development"
    HOST: str = "0.0.0.0"
    PORT: int = Field(default=8100, ge=1, le=65535)
    API_PREFIX: str = "/api/v1"
    ROOT_PATH: str = ""
    CORS_ORIGINS: str = "http://localhost:5173"
    API_KEYS: SecretStr = SecretStr("")
    RELOAD: bool = False
    MAX_BODY_BYTES: int = Field(default=12_582_912, ge=1024)
    MAX_CONCURRENT_RUNS: int = Field(default=8, ge=1)

    # --- LLM (any OpenAI-compatible endpoint) ---
    OPENAI_BASE_URL: str = DEFAULT_OPENAI_BASE_URL
    # Required for the default Gemini endpoint; optional for a self-hosted server (see validator).
    OPENAI_API_KEY: SecretStr = Field(default=SecretStr(""), validate_default=True)
    OPENAI_MODEL: str = "gemini-3-flash-preview"
    OPENAI_TEMPERATURE: float = Field(default=1.0, ge=0.0, le=2.0)
    OPENAI_MAX_TOKENS: int | None = Field(default=None, ge=1)
    OPENAI_REASONING_EFFORT: ReasoningEffort | None = None
    OPENAI_ENABLE_THINKING: bool | None = None
    OPENAI_THINKING_MODELS: str = "qwen,gemma"
    OPENAI_TOP_P: float | None = Field(default=None, gt=0.0, le=1.0)
    OPENAI_PRESENCE_PENALTY: float | None = Field(default=None, ge=-2.0, le=2.0)
    OPENAI_FREQUENCY_PENALTY: float | None = Field(default=None, ge=-2.0, le=2.0)
    OPENAI_SEED: int | None = None
    OPENAI_TOP_K: int | None = Field(default=None, ge=1)
    OPENAI_MIN_P: float | None = Field(default=None, ge=0.0, le=1.0)
    OPENAI_REPETITION_PENALTY: float | None = Field(default=None, gt=0.0)
    MAX_RETRIES: int = Field(default=3, ge=0)
    REQUEST_TIMEOUT: float = Field(default=60.0, gt=0)
    MAX_INPUT_CHARS: int = Field(default=20_000, ge=1)

    # --- Embeddings (OpenAI-compatible) ---
    EMBEDDING_BASE_URL: str = DEFAULT_EMBEDDING_BASE_URL
    EMBEDDING_MODEL: str = "embed-v5.0-fast"
    EMBEDDING_API_KEY: SecretStr | None = None
    EMBEDDING_BATCH_SIZE: int = Field(default=96, ge=1)
    EMBEDDING_CONCURRENCY: int = Field(default=4, ge=1)
    EMBEDDING_QUERY_PREFIX: str | None = None
    EMBEDDING_DOCUMENT_PREFIX: str | None = None
    EMBEDDING_DIMENSIONS: int | None = Field(default=None, ge=1)

    # --- Speech to text ---
    ELEVENLABS_API_KEY: SecretStr | None = None
    STT_PROVIDER: Literal["elevenlabs", "openai"] = "elevenlabs"
    STT_MODEL: str = "scribe_v2_realtime"
    STT_LANGUAGE: str | None = None
    STT_BASE_URL: str | None = None
    STT_API_KEY: SecretStr | None = None
    STT_PROMPT: str | None = None
    STT_TEMPERATURE: float | None = Field(default=None, ge=0.0, le=1.0)

    # --- Text to speech ---
    TTS_PROVIDER: Literal["elevenlabs", "openai"] = "elevenlabs"
    TTS_MODEL: str = "eleven_v4_turbo"
    TTS_VOICE: str = "EXAVITQu4vr4xnSDxMaL"
    TTS_BASE_URL: str | None = None
    TTS_API_KEY: SecretStr | None = None
    TTS_RESPONSE_FORMAT: str | None = None
    TTS_SAMPLE_RATE: int = Field(default=24_000, ge=8_000, le=192_000)
    TTS_SPEED: float = Field(default=1.0, ge=0.25, le=4.0)
    TTS_INSTRUCTIONS: str | None = None

    # --- Voice pipeline ---
    VAD_ACTIVATION_THRESHOLD: float = Field(default=0.5, ge=0.0, le=1.0)
    VAD_MIN_SPEECH_DURATION: float = Field(default=0.05, ge=0.0)
    VAD_MIN_SILENCE_DURATION: float = Field(default=0.55, ge=0.0)
    TURN_DETECTOR: Literal["audio", "vad", "stt"] = "audio"
    MIN_ENDPOINTING_DELAY: float = Field(default=0.5, ge=0.0)
    MAX_ENDPOINTING_DELAY: float = Field(default=3.0, ge=0.0)
    ALLOW_INTERRUPTIONS: bool = True
    PREEMPTIVE_GENERATION: bool = False
    AGENT_GREETING: str = "Hi, this is OmniVox. Ask me anything, or ask about your documents."
    INSPECTOR_ENABLED: bool = True
    INSPECTOR_MAX_FIELD_CHARS: int = Field(default=1500, ge=50)

    # --- LiveKit ---
    WORKER_IDLE_PROCESSES: int = Field(default=1, ge=0)
    WORKER_PORT: int = Field(default=8181, ge=0, le=65535)
    LIVEKIT_URL: str = "ws://localhost:7880"
    LIVEKIT_PUBLIC_URL: str = "ws://localhost:7880"
    LIVEKIT_API_KEY: str = "devkey"
    LIVEKIT_API_SECRET: SecretStr = Field(min_length=1)
    LIVEKIT_TOKEN_TTL_SECONDS: int = Field(default=3600, ge=60)

    # --- Knowledge base (Qdrant) ---
    QDRANT_URL: str = "http://localhost:6333/"
    QDRANT_API_KEY: SecretStr | None = None
    QDRANT_COLLECTION: str = "omnivox_knowledge"
    RAG_CHUNK_SIZE: int = Field(default=800, ge=100)
    RAG_CHUNK_OVERLAP: int = Field(default=100, ge=0)
    RAG_TOP_K: int = Field(default=4, ge=1)
    RAG_SCORE_THRESHOLD: float = 0.0
    RAG_MAX_UPLOAD_BYTES: int = Field(default=5_000_000, ge=1)

    # --- Web search (ddgs) ---
    WEB_SEARCH_MAX_RESULTS: int = Field(default=5, ge=1, le=20)
    WEB_SEARCH_TIMEOUT: float = Field(default=10.0, gt=0)
    WEB_SEARCH_REGION: str = "us-en"

    # --- Logging ---
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    LOG_FORMAT: Literal["console", "json"] = "console"
    LOG_DIR: str = "files/logs"
    LOG_MAX_BYTES: int = Field(default=10_485_760, ge=1024)
    LOG_BACKUP_COUNT: int = Field(default=5, ge=0)

    # --- Tracing ---
    TRACING_PROVIDER: Literal["none", "langsmith"] = "none"
    LANGSMITH_API_KEY: SecretStr | None = None
    LANGSMITH_PROJECT: str | None = None

    # --- Agent graph ---
    GRAPH_RECURSION_LIMIT: int = Field(default=25, ge=2)
    GRAPH_MEMORY_BACKEND: Literal["memory", "sqlite"] = "memory"
    GRAPH_MEMORY_URL: str = "files/graph_memory.sqlite"
    GRAPH_MAX_HISTORY_MESSAGES: int = Field(default=40, ge=2)
    GRAPH_MAX_HISTORY_CHARS: int | None = Field(default=None, ge=500)
    AGENT_INSTRUCTIONS: str | None = None

    @field_validator("OPENAI_API_KEY")
    @classmethod
    def _llm_key_required_for_the_default_endpoint(
        cls, value: SecretStr, info: ValidationInfo
    ) -> SecretStr:
        base_url = info.data.get("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL)
        if not value.get_secret_value() and same_url(base_url, DEFAULT_OPENAI_BASE_URL):
            raise ValueError(
                "OPENAI_API_KEY is required for the default endpoint. "
                "It may stay blank when OPENAI_BASE_URL points at a server without auth."
            )
        return value

    @field_validator(
        "EMBEDDING_QUERY_PREFIX",
        "EMBEDDING_DOCUMENT_PREFIX",
        "STT_PROMPT",
        "TTS_INSTRUCTIONS",
        "AGENT_INSTRUCTIONS",
    )
    @classmethod
    def _decode_escapes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        for escaped, real in ESCAPES.items():
            value = value.replace(escaped, real)
        return value

    @model_validator(mode="after")
    def _check_consistency(self) -> "Settings":
        if not self.API_PREFIX.startswith("/"):
            raise ValueError("API_PREFIX must start with '/'")
        if self.ROOT_PATH and not self.ROOT_PATH.startswith("/"):
            raise ValueError("ROOT_PATH must be empty or start with '/'")
        if self.RAG_CHUNK_OVERLAP >= self.RAG_CHUNK_SIZE:
            raise ValueError("RAG_CHUNK_OVERLAP must be smaller than RAG_CHUNK_SIZE")
        if self.MIN_ENDPOINTING_DELAY > self.MAX_ENDPOINTING_DELAY:
            raise ValueError("MIN_ENDPOINTING_DELAY must not exceed MAX_ENDPOINTING_DELAY")
        if self.TRACING_PROVIDER == "langsmith" and self.LANGSMITH_API_KEY is None:
            raise ValueError("TRACING_PROVIDER=langsmith requires LANGSMITH_API_KEY")
        return self

    @property
    def cors_origins_list(self) -> list[str]:
        """CORS origins as a list."""
        return [item.strip() for item in self.CORS_ORIGINS.split(",") if item.strip()]

    @property
    def thinking_models_list(self) -> list[str]:
        """Lowercase name fragments of the models that get the thinking switch."""
        return [
            item.strip().lower() for item in self.OPENAI_THINKING_MODELS.split(",") if item.strip()
        ]

    @property
    def api_keys_list(self) -> list[str]:
        """Accepted API keys; an empty list disables authentication."""
        return [
            item.strip() for item in self.API_KEYS.get_secret_value().split(",") if item.strip()
        ]

    @property
    def auth_required(self) -> bool:
        """True when at least one API key is configured."""
        return bool(self.api_keys_list)

    def secret_values(self) -> list[str]:
        """Every non-empty secret value, used to mask log output."""
        values: list[str] = []
        for name in type(self).model_fields:
            value = getattr(self, name)
            if isinstance(value, SecretStr) and value.get_secret_value():
                values.extend(
                    part
                    for part in value.get_secret_value().split(",")
                    if len(part.strip()) >= MIN_SECRET_LENGTH
                )
        return values


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings; raises ``ValidationError`` listing every missing value."""
    return Settings()
