import json
import pytest

from services import agent_service as agent_service_module
from services import pipeline
from services.agent_service import AgentService
from services.system_prompt import REFUSAL_MESSAGE, ZERO_ROWS_HINT
from services.settings_service import settings_service

from conftest import FakeOllamaClient, content_turn, json_turn


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


def route_turn(route, tables=None, query_text=""):
    return json_turn({"route": route, "tables": tables or [], "query_text": query_text})


def read_audit(tmp_audit_dir, session_id):
    audit_file = tmp_audit_dir / f"audit_{session_id}.jsonl"
    return [json.loads(line) for line in audit_file.read_text().splitlines()]


# --- router ---

async def test_router_call_uses_format_and_catalog(agent, monkeypatch):
    fake = use_fake_client(monkeypatch, [
        route_turn("structured_query", ["callhistory"]),
        json_turn({"sql": 'SELECT COUNT(*) FROM "callhistory"'}),
        content_turn("3 calls")
    ])
    events = await run_agent(agent, "how many calls?", "s-router")

    router_call = fake.calls[0]
    assert router_call["format"] == pipeline.ROUTER_FORMAT
    assert router_call["tools"] is None
    assert "callhistory" in router_call["messages"][0]["content"]

    route_event = next(e for e in events if e["type"] == "route")
    assert route_event["route"] == "structured_query"
    assert route_event["tables"] == ["callhistory"]
    assert route_event["job_name"] == "job_pipe"


async def test_unparseable_router_falls_back_to_react(agent, monkeypatch, tmp_audit_dir):
    fake = use_fake_client(monkeypatch, [
        content_turn("I think this is about calls"),
        content_turn("react answer")
    ])
    events = await run_agent(agent, "how many calls?", "s-noparse")

    # Second call is the ReAct loop: it passes tools
    assert fake.calls[1]["tools"] is not None
    assert events[-1]["content"] == "react answer"

    route_audit = next(r for r in read_audit(tmp_audit_dir, "s-noparse") if r["event"] == "route")
    assert route_audit["data"]["fallback_reason"] == "unparseable"


async def test_parse_route_leniency():
    catalog = ["callhistory"]
    fenced = '```json\n{"route": "structured_query", "tables": ["callhistory", "bogus"], "query_text": ""}\n```'
    route = pipeline.parse_route(fenced, catalog)
    assert route.route == "structured_query"
    assert route.tables == ["callhistory"]

    assert pipeline.parse_route("not json", catalog) is None
    assert pipeline.parse_route('{"route": "invented"}', catalog) is None


async def test_think_level_plumbing(ingested_report, tmp_audit_dir, monkeypatch):
    settings_service.set_chat_model("gpt-oss:20b")
    fake = use_fake_client(monkeypatch, [
        route_turn("direct"),
        content_turn("hello")
    ])
    await run_agent(AgentService(), "hi", "s-think")
    assert fake.calls[0]["think"] == "low"       # router
    assert fake.calls[1]["think"] is None        # synthesis/direct stays default


# --- structured_query ---

async def test_forced_describe_before_sql(agent, monkeypatch):
    fake = use_fake_client(monkeypatch, [
        route_turn("structured_query", ["callhistory"]),
        json_turn({"sql": 'SELECT COUNT(*) AS n FROM "callhistory"'}),
        content_turn("There are 3 calls")
    ])
    events = await run_agent(agent, "how many calls?", "s-describe")

    tool_calls = [e for e in events if e["type"] == "tool_call"]
    assert tool_calls[0]["name"] == "describeArtifact"
    assert tool_calls[0]["arguments"]["tablename"] == "callhistory"
    assert tool_calls[1]["name"] == "queryArtifacts"

    # Describe results (schema + samples) reached the SQL generation call
    sql_gen_messages = fake.calls[1]["messages"]
    assert fake.calls[1]["format"] == pipeline.SQL_FORMAT
    assert "phone_number" in sql_gen_messages[-1]["content"]

    assert events[-1]["type"] == "final"
    assert events[-1]["content"] == "There are 3 calls"


async def test_sql_retry_feeds_back_error(agent, monkeypatch, tmp_audit_dir):
    fake = use_fake_client(monkeypatch, [
        route_turn("structured_query", ["callhistory"]),
        json_turn({"sql": "SELEC broken"}),
        json_turn({"sql": 'SELECT COUNT(*) AS n FROM "callhistory"'}),
        content_turn("3 calls")
    ])
    events = await run_agent(agent, "how many calls?", "s-retry")

    query_calls = [e for e in events if e["type"] == "tool_call" and e["name"] == "queryArtifacts"]
    assert len(query_calls) == 2

    # Exact error string fed back to the second generation call
    second_gen = fake.calls[2]["messages"][-1]["content"]
    assert "Feedback on your previous query" in second_gen

    attempts = [r for r in read_audit(tmp_audit_dir, "s-retry") if r["event"] == "sql_attempt"]
    assert len(attempts) == 2
    assert attempts[0]["data"]["success"] is False
    assert attempts[1]["data"]["success"] is True


async def test_zero_rows_retries_once(agent, monkeypatch):
    fake = use_fake_client(monkeypatch, [
        route_turn("structured_query", ["callhistory"]),
        json_turn({"sql": "SELECT * FROM \"callhistory\" WHERE phone_number = 'nope'"}),
        json_turn({"sql": "SELECT * FROM \"callhistory\" WHERE phone_number = 'still-nope'"}),
        content_turn("No matching calls")
    ])
    events = await run_agent(agent, "calls from nope?", "s-zero")

    assert ZERO_ROWS_HINT in fake.calls[2]["messages"][-1]["content"]
    # Second zero-row result is accepted as evidence, not retried again
    assert events[-1]["content"] == "No matching calls"


async def test_hard_gate_refuses_without_evidence(agent, monkeypatch, tmp_audit_dir):
    use_fake_client(monkeypatch, [
        route_turn("structured_query", ["callhistory"]),
        json_turn({"sql": "SELEC broken"}),
        json_turn({"sql": "DELETE FROM callhistory"}),
        json_turn({"sql": "PRAGMA integrity_check"}),
        # no synthesis turn scripted: the gate must refuse without another LLM call
    ])
    events = await run_agent(agent, "how many calls?", "s-gate")

    assert events[-1]["type"] == "final"
    assert events[-1]["content"] == REFUSAL_MESSAGE
    audit = read_audit(tmp_audit_dir, "s-gate")
    assert any(r["event"] == "gate_refusal" for r in audit)


async def test_schema_link_failure_falls_back(agent, monkeypatch, tmp_audit_dir):
    # Router picks a table, but every describe fails (empty tables list after filtering
    # can't happen via parse_route, so simulate a describe error with a valid name by
    # deleting the catalog row is overkill - instead route to a table then break describe)
    fake = use_fake_client(monkeypatch, [
        json_turn({"route": "structured_query", "tables": [], "query_text": ""}),
        content_turn("react answer")
    ])
    events = await run_agent(agent, "how many calls?", "s-nolink")

    # No tables selected -> no describes succeed -> ReAct fallback ran with tools
    assert fake.calls[1]["tools"] is not None
    assert events[-1]["content"] == "react answer"
    audit = read_audit(tmp_audit_dir, "s-nolink")
    assert any(r["event"] == "route" and r["data"].get("fallback_reason") == "schema_link_failed"
               for r in audit)


# --- search and direct routes ---

async def test_text_search_route(agent, monkeypatch):
    fake = use_fake_client(monkeypatch, [
        route_turn("text_search", ["callhistory"], query_text="+14082560700"),
        content_turn("Found in call history")
    ])
    events = await run_agent(agent, "find +14082560700", "s-search")

    tool_calls = [e for e in events if e["type"] == "tool_call"]
    assert len(tool_calls) == 1
    assert tool_calls[0]["name"] == "searchArtifacts"
    assert tool_calls[0]["arguments"]["pattern"] == "+14082560700"

    # Synthesis got the search results
    synth = fake.calls[1]["messages"][-1]["content"]
    assert "searchArtifacts" in synth
    assert events[-1]["content"] == "Found in call history"


async def test_direct_route_no_tools(agent, monkeypatch):
    fake = use_fake_client(monkeypatch, [
        route_turn("direct"),
        content_turn("I can query call logs and messages")
    ])
    events = await run_agent(agent, "what can you do?", "s-direct")

    assert len(fake.calls) == 2
    assert not [e for e in events if e["type"] == "tool_call"]
    assert "callhistory" in fake.calls[1]["messages"][0]["content"]
    assert events[-1]["type"] == "final"


async def test_no_report_loaded(tmp_db, tmp_audit_dir, monkeypatch):
    settings_service.set_chat_model("test-model")
    fake = use_fake_client(monkeypatch, [content_turn("Please upload a report")])
    events = await run_agent(AgentService(), "how many calls?", "s-noreport")

    assert len(fake.calls) == 1  # no router, straight to the no-report answer
    assert events[-1]["type"] == "final"
    assert events[-1]["content"] == "Please upload a report"


# --- streaming order ---

async def test_event_order_happy_path(agent, monkeypatch):
    use_fake_client(monkeypatch, [
        route_turn("structured_query", ["callhistory"]),
        json_turn({"sql": 'SELECT COUNT(*) AS n FROM "callhistory"'}),
        content_turn("3 ", "calls")
    ])
    events = await run_agent(agent, "how many calls?", "s-order")
    types = [e["type"] for e in events]

    assert types[0] == "route"
    assert types[1:5] == ["tool_call", "tool_result", "tool_call", "tool_result"]
    assert types[5:] == ["token", "token", "final"]


# --- stage helpers ---

def test_render_catalog(ingested_report):
    catalog = pipeline.load_catalog(ingested_report)
    text = pipeline.render_catalog(catalog)
    assert "callhistory | Call History | Call History | 3" in text
    assert "whatsappmessages" in text


def test_resolve_job(ingested_report):
    assert pipeline.resolve_job(None) == ingested_report
    assert pipeline.resolve_job("explicit-job") == "explicit-job"
