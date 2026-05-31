from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import BinaryIO

import pdfplumber
from docx import Document
from pypdf import PdfReader


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt"}


def _as_bytes_io(file_data: bytes | bytearray | BinaryIO) -> BytesIO | BinaryIO:
    if isinstance(file_data, (bytes, bytearray)):
        return BytesIO(file_data)
    return file_data


def extract_text_from_pdf(file_path: str | Path | bytes | bytearray | BinaryIO) -> str:
    """Extract readable text from a PDF path or byte stream."""
    if isinstance(file_path, (str, Path)):
        path = Path(file_path)
        with pdfplumber.open(path) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
    else:
        data = _as_bytes_io(file_path)
        try:
            with pdfplumber.open(data) as pdf:
                pages = [page.extract_text() or "" for page in pdf.pages]
        except Exception:
            if hasattr(data, "seek"):
                data.seek(0)
            reader = PdfReader(data)
            pages = [page.extract_text() or "" for page in reader.pages]

    return "\n\n".join(page.strip() for page in pages if page.strip())


def extract_text_from_docx(file_path: str | Path | bytes | bytearray | BinaryIO) -> str:
    """Extract paragraph and table text from a DOCX path or byte stream."""
    document = Document(
        _as_bytes_io(file_path)
        if not isinstance(file_path, (str, Path))
        else str(file_path)
    )
    parts: list[str] = []

    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if text:
            parts.append(text)

    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                parts.append(" | ".join(cells))

    return "\n".join(parts)


def extract_text_from_txt(file_path: str | Path | bytes | bytearray | BinaryIO) -> str:
    """Extract text from a TXT path or byte stream."""
    if isinstance(file_path, (str, Path)):
        return Path(file_path).read_text(encoding="utf-8")

    data = file_path if isinstance(file_path, (bytes, bytearray)) else file_path.read()
    if isinstance(data, str):
        return data
    return bytes(data).decode("utf-8")


def extract_text(
    file_input: str | Path | bytes | bytearray | BinaryIO,
    filename: str | None = None,
    content_type: str | None = None,
) -> str:
    """Route an uploaded tender file to the right text extractor."""
    suffix = (
        Path(filename or str(file_input)).suffix.lower()
        if filename or isinstance(file_input, (str, Path))
        else ""
    )

    if content_type == "application/pdf" or suffix == ".pdf":
        return extract_text_from_pdf(file_input)
    if (
        content_type
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        or suffix == ".docx"
    ):
        return extract_text_from_docx(file_input)
    if content_type == "text/plain" or suffix == ".txt":
        return extract_text_from_txt(file_input)

    supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
    raise ValueError(f"Unsupported file type. Expected one of: {supported}")
