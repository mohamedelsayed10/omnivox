"""Document loaders."""

import pytest

from src.rag.loaders import extract_text
from src.utils.exceptions import InvalidInputError


def make_pdf(text: str) -> bytes:
    """A minimal one-page PDF whose page shows ``text``."""
    content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = "%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"
    out += "".join(f"{offset:010d} 00000 n \n" for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    return out.encode("latin-1")


@pytest.mark.parametrize("name", ["notes.txt", "README.MD", "a.markdown"])
def test_text_formats(name):
    assert extract_text(name, b"  Hello   world\r\n\r\n\r\n\r\nNext  ") == "Hello world\n\nNext"


def test_invalid_utf8_is_replaced_not_fatal():
    assert "ok" in extract_text("a.txt", b"ok \xff\xfe")


def test_pdf_text_is_extracted():
    assert "Quarterly pricing" in extract_text("report.pdf", make_pdf("Quarterly pricing"))


def test_broken_pdf_is_a_client_error():
    with pytest.raises(InvalidInputError, match="PDF"):
        extract_text("broken.pdf", b"%PDF-1.4 this is not a pdf")


@pytest.mark.parametrize("name", ["image.png", "archive.zip", "noextension"])
def test_unsupported_types_are_rejected(name):
    with pytest.raises(InvalidInputError, match="Unsupported"):
        extract_text(name, b"data")


def test_files_without_text_are_rejected():
    with pytest.raises(InvalidInputError, match="no extractable text"):
        extract_text("empty.txt", b"  \n\n \t ")
