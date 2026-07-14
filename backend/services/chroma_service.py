import os
import chromadb
import logging
from typing import List, Dict, Any, Optional

from services.ollama_embedding import OllamaEmbeddingFunction
from services.settings_service import settings_service

COLLECTION_NAME = "artifact_chunks"
BATCH_SIZE = 100

logger = logging.getLogger(__name__)


class ChromaService:
    def __init__(self, persist_directory: str = None):
        """Initialize ChromaDB service with persistent storage"""
        if persist_directory is None:
            # Default to same directory as SQLite database
            persist_directory = os.path.join(os.path.dirname(__file__), "..", "database", "chroma")

        os.makedirs(persist_directory, exist_ok=True)

        # Initialize ChromaDB client; the collection is created lazily because
        # the embedding model may not be resolved until the first health check
        self.client = chromadb.PersistentClient(path=persist_directory)
        self._collection = None
        self._embed_model = None

    def _get_collection(self):
        """Get or create the collection with the configured Ollama embedding model"""
        embed_model = settings_service.get_embed_model()
        if not embed_model:
            raise RuntimeError("No embedding model configured. Select one in settings or pull nomic-embed-text.")

        if self._collection is None or embed_model != self._embed_model:
            self._embed_model = embed_model
            self._collection = self.client.get_or_create_collection(
                name=COLLECTION_NAME,
                embedding_function=OllamaEmbeddingFunction(embed_model),
                metadata={"description": "LEAPP forensic report artifact chunks"}
            )
        return self._collection

    def embed_and_store_chunks(self, job_name: str, chunks_data: List[Dict[str, Any]]) -> bool:
        """Embed and store chunks in ChromaDB"""
        try:
            if not chunks_data:
                return True

            collection = self._get_collection()

            documents = [chunk['document'] for chunk in chunks_data]
            metadatas = [chunk['metadata'] for chunk in chunks_data]
            ids = [chunk['id'] for chunk in chunks_data]

            # Add to collection in batches to avoid memory issues
            for i in range(0, len(documents), BATCH_SIZE):
                batch_end = min(i + BATCH_SIZE, len(documents))
                collection.add(
                    documents=documents[i:batch_end],
                    metadatas=metadatas[i:batch_end],
                    ids=ids[i:batch_end]
                )
                logger.info(f"Embedded {batch_end}/{len(documents)} chunks for job {job_name}")

            return True

        except Exception as e:
            logger.error(f"Failed to embed chunks for job {job_name}: {e}")
            return False

    def reset_collection(self) -> bool:
        """Reset the ChromaDB collection"""
        try:
            self.client.delete_collection(COLLECTION_NAME)
        except Exception:
            pass  # Collection may not exist yet
        self._collection = None
        self._embed_model = None
        return True

    def rebuild(self, embed_model: str) -> bool:
        """Drop the collection so it is recreated with a new embedding model.

        Existing embeddings are dimension-bound to the old model, so a model
        change requires re-ingesting reports.
        """
        logger.info(f"Rebuilding vector store for embedding model: {embed_model}")
        return self.reset_collection()

    def query_chunks(self, query_text: str, job_name: Optional[str] = None, n_results: int = 10) -> List[Dict[str, Any]]:
        """Query chunks from ChromaDB"""
        try:
            # Prepare where clause if job_name is specified
            where_clause = {"job_name": job_name} if job_name else None

            results = self._get_collection().query(
                query_texts=[query_text],
                n_results=n_results,
                where=where_clause
            )

            # Format results safely
            if not results['documents'] or not results['documents'][0]:
                return []

            docs = results['documents'][0]
            metadatas = results['metadatas'][0] if results['metadatas'] else [{}] * len(docs)
            distances = results['distances'][0] if results['distances'] else [0] * len(docs)
            ids = results['ids'][0] if results['ids'] else [''] * len(docs)

            return [
                {
                    'document': doc,
                    'metadata': metadatas[i] if i < len(metadatas) else {},
                    'distance': distances[i] if i < len(distances) else 0,
                    'id': ids[i] if i < len(ids) else ''
                }
                for i, doc in enumerate(docs)
            ]

        except Exception as e:
            logger.error(f"Error querying chunks: {str(e)}")
            return []

# Global instance
chroma_service = ChromaService()
