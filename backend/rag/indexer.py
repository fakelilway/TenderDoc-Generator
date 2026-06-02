from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from utils.file_parser import SUPPORTED_EXTENSIONS, extract_text


DEFAULT_CHUNK_SIZE = 1200
DEFAULT_CHUNK_OVERLAP = 200


@dataclass(frozen=True)
class KnowledgeChunk:
    content: str
    metadata: dict[str, str | int] = field(default_factory=dict)


def iter_knowledge_files(knowledge_dir: str | Path) -> list[Path]:
    """Return supported knowledge-base files in stable path order."""
    root = Path(knowledge_dir)
    if not root.exists():
        raise FileNotFoundError(f"Knowledge base directory does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Knowledge base path is not a directory: {root}")

    files = [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    return sorted(files)


def split_text(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[str]:
    """Split text into overlapping chunks without emitting tiny whitespace chunks."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if chunk_overlap < 0:
        raise ValueError("chunk_overlap cannot be negative")
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")

    normalized = "\n".join(line.strip() for line in text.splitlines())
    normalized = normalized.strip()
    if not normalized:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(start + chunk_size, len(normalized))
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(normalized):
            break
        start = end - chunk_overlap

    return chunks


def index_document(
    file_path: str | Path,
    source_root: str | Path | None = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[KnowledgeChunk]:
    path = Path(file_path)
    text = extract_text(path)
    chunks = split_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    root = Path(source_root).resolve() if source_root else path.parent.resolve()
    resolved_path = path.resolve()

    try:
        relative_path = resolved_path.relative_to(root)
    except ValueError:
        relative_path = Path(path.name)

    return [
        KnowledgeChunk(
            content=content,
            metadata={
                "source_path": str(relative_path),
                "file_name": path.name,
                "file_type": path.suffix.lower().lstrip("."),
                "chunk_index": index,
            },
        )
        for index, content in enumerate(chunks)
    ]


def index_knowledge_base(
    knowledge_dir: str | Path,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[KnowledgeChunk]:
    root = Path(knowledge_dir)
    chunks: list[KnowledgeChunk] = []
    for path in iter_knowledge_files(root):
        chunks.extend(
            index_document(
                path,
                source_root=root,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
        )
    return chunks


def print_chunk_summary(chunks: Iterable[KnowledgeChunk]) -> None:
    chunks = list(chunks)
    print(f"Indexed chunks: {len(chunks)}")
    for chunk in chunks[:5]:
        print(
            f"- {chunk.metadata['source_path']} "
            f"#{chunk.metadata['chunk_index']}: {len(chunk.content)} chars"
        )
