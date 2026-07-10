from services.ollama_client import OllamaClient, NUM_CTX


def test_payload_defaults():
    payload = OllamaClient._build_payload("m", [{"role": "user", "content": "hi"}])
    assert payload["options"]["num_ctx"] == NUM_CTX
    assert payload["stream"] is True
    assert "tools" not in payload
    assert "format" not in payload
    assert "think" not in payload


def test_payload_includes_optional_keys_when_set():
    schema = {"type": "object"}
    payload = OllamaClient._build_payload("m", [], tools=[{"t": 1}], format=schema, think="low")
    assert payload["tools"] == [{"t": 1}]
    assert payload["format"] == schema
    assert payload["think"] == "low"
