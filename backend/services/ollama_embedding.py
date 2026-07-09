import logging
from chromadb import Documents, EmbeddingFunction, Embeddings

from services.ollama_client import ollama_client

logger = logging.getLogger(__name__)

EMBED_BATCH_SIZE = 64


class OllamaEmbeddingFunction(EmbeddingFunction):
    """ChromaDB embedding function backed by the local Ollama /api/embed endpoint"""

    def __init__(self, model: str):
        self.model = model

    def __call__(self, input: Documents) -> Embeddings:
        embeddings = []
        for i in range(0, len(input), EMBED_BATCH_SIZE):
            batch = list(input[i:i + EMBED_BATCH_SIZE])
            embeddings.extend(ollama_client.embed(self.model, batch))
        return embeddings

    # chromadb 1.x persists embedding-function config with the collection
    @staticmethod
    def name() -> str:
        return "ollama"

    def get_config(self) -> dict:
        return {"model": self.model}

    @staticmethod
    def build_from_config(config: dict) -> "OllamaEmbeddingFunction":
        return OllamaEmbeddingFunction(model=config["model"])
