from __future__ import annotations

from io import BytesIO
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from typing import BinaryIO

import pdfplumber
from docx import Document
from pypdf import PdfReader


SUPPORTED_EXTENSIONS = {".pdf", ".doc", ".docx", ".txt", ".md", ".jpg", ".jpeg", ".png"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
LEGACY_WORD_EXTENSIONS = {".doc"}
TEXT_EXTENSIONS = {".txt", ".md"}


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


def extract_text_from_image(
    file_path: str | Path | bytes | bytearray | BinaryIO,
) -> str:
    """Extract text from an image when optional OCR tooling is available."""
    try:
        import pytesseract
        from PIL import Image
    except Exception as error:
        raise ValueError(
            "Image OCR is not configured. Store this file as evidence-only or "
            "install OCR tooling before indexing image text."
        ) from error

    image_input = (
        _as_bytes_io(file_path)
        if not isinstance(file_path, (str, Path))
        else str(file_path)
    )
    try:
        image = Image.open(image_input)
        return pytesseract.image_to_string(image, lang="chi_sim+eng").strip()
    except Exception as error:
        raise ValueError(f"Image OCR failed: {error}") from error


def extract_text_from_legacy_doc(
    file_path: str | Path | bytes | bytearray | BinaryIO,
) -> str:
    """Convert a legacy .doc file with LibreOffice, then extract DOCX text."""
    converter = shutil.which("soffice") or shutil.which("libreoffice")
    if not converter:
        raise ValueError(
            "Legacy .doc conversion requires LibreOffice/soffice. Store this file "
            "as evidence-only or install LibreOffice before indexing .doc text."
        )

    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        source_path = tmp_path / "input.doc"
        if isinstance(file_path, (str, Path)):
            source_path.write_bytes(Path(file_path).read_bytes())
        elif isinstance(file_path, (bytes, bytearray)):
            source_path.write_bytes(bytes(file_path))
        else:
            source_path.write_bytes(file_path.read())

        subprocess.run(
            [
                converter,
                "--headless",
                "--convert-to",
                "docx",
                "--outdir",
                str(tmp_path),
                str(source_path),
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        converted = source_path.with_suffix(".docx")
        if not converted.exists():
            matches = list(tmp_path.glob("*.docx"))
            if not matches:
                raise ValueError("Legacy .doc conversion did not produce a DOCX file")
            converted = matches[0]
        return extract_text_from_docx(converted)


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
    if content_type == "text/plain" or suffix in TEXT_EXTENSIONS:
        return extract_text_from_txt(file_input)
    if suffix in LEGACY_WORD_EXTENSIONS or content_type == "application/msword":
        return extract_text_from_legacy_doc(file_input)
    if suffix in IMAGE_EXTENSIONS or (content_type or "").startswith("image/"):
        return extract_text_from_image(file_input)

    supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
    raise ValueError(f"Unsupported file type. Expected one of: {supported}")
