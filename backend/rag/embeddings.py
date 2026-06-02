from __future__ import annotations

from functools import lru_cache
from typing import Iterable

from sentence_transformers import SentenceTransformer

from core.config import settings


class EmbeddingDimensionError(ValueError):
    pass


@lru_cache
def get_embedding_model() -> SentenceTransformer:
    return SentenceTransformer(
        settings.embedding_model, device=settings.embedding_device
    )


def _to_float_list(vector) -> list[float]:
    if hasattr(vector, "tolist"):
        vector = vector.tolist()
    return [float(value) for value in vector]


def validate_embedding_dimension(vector: list[float]) -> list[float]:
    expected = settings.embedding_dimension
    if len(vector) != expected:
        raise EmbeddingDimensionError(
            f"Expected embedding dimension {expected}, got {len(vector)}"
        )
    return vector


def embed_text(text: str) -> list[float]:
    vectors = embed_texts([text])
    return vectors[0]


def embed_texts(texts: Iterable[str]) -> list[list[float]]:
    texts = list(texts)
    if not texts:
        return []

    model = get_embedding_model()
    vectors = model.encode(
        texts,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    return [validate_embedding_dimension(_to_float_list(vector)) for vector in vectors]


def get_embedding_dimension() -> int:
    return len(embed_text("维度检测"))
