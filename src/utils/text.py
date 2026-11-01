"""Pure text helpers: chunking and truncation."""

import re

ELLIPSIS = "…"
LEFT_ANGLE = chr(0x2039)
RIGHT_ANGLE = chr(0x203A)
SENTENCE_BREAK = re.compile(r"(?<=[.!?。؟])\s+|\n{2,}")
INLINE_SPACE = re.compile(r"[ \t]+")
BLANK_LINES = re.compile(r"\n{3,}")


def normalize_text(text: str) -> str:
    """Collapse runs of spaces and blank lines and trim the ends."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = INLINE_SPACE.sub(" ", text)
    return BLANK_LINES.sub("\n\n", text).strip()


def truncate(text: str, limit: int) -> str:
    """Cut ``text`` to at most ``limit`` characters, marking the cut with an ellipsis."""
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)] + ELLIPSIS


def escape_tags(text: str) -> str:
    """Neutralize angle brackets so untrusted text cannot close or open the tags wrapping it."""
    return text.replace("<", LEFT_ANGLE).replace(">", RIGHT_ANGLE)


def _split_long(unit: str, size: int) -> list[str]:
    """Split a unit longer than ``size`` at spaces where possible."""
    pieces: list[str] = []
    while len(unit) > size:
        cut = unit.rfind(" ", size // 2, size)
        cut = cut if cut > 0 else size
        pieces.append(unit[:cut].strip())
        unit = unit[cut:].strip()
    if unit:
        pieces.append(unit)
    return pieces


def _tail(text: str, overlap: int) -> str:
    """Last ``overlap`` characters of ``text``, starting at a word boundary."""
    if overlap <= 0 or not text:
        return ""
    tail = text[-overlap:]
    first_space = tail.find(" ")
    return tail[first_space + 1 :] if 0 <= first_space < len(tail) - 1 else tail


def chunk_text(text: str, size: int, overlap: int) -> list[str]:
    """Split text into chunks of at most ``size`` characters.

    Chunks break on paragraph and sentence boundaries; each chunk starts with the last
    ``overlap`` characters of the previous one so context is not cut mid-thought.
    """
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError("size must be positive and overlap must be in [0, size)")
    text = normalize_text(text)
    if not text:
        return []
    if len(text) <= size:
        return [text]

    units: list[str] = []
    for part in SENTENCE_BREAK.split(text):
        part = part.strip()
        if part:
            units.extend(_split_long(part, size))

    chunks: list[str] = []
    current = ""
    for unit in units:
        candidate = f"{current} {unit}" if current else unit
        if len(candidate) <= size:
            current = candidate
            continue
        chunks.append(current)
        tail = _tail(current, overlap)
        current = f"{tail} {unit}" if tail else unit
        if len(current) > size:
            current = unit
    if current:
        chunks.append(current)
    return chunks
