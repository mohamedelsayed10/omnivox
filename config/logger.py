"""Logging setup: colored console, rotating file, request-id context and secret redaction."""

import contextvars
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config.settings import Settings

LOG_FILE_NAME = "omnivox.log"
DEFAULT_REQUEST_ID = "-"
REDACTED = "***"
LINE_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(request_id)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
HANDLER_MARK = "_omnivox_handler"

# Third-party loggers routed through the shared handlers, and noisy ones kept at WARNING.
ROUTED_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi", "livekit", "asyncio")
NOISY_LOGGERS = (
    "httpx",
    "httpx2",
    "httpcore",
    "ddgs",
    "openai",
    "urllib3",
    "qdrant_client",
    "hpack",
    "primp",
    "rquest",
)

SECRET_PATTERNS = (
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),
    re.compile(r"lsv2_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bsk[-_][A-Za-z0-9_\-]{16,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(?i)(xi-api-key|x-api-key|api[_-]?key)(\"?\s*[:=]\s*\"?)[^\s\"',}]{6,}"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),
    re.compile(r"\b[0-9a-f]{64}\b"),
)
LEVEL_COLORS = {
    "DEBUG": "\033[36m",
    "INFO": "\033[32m",
    "WARNING": "\033[33m",
    "ERROR": "\033[31m",
    "CRITICAL": "\033[1;41m",
}
RESET = "\033[0m"

_request_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default=DEFAULT_REQUEST_ID
)
_exact_secrets: set[str] = set()


def set_request_id(value: str) -> contextvars.Token[str]:
    """Bind the request id to the current context and return the reset token."""
    return _request_id.set(value)


def reset_request_id(token: contextvars.Token[str]) -> None:
    """Restore the request id that was active before ``set_request_id``."""
    _request_id.reset(token)


def get_request_id() -> str:
    """Return the request id of the current context (``-`` outside a request)."""
    return _request_id.get()


def redact(text: str) -> str:
    """Mask known secret values and secret-looking tokens in ``text``."""
    for secret in _exact_secrets:
        text = text.replace(secret, REDACTED)
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(_mask_match, text)
    return text


def _mask_match(match: re.Match[str]) -> str:
    if match.lastindex and match.lastindex >= 2:
        return f"{match.group(1)}{match.group(2)}{REDACTED}"
    return REDACTED


class _ContextFormatter(logging.Formatter):
    """Adds the request id to the record and redacts the final text, tracebacks included."""

    def format(self, record: logging.LogRecord) -> str:
        record.request_id = get_request_id()
        return redact(self._render(record))

    def _render(self, record: logging.LogRecord) -> str:
        return super().format(record)


class ConsoleFormatter(_ContextFormatter):
    """Human readable line with the level colored when the stream supports it."""

    def __init__(self, use_color: bool) -> None:
        super().__init__(LINE_FORMAT, DATE_FORMAT)
        self._use_color = use_color

    def _render(self, record: logging.LogRecord) -> str:
        if not self._use_color:
            return super()._render(record)
        color = LEVEL_COLORS.get(record.levelname, "")
        original = record.levelname
        record.levelname = f"{color}{original}{RESET}"
        try:
            return super()._render(record)
        finally:
            record.levelname = original


class JsonFormatter(_ContextFormatter):
    """One JSON object per line."""

    def _render(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "module": record.name,
            "request_id": record.request_id,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class FileFormatter(_ContextFormatter):
    """Plain text line without color codes."""

    def __init__(self) -> None:
        super().__init__(LINE_FORMAT, DATE_FORMAT)


def _enable_windows_ansi() -> bool:
    """Turn on ANSI escape handling for the Windows console; False when unavailable."""
    if os.name != "nt":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-12)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except (AttributeError, OSError):
        return False


def _supports_color(stream: object) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    isatty = getattr(stream, "isatty", None)
    return bool(isatty and isatty() and _enable_windows_ansi())


def _mark(handler: logging.Handler) -> logging.Handler:
    setattr(handler, HANDLER_MARK, True)
    return handler


def setup_logging(settings: Settings, *, exclusive: bool = False) -> None:
    """Configure the root logger; calling it again replaces our handlers, never stacks them.

    ``exclusive`` also removes handlers installed by other libraries (the LiveKit CLI does so).
    """
    _exact_secrets.update(settings.secret_values())
    root = logging.getLogger()
    for handler in list(root.handlers):
        if exclusive or getattr(handler, HANDLER_MARK, False):
            root.removeHandler(handler)
            handler.close()

    console = _mark(logging.StreamHandler(sys.stderr))
    if settings.LOG_FORMAT == "json":
        console.setFormatter(JsonFormatter())
    else:
        console.setFormatter(ConsoleFormatter(_supports_color(sys.stderr)))
    root.addHandler(console)

    log_dir = Path(settings.LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = _mark(
        RotatingFileHandler(
            log_dir / LOG_FILE_NAME,
            maxBytes=settings.LOG_MAX_BYTES,
            backupCount=settings.LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
    )
    file_handler.setFormatter(JsonFormatter() if settings.LOG_FORMAT == "json" else FileFormatter())
    root.addHandler(file_handler)
    root.setLevel(settings.LOG_LEVEL)

    for name in ROUTED_LOGGERS:
        routed = logging.getLogger(name)
        routed.handlers.clear()
        routed.propagate = True
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    quiet_level = logging.DEBUG if settings.LOG_LEVEL == "DEBUG" else logging.WARNING
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(quiet_level)


def get_logger(name: str) -> logging.Logger:
    """Return a module logger; call with ``__name__``."""
    return logging.getLogger(name)
