import os
import sys
import json
import sqlite3
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


@pytest.fixture
def ingested_report(tmp_db, tmp_path, monkeypatch):
    """A fake LAVA report ingested as 'job_pipe' with embedding disabled"""
    from database.database import insert_report_metadata
    from services.settings_service import settings_service
    from utils import processing_utils
    make_lava_report(tmp_path)
    settings_service.set_disable_embedding(True)
    monkeypatch.setattr(processing_utils, "embed_job_data", lambda job: None)
    insert_report_metadata("job_pipe", str(tmp_path))
    processing_utils.process_leapp_report("job_pipe", str(tmp_path))
    return "job_pipe"


def make_lava_report(tmp_path, call_count=3, long_message=False, complete=True):
    """Build a minimal LAVA-format report: _lava_artifacts.db + _lava_data.lava"""
    conn = sqlite3.connect(tmp_path / "_lava_artifacts.db")
    conn.execute("CREATE TABLE callhistory (starting_timestamp INTEGER, phone_number TEXT, call_direction TEXT)")
    conn.executemany(
        "INSERT INTO callhistory VALUES (?, ?, ?)",
        [(1584993772 + i, "+14082560700" if i % 2 == 0 else "+17042751134", "Incoming") for i in range(call_count)]
    )

    conn.execute("CREATE TABLE whatsappmessages (timestamp INTEGER, sender_name TEXT, message TEXT)")
    message_rows = [
        (1585000000, "Alice", "Meet me at the pier at noon"),
        (1585000060, "Bob", ""),
        (1585000120, "Carol", "Wire the money to the usual account"),
    ]
    if long_message:
        message_rows.append((1585000180, "Dave", "x" * 600))
    conn.executemany("INSERT INTO whatsappmessages VALUES (?, ?, ?)", message_rows)
    conn.commit()
    conn.close()

    manifest = {
        "processing_status": "Complete" if complete else "In Progress",
        "lava_db_name": "_lava_artifacts.db",
        "parser_info": {"leapp_version": "2.3.0"},
        "artifacts": {
            "Call History": [{
                "name": "Call History",
                "tablename": "callhistory",
                "column_map": {
                    "starting_timestamp": "Starting Timestamp",
                    "phone_number": "Phone Number",
                    "call_direction": "Call Direction"
                },
                "object_columns": [
                    {"name": "starting_timestamp", "type": "datetime"},
                    {"name": "phone_number", "type": "phonenumber"}
                ],
                "record_count": call_count,
                "source_path": "/evidence/CallHistory.storedata"
            }],
            "WhatsApp": [{
                "name": "WhatsApp - Messages",
                "tablename": "whatsappmessages",
                "column_map": {
                    "timestamp": "Timestamp",
                    "sender_name": "Sender Name",
                    "message": "Message"
                },
                "object_columns": [{"name": "timestamp", "type": "datetime"}],
                "record_count": len(message_rows),
                "source_path": "/evidence/ChatStorage.sqlite"
            }]
        },
        "meta": {
            "modules": [{
                "module_name": "callHistory",
                "artifacts": [{
                    "tablename": "callhistory",
                    "name": "Call History",
                    "description": "Call logs from CallHistory.storedata"
                }]
            }]
        }
    }
    (tmp_path / "_lava_data.lava").write_text(json.dumps(manifest))
    return tmp_path


class FakeOllamaClient:
    """Scripted Ollama client: yields ChatChunk sequences per chat_stream call"""

    def __init__(self, turns):
        # turns: list of lists of ChatChunk, one list per chat_stream invocation
        self.turns = list(turns)
        self.calls = []

    async def chat_stream(self, model, messages, tools=None, format=None, think=None):
        self.calls.append({"model": model, "messages": list(messages), "tools": tools,
                           "format": format, "think": think})
        if not self.turns:
            return
        for chunk in self.turns.pop(0):
            yield chunk


def content_turn(*tokens):
    """A model turn that streams content only (a final answer)"""
    return [ChatChunk(content=token) for token in tokens] + [ChatChunk(done=True)]


def json_turn(obj):
    """A model turn that streams one JSON object (router/SQL structured output)"""
    return content_turn(json.dumps(obj))


def tool_call_turn(name, arguments, content=""):
    """A model turn that requests one tool call, optionally preceded by content"""
    chunks = []
    if content:
        chunks.append(ChatChunk(content=content))
    chunks.append(ChatChunk(tool_calls=[{"function": {"name": name, "arguments": arguments}}]))
    chunks.append(ChatChunk(done=True))
    return chunks
