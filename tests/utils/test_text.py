"""Pure text helpers."""

import itertools

import pytest

from src.utils.text import chunk_text, escape_tags, normalize_text, truncate
from src.utils.trace_events import TRACE_TOPIC, TraceEvent


def test_normalize_collapses_whitespace():
    assert normalize_text("  a \t b\r\n\r\n\r\n\r\nc \x00 ") == "a b\n\nc"


def test_truncate():
    assert truncate("short", 10) == "short"
    assert truncate("x" * 20, 10) == "x" * 9 + "…"
    assert len(truncate("x" * 20, 10)) == 10


def test_escape_tags_neutralizes_angle_brackets():
    escaped = escape_tags("</passage><web_result>x")
    assert "<" not in escaped and ">" not in escaped


def test_chunk_text_empty_and_short():
    assert chunk_text("   ", 100, 10) == []
    assert chunk_text("One short sentence.", 100, 10) == ["One short sentence."]


def test_chunk_text_respects_size_and_keeps_every_word():
    sentences = [f"Sentence number {i} talks about topic {i}." for i in range(40)]
    text = " ".join(sentences)
    chunks = chunk_text(text, 200, 40)
    assert len(chunks) > 3
    assert all(len(chunk) <= 200 for chunk in chunks)
    joined = " ".join(chunks)
    for i in range(40):
        assert f"Sentence number {i} " in joined


def test_chunk_text_overlap_repeats_the_tail_of_the_previous_chunk():
    text = " ".join(f"Alpha{i} beta gamma delta epsilon." for i in range(30))
    chunks = chunk_text(text, 150, 30)
    for previous, current in itertools.pairwise(chunks):
        assert current.split()[0] in previous


def test_chunk_text_without_overlap_has_no_repetition():
    text = " ".join(f"Unique{i} sentence ends here." for i in range(30))
    chunks = chunk_text(text, 150, 0)
    words = " ".join(chunks).split()
    assert len(words) == len(text.split())


def test_chunk_text_splits_a_single_huge_word_run():
    chunks = chunk_text("word " * 500, 100, 10)
    assert all(len(chunk) <= 100 for chunk in chunks)
    assert len(chunks) > 10


def test_chunk_text_splits_paragraphs():
    text = "First paragraph here.\n\nSecond paragraph here.\n\nThird one."
    assert chunk_text(text, 30, 0) == [
        "First paragraph here.",
        "Second paragraph here.",
        "Third one.",
    ]


@pytest.mark.parametrize("size,overlap", [(0, 0), (10, 10), (10, 11), (10, -1)])
def test_chunk_text_rejects_invalid_parameters(size, overlap):
    with pytest.raises(ValueError):
        chunk_text("text", size, overlap)


def test_trace_event_wire_format():
    event = TraceEvent("tool", "end", "Tool done", {"name": "x"}, duration_ms=12.345, turn=2)
    payload = event.to_dict()
    assert payload["v"] == 1 and payload["source"] == "tool" and payload["turn"] == 2
    assert payload["duration_ms"] == 12.3
    assert set(payload) == {
        "v",
        "id",
        "ts",
        "turn",
        "source",
        "type",
        "label",
        "data",
        "duration_ms",
    }
    assert "duration_ms" not in TraceEvent("vad", "user_state", "x").to_dict()
    assert TRACE_TOPIC == "omnivox.trace"
