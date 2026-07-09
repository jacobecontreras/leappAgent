from services import ollama_embedding
from services.ollama_embedding import OllamaEmbeddingFunction, EMBED_BATCH_SIZE


def test_batching_and_shape(monkeypatch):
    calls = []

    def fake_embed(model, input_texts):
        calls.append((model, list(input_texts)))
        return [[0.1, 0.2]] * len(input_texts)

    monkeypatch.setattr(ollama_embedding.ollama_client, "embed", fake_embed)

    ef = OllamaEmbeddingFunction("test-embed")
    documents = [f"doc {i}" for i in range(EMBED_BATCH_SIZE * 2 + 10)]
    embeddings = ef(documents)

    assert len(embeddings) == len(documents)
    assert all(len(e) == 2 for e in embeddings)
    assert [len(batch) for _, batch in calls] == [EMBED_BATCH_SIZE, EMBED_BATCH_SIZE, 10]
    assert all(model == "test-embed" for model, _ in calls)


def test_config_round_trip():
    ef = OllamaEmbeddingFunction("nomic-embed-text")
    assert OllamaEmbeddingFunction.name() == "ollama"
    rebuilt = OllamaEmbeddingFunction.build_from_config(ef.get_config())
    assert rebuilt.model == "nomic-embed-text"
