import json
import pytest

from services import agent_service as agent_service_module
from services import pipeline
from services.agent_service import AgentService, REACT_MAX_ITERATIONS, MAX_ITERATIONS_MESSAGE
from services.session_manager import session_manager
from services.settings_service import settings_service

from conftest import FakeOllamaClient, content_turn, json_turn, tool_call_turn


@pytest.fixture
def agent(ingested_report, tmp_audit_dir):
    settings_service.set_chat_model("test-model")
    return AgentService()


def use_fake_client(monkeypatch, turns):
    fake = FakeOllamaClient(turns)
    monkeypatch.setattr(agent_service_module, "ollama_client", fake)
    monkeypatch.setattr(pipeline, "ollama_client", fake)
    return fake


async def run_agent(agent, prompt, session_id):
    return [json.loads(e) async for e in agent.process_agent_message(prompt, session_id)]


def exploratory_turn():
    return json_turn({"route": "exploratory", "tables": [], "query_text": ""})


async def test_no_model_configured(tmp_db, tmp_audit_dir):
    settings_service.set_chat_model("")
    events = await run_agent(AgentService(), "hi", "s-nomodel")
    assert events[0]["type"] == "error"


async def test_no_report_content_is_final(tmp_db, tmp_audit_dir, monkeypatch):
    settings_service.set_chat_model("test-model")
    use_fake_client(monkeypatch, [content_turn("hello ", "there ", "user")])
    events = await run_agent(AgentService(), "hi", "s-final")

    assert [e["type"] for e in events[:-1]] == ["token"] * 3
    final = events[-1]
    assert final["type"] == "final"
    assert final["content"] == "hello there user"

    # Session stored the completed loop
    context = session_manager.get_context_for_ai("s-final")
    assert any("hi" in m["content"] for m in context)


async def test_react_tool_call_round_trip(agent, monkeypatch):
    fake = use_fake_client(monkeypatch, [
        exploratory_turn(),
        tool_call_turn("viewReportList", {}, content="Checking reports."),
        content_turn("one report found")
    ])
    events = await run_agent(agent, "poke around the reports", "s-tools")
    types = [e["type"] for e in events]

    assert "tool_call" in types
    assert types.index("tool_call") < types.index("tool_result")
    assert types[-1] == "final"

    tool_call = next(e for e in events if e["type"] == "tool_call")
    assert tool_call["name"] == "viewReportList"
    tool_result = next(e for e in events if e["type"] == "tool_result")
    assert tool_result["success"] is True

    # The ReAct system prompt carries the catalog and job name
    react_system = fake.calls[1]["messages"][0]["content"]
    assert "callhistory" in react_system
    assert "job_pipe" in react_system

    # Third model call got the assistant tool_calls message and the tool result
    third_messages = fake.calls[2]["messages"]
    assert third_messages[-2]["role"] == "assistant"
    assert third_messages[-2]["tool_calls"]
    assert third_messages[-1]["role"] == "tool"
    assert third_messages[-1]["tool_name"] == "viewReportList"


async def test_react_invalid_tool_self_corrects(agent, monkeypatch):
    fake = use_fake_client(monkeypatch, [
        exploratory_turn(),
        tool_call_turn("bogusTool", {}),
        content_turn("recovered")
    ])
    events = await run_agent(agent, "explore", "s-badtool")

    tool_result = next(e for e in events if e["type"] == "tool_result")
    assert tool_result["success"] is False

    # The error response was fed back to the model as a tool message
    third_messages = fake.calls[2]["messages"]
    assert third_messages[-1]["role"] == "tool"
    assert "tool_not_found" in third_messages[-1]["content"]
    assert events[-1]["content"] == "recovered"


async def test_react_max_iterations(agent, monkeypatch):
    # Distinct arguments each turn so the repeat check does not short-circuit
    turns = [exploratory_turn()] + [
        tool_call_turn("describeArtifact", {"tablename": f"t{i}"})
        for i in range(REACT_MAX_ITERATIONS)
    ]
    use_fake_client(monkeypatch, turns)
    events = await run_agent(agent, "loop forever", "s-max")

    assert events[-1]["type"] == "final"
    assert events[-1]["content"] == MAX_ITERATIONS_MESSAGE


async def test_react_repeated_call_short_circuits(agent, monkeypatch):
    fake = use_fake_client(monkeypatch, [
        exploratory_turn(),
        tool_call_turn("viewReportList", {}),
        tool_call_turn("viewReportList", {}),
        content_turn("done")
    ])
    events = await run_agent(agent, "explore", "s-repeat")

    tool_results = [e for e in events if e["type"] == "tool_result"]
    assert tool_results[0]["success"] is True
    assert tool_results[1]["success"] is False
    assert "repeated_call" in tool_results[1]["summary"]

    # The repeat error was fed back to the model
    fourth_messages = fake.calls[3]["messages"]
    assert "repeated_call" in fourth_messages[-1]["content"]
    assert events[-1]["content"] == "done"


async def test_stream_error_yields_error_event(agent, monkeypatch):
    class BrokenClient:
        async def chat_stream(self, model, messages, tools=None, format=None, think=None):
            raise RuntimeError("connection refused")
            yield  # pragma: no cover

    monkeypatch.setattr(agent_service_module, "ollama_client", BrokenClient())
    monkeypatch.setattr(pipeline, "ollama_client", BrokenClient())
    events = await run_agent(agent, "hi", "s-err")
    assert events[-1]["type"] == "error"
    assert "connection refused" in events[-1]["message"]
