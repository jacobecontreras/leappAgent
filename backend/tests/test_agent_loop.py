import json
import pytest

from services import agent_service as agent_service_module
from services.agent_service import AgentService, MAX_ITERATIONS, MAX_ITERATIONS_MESSAGE
from services.session_manager import session_manager
from services.settings_service import settings_service

from conftest import FakeOllamaClient, content_turn, tool_call_turn


@pytest.fixture
def agent(tmp_db, tmp_audit_dir):
    settings_service.set_chat_model("test-model")
    return AgentService()


def use_fake_client(monkeypatch, turns):
    fake = FakeOllamaClient(turns)
    monkeypatch.setattr(agent_service_module, "ollama_client", fake)
    return fake


async def run_agent(agent, prompt, session_id):
    return [json.loads(e) async for e in agent.process_agent_message(prompt, session_id)]


async def test_no_model_configured(tmp_db, tmp_audit_dir):
    settings_service.set_chat_model("")
    events = await run_agent(AgentService(), "hi", "s-nomodel")
    assert events[0]["type"] == "error"


async def test_content_only_is_final(agent, monkeypatch):
    use_fake_client(monkeypatch, [content_turn("hello ", "there ", "user")])
    events = await run_agent(agent, "hi", "s-final")

    assert [e["type"] for e in events[:-1]] == ["token"] * 3
    final = events[-1]
    assert final["type"] == "final"
    assert final["content"] == "hello there user"

    # Session stored the completed loop
    context = session_manager.get_context_for_ai("s-final")
    assert any("hi" in m["content"] for m in context)


async def test_tool_call_round_trip(agent, monkeypatch):
    fake = use_fake_client(monkeypatch, [
        tool_call_turn("viewReportList", {}, content="Checking reports."),
        content_turn("no reports found")
    ])
    events = await run_agent(agent, "what reports exist?", "s-tools")
    types = [e["type"] for e in events]

    # content precedes tool_call, tool_result follows, then second-turn tokens and final
    assert types[0] == "token"
    assert "tool_call" in types
    assert types.index("tool_call") < types.index("tool_result")
    assert types[-1] == "final"

    tool_call = next(e for e in events if e["type"] == "tool_call")
    assert tool_call["name"] == "viewReportList"
    tool_result = next(e for e in events if e["type"] == "tool_result")
    assert tool_result["success"] is True

    # Second model call got the assistant tool_calls message and the tool result
    second_messages = fake.calls[1]["messages"]
    assert second_messages[-2]["role"] == "assistant"
    assert second_messages[-2]["tool_calls"]
    assert second_messages[-1]["role"] == "tool"
    assert second_messages[-1]["tool_name"] == "viewReportList"


async def test_invalid_tool_self_corrects(agent, monkeypatch):
    fake = use_fake_client(monkeypatch, [
        tool_call_turn("bogusTool", {}),
        content_turn("recovered")
    ])
    events = await run_agent(agent, "hi", "s-badtool")

    tool_result = next(e for e in events if e["type"] == "tool_result")
    assert tool_result["success"] is False

    # The error response was fed back to the model as a tool message
    second_messages = fake.calls[1]["messages"]
    assert second_messages[-1]["role"] == "tool"
    assert "tool_not_found" in second_messages[-1]["content"]
    assert events[-1]["content"] == "recovered"


async def test_max_iterations(agent, monkeypatch):
    turns = [tool_call_turn("viewReportList", {}) for _ in range(MAX_ITERATIONS)]
    use_fake_client(monkeypatch, turns)
    events = await run_agent(agent, "loop forever", "s-max")

    assert events[-1]["type"] == "final"
    assert events[-1]["content"] == MAX_ITERATIONS_MESSAGE


async def test_stream_error_yields_error_event(agent, monkeypatch):
    class BrokenClient:
        async def chat_stream(self, model, messages, tools=None):
            raise RuntimeError("connection refused")
            yield  # pragma: no cover

    monkeypatch.setattr(agent_service_module, "ollama_client", BrokenClient())
    events = await run_agent(agent, "hi", "s-err")
    assert events[-1]["type"] == "error"
    assert "connection refused" in events[-1]["message"]
