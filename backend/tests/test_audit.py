import json

from logs.audit import audit_logger


def test_jsonl_records(tmp_audit_dir):
    audit_logger.log("session-a", "test-model", "user_message", {"message": "hello"})
    audit_logger.log("session-a", "test-model", "tool_call", {"iteration": 1, "name": "searchArtifacts", "arguments": {"pattern": "x"}})

    audit_file = tmp_audit_dir / "audit_session-a.jsonl"
    assert audit_file.exists()

    records = [json.loads(line) for line in audit_file.read_text().splitlines()]
    assert len(records) == 2

    for record in records:
        assert set(record.keys()) == {"ts", "session_id", "chat_model", "event", "data"}
        assert record["session_id"] == "session-a"
        assert record["chat_model"] == "test-model"

    assert records[0]["event"] == "user_message"
    assert records[1]["data"]["name"] == "searchArtifacts"


def test_per_session_files(tmp_audit_dir):
    audit_logger.log("session-a", "m", "user_message", {"message": "one"})
    audit_logger.log("session-b", "m", "user_message", {"message": "two"})

    assert (tmp_audit_dir / "audit_session-a.jsonl").exists()
    assert (tmp_audit_dir / "audit_session-b.jsonl").exists()


def test_session_id_sanitized(tmp_audit_dir):
    audit_logger.log("../evil/../../path", "m", "user_message", {"message": "x"})
    files = list(tmp_audit_dir.iterdir())
    assert len(files) == 1
    assert files[0].parent == tmp_audit_dir
    assert "/" not in files[0].name.replace(str(tmp_audit_dir), "")
