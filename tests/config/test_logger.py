"""Logging: redaction, idempotent setup, request id and output formats."""

import json
import logging

import pytest

from config.logger import (
    HANDLER_MARK,
    REDACTED,
    get_logger,
    redact,
    reset_request_id,
    set_request_id,
    setup_logging,
)

GOOGLE_KEY = "AIza" + "x" * 35
LANGSMITH_KEY = "lsv2_pt_" + "a" * 32 + "_" + "b" * 10
HEX_KEY = "0123456789abcdef" * 4
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.c2lnbmF0dXJlLXNpZ25hdHVyZQ"


@pytest.fixture(autouse=True)
def clean_root():
    root = logging.getLogger()
    saved = list(root.handlers)
    yield
    for handler in list(root.handlers):
        if handler not in saved:
            root.removeHandler(handler)
            handler.close()


@pytest.mark.parametrize(
    "secret",
    [GOOGLE_KEY, LANGSMITH_KEY, HEX_KEY, JWT, "sk-abcdefghijklmnop1234", "Bearer abc.def-123456"],
)
def test_redact_masks_known_secret_shapes(secret):
    assert secret not in redact(f"calling with {secret} now")
    assert REDACTED in redact(f"calling with {secret} now")


def test_redact_masks_key_value_pairs_and_keeps_the_name():
    masked = redact('headers {"xi-api-key": "supersecretvalue", "x": 1}')
    assert "supersecretvalue" not in masked
    assert "xi-api-key" in masked


def test_redact_masks_registered_exact_secrets(settings):
    setup_logging(settings)
    assert "test-key-not-real-0123456789" not in redact("key is test-key-not-real-0123456789!")


def test_redact_leaves_ordinary_text_alone():
    text = "agent: done in 12 ms (tool_calls=1) request 7a3a6bc894a940bd"
    assert redact(text) == text


def test_setup_is_idempotent(settings):
    setup_logging(settings)
    setup_logging(settings)
    ours = [h for h in logging.getLogger().handlers if getattr(h, HANDLER_MARK, False)]
    assert len(ours) == 2  # console + rotating file


def test_exclusive_setup_removes_foreign_handlers(settings):
    foreign = logging.StreamHandler()
    logging.getLogger().addHandler(foreign)
    setup_logging(settings, exclusive=True)
    assert foreign not in logging.getLogger().handlers


def test_file_line_has_the_documented_columns_and_request_id(settings, tmp_path):
    setup_logging(settings)
    token = set_request_id("req-123")
    try:
        get_logger("tests.example").info("hello %s", "world")
    finally:
        reset_request_id(token)
    for handler in logging.getLogger().handlers:
        handler.flush()
    line = (tmp_path / "logs" / "omnivox.log").read_text(encoding="utf-8").strip().splitlines()[-1]
    columns = [part.strip() for part in line.split("|")]
    assert columns[1:] == ["INFO", "tests.example", "req-123", "hello world"]


def test_log_output_masks_secrets_even_in_tracebacks(settings, tmp_path):
    setup_logging(settings)
    try:
        raise RuntimeError(f"failed with {GOOGLE_KEY}")
    except RuntimeError:
        get_logger("tests.secret").exception("boom")
    for handler in logging.getLogger().handlers:
        handler.flush()
    text = (tmp_path / "logs" / "omnivox.log").read_text(encoding="utf-8")
    assert GOOGLE_KEY not in text and REDACTED in text


def test_json_format_emits_one_object_per_line(make_settings, tmp_path):
    setup_logging(make_settings(LOG_FORMAT="json"))
    get_logger("tests.json").warning("structured %d", 7)
    for handler in logging.getLogger().handlers:
        handler.flush()
    record = json.loads(
        (tmp_path / "logs" / "omnivox.log").read_text(encoding="utf-8").splitlines()[-1]
    )
    assert record["level"] == "WARNING"
    assert record["module"] == "tests.json"
    assert record["message"] == "structured 7"
    assert record["request_id"] == "-"
