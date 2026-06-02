import pytest

from rag import embeddings


class FakeModel:
    def encode(self, texts, **kwargs):
        return [[1.0, 0.5, 0.25] for _text in texts]


def test_embed_texts_validates_configured_dimension(monkeypatch) -> None:
    monkeypatch.setattr(embeddings.settings, "embedding_dimension", 3)
    embeddings.get_embedding_model.cache_clear()
    monkeypatch.setattr(
        embeddings, "SentenceTransformer", lambda *args, **kwargs: FakeModel()
    )

    vectors = embeddings.embed_texts(["资质", "业绩"])

    assert vectors == [[1.0, 0.5, 0.25], [1.0, 0.5, 0.25]]


def test_validate_embedding_dimension_rejects_mismatch(monkeypatch) -> None:
    monkeypatch.setattr(embeddings.settings, "embedding_dimension", 3)

    with pytest.raises(embeddings.EmbeddingDimensionError, match="Expected"):
        embeddings.validate_embedding_dimension([1.0, 2.0])
