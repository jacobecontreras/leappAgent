import json
import logging
import httpx
from dataclasses import dataclass, field
from typing import AsyncGenerator, List, Optional

logger = logging.getLogger(__name__)

OLLAMA_URL = "http://127.0.0.1:11434"

# Preferred chat model families, checked in order when resolving a default
PREFERRED_CHAT_PREFIXES = ["qwen", "llama", "mistral"]
DEFAULT_EMBED_MODEL = "nomic-embed-text"

# Ollama's default context (4096) silently drops the oldest messages once the
# system prompt, tool schemas, and tool results exceed it - the model loses
# the user's question. Artifact catalogs alone can be several thousand tokens.
NUM_CTX = 16384


@dataclass
class ChatChunk:
    """One streamed chunk from Ollama's /api/chat"""
    content: str = ""
    thinking: str = ""
    tool_calls: List[dict] = field(default_factory=list)
    done: bool = False


class OllamaClient:
    def __init__(self, base_url: str = OLLAMA_URL):
        self.base_url = base_url

    async def is_healthy(self) -> bool:
        """Check whether the Ollama server is reachable"""
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(f"{self.base_url}/api/version")
                return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def list_models(self) -> List[dict]:
        """List locally installed models via /api/tags"""
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            return response.json().get("models", [])

    async def model_capabilities(self, name: str) -> List[str]:
        """Get a model's capabilities (e.g. 'tools', 'embedding') via /api/show"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(f"{self.base_url}/api/show", json={"model": name})
                response.raise_for_status()
                return response.json().get("capabilities", [])
        except httpx.HTTPError as e:
            logger.warning(f"Failed to fetch capabilities for model {name}: {e}")
            return []

    @staticmethod
    def _build_payload(model: str, messages: list, tools: Optional[list] = None,
                       format: Optional[dict] = None, think: Optional[str] = None) -> dict:
        payload = {"model": model, "messages": messages, "stream": True, "options": {"num_ctx": NUM_CTX}}
        if tools:
            payload["tools"] = tools
        if format is not None:
            payload["format"] = format
        # Only send "think" when set: Ollama rejects it for non-thinking models
        if think is not None:
            payload["think"] = think
        return payload

    async def chat_stream(self, model: str, messages: list, tools: Optional[list] = None,
                          format: Optional[dict] = None, think: Optional[str] = None) -> AsyncGenerator[ChatChunk, None]:
        """Stream a chat completion from /api/chat (NDJSON lines)"""
        payload = self._build_payload(model, messages, tools, format, think)

        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as response:
                if response.status_code != 200:
                    error_text = (await response.aread()).decode()
                    raise RuntimeError(f"Ollama error ({response.status_code}): {error_text}")

                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        parsed = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    message = parsed.get("message", {})
                    yield ChatChunk(
                        content=message.get("content", ""),
                        thinking=message.get("thinking", ""),
                        tool_calls=message.get("tool_calls", []) or [],
                        done=parsed.get("done", False)
                    )
                    if parsed.get("done"):
                        return

    def embed(self, model: str, input_texts: List[str]) -> List[List[float]]:
        """Generate embeddings via /api/embed (sync: chromadb embedding functions are sync)"""
        with httpx.Client(timeout=120.0) as client:
            response = client.post(f"{self.base_url}/api/embed", json={"model": model, "input": input_texts})
            response.raise_for_status()
            return response.json().get("embeddings", [])


# Global instance
ollama_client = OllamaClient()


async def resolve_default_models(client: OllamaClient) -> dict:
    """Pick sensible default chat/embed models from what is installed.

    Returns {"chat_model": str|None, "embed_model": str|None, "models": [...]}
    where models is [{"name", "tools_capable", "embedding"}].
    """
    installed = await client.list_models()
    models = []
    for m in installed:
        name = m.get("name", "")
        capabilities = await client.model_capabilities(name)
        models.append({
            "name": name,
            "tools_capable": "tools" in capabilities,
            "embedding": "embedding" in capabilities
        })

    tools_capable = [m["name"] for m in models if m["tools_capable"]]
    chat_model = None
    for prefix in PREFERRED_CHAT_PREFIXES:
        chat_model = next((n for n in tools_capable if n.lower().startswith(prefix)), None)
        if chat_model:
            break
    if not chat_model and tools_capable:
        chat_model = tools_capable[0]

    embedding_capable = [m["name"] for m in models if m["embedding"]]
    embed_model = next((n for n in embedding_capable if n.startswith(DEFAULT_EMBED_MODEL)), None)
    if not embed_model and embedding_capable:
        embed_model = embedding_capable[0]

    return {"chat_model": chat_model, "embed_model": embed_model, "models": models}
