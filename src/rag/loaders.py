"""Turn uploaded files into plain text."""

from io import BytesIO
from pathlib import PurePath

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from src.utils.exceptions import InvalidInputError
from src.utils.text import normalize_text

TEXT_EXTENSIONS = {".txt", ".md", ".markdown"}
PDF_EXTENSION = ".pdf"
SUPPORTED_EXTENSIONS = sorted(TEXT_EXTENSIONS | {PDF_EXTENSION})


def extract_text(filename: str, data: bytes) -> str:
    """Extract normalized text from a txt, md or pdf file. Blocking: call from a worker thread."""
    extension = PurePath(filename).suffix.lower()
    if extension in TEXT_EXTENSIONS:
        text = data.decode("utf-8", errors="replace")
    elif extension == PDF_EXTENSION:
        text = _pdf_text(data)
    else:
        raise InvalidInputError(
            f"Unsupported file type '{extension or 'none'}'. Use one of: "
            f"{', '.join(SUPPORTED_EXTENSIONS)}."
        )
    text = normalize_text(text)
    if not text:
        raise InvalidInputError("The file contains no extractable text.")
    return text


def _pdf_text(data: bytes) -> str:
    try:
        reader = PdfReader(BytesIO(data))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    except (PyPdfError, ValueError, OSError) as exc:
        raise InvalidInputError("The PDF could not be read.") from exc
