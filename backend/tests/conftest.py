import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.ollama_client import ChatChunk


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Isolated SQLite database for each test"""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("LEAPP_DB_PATH", str(db_path))
    from database.database import init_database
    init_database()
    return db_path


@pytest.fixture
def tmp_audit_dir(tmp_path, monkeypatch):
    """Isolated audit log directory for each test"""
    audit_dir = tmp_path / "audit"
    from logs import audit
    monkeypatch.setattr(audit.audit_logger, "audit_dir", str(audit_dir))
    return audit_dir


class FakeOllamaClient:
    """Scripted Ollama client: yields ChatChunk sequences per chat_stream call"""

    def __init__(self, turns):
        # turns: list of lists of ChatChunk, one list per chat_stream invocation
        self.turns = list(turns)
        self.calls = []

    async def chat_stream(self, model, messages, tools=None):
        self.calls.append({"model": model, "messages": list(messages), "tools": tools})
        if not self.turns:
            return
        for chunk in self.turns.pop(0):
            yield chunk


def content_turn(*tokens):
    """A model turn that streams content only (a final answer)"""
    return [ChatChunk(content=token) for token in tokens] + [ChatChunk(done=True)]


def tool_call_turn(name, arguments, content=""):
    """A model turn that requests one tool call, optionally preceded by content"""
    chunks = []
    if content:
        chunks.append(ChatChunk(content=content))
    chunks.append(ChatChunk(tool_calls=[{"function": {"name": name, "arguments": arguments}}]))
    chunks.append(ChatChunk(done=True))
    return chunks
