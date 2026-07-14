import pytest

from database.database import insert_report_metadata
from services.settings_service import settings_service
from utils import processing_utils
from utils.embedding_utils import get_artifact_chunks
from utils.processing_utils import process_leapp_report
from tools import execute_tool

from conftest import make_lava_report


@pytest.fixture
def ingested(tmp_db, tmp_path, monkeypatch):
    make_lava_report(tmp_path)
    settings_service.set_disable_embedding(True)
    monkeypatch.setattr(processing_utils, "embed_job_data", lambda job: None)
    insert_report_metadata("job_tools", str(tmp_path))
    process_leapp_report("job_tools", str(tmp_path))
    return "job_tools"


def test_artifact_list_grouped_by_category(ingested):
    result = execute_tool("viewArtifactList", {"job_name": ingested})
    assert result["success"] is True
    assert result["artifact_count"] == 2
    assert result["categories"]["Call History"][0]["tablename"] == "callhistory"
    assert result["categories"]["WhatsApp"][0]["record_count"] == 3


def test_artifact_list_unknown_report(ingested):
    result = execute_tool("viewArtifactList", {"job_name": "nope"})
    assert result["success"] is False
    assert result["error_type"] == "report_not_found"
    assert "job_tools" in result["error"]


def test_describe_artifact(ingested):
    result = execute_tool("describeArtifact", {"job_name": ingested, "tablename": "callhistory"})
    assert result["success"] is True
    assert result["artifact"] == "Call History"
    assert result["description"] == "Call logs from CallHistory.storedata"
    assert result["evidence_source_path"] == "/evidence/CallHistory.storedata"

    columns = {c["column"]: c for c in result["columns"]}
    assert columns["phone_number"]["label"] == "Phone Number"
    assert "unixepoch" in columns["starting_timestamp"]["type"]
    assert "type" not in columns["call_direction"]

    assert result["sample_rows"]["columns"] == ["starting_timestamp", "phone_number", "call_direction"]
    assert len(result["sample_rows"]["rows"]) == 3


def test_describe_unknown_table_lists_valid(ingested):
    result = execute_tool("describeArtifact", {"job_name": ingested, "tablename": "nope"})
    assert result["success"] is False
    assert result["error_type"] == "artifact_not_found"
    assert "callhistory" in result["error"]
    assert "whatsappmessages" in result["error"]


def test_query_artifacts(ingested):
    result = execute_tool("queryArtifacts", {
        "job_name": ingested,
        "sql": "SELECT phone_number, COUNT(*) AS n FROM callhistory GROUP BY phone_number ORDER BY n DESC"
    })
    assert result["success"] is True
    assert result["rows"][0] == ["+14082560700", 2]
    assert result["truncated"] is False


def test_query_artifacts_bad_sql_self_correctable(ingested):
    result = execute_tool("queryArtifacts", {"job_name": ingested, "sql": "SELECT * FROM no_such_table"})
    assert result["success"] is False
    assert result["error_type"] == "query_error"
    assert "no_such_table" in result["error"]

    result = execute_tool("queryArtifacts", {"job_name": ingested, "sql": "DELETE FROM callhistory"})
    assert result["success"] is False
    assert "SELECT" in result["error"]


def test_search_artifacts_across_tables(ingested):
    result = execute_tool("searchArtifacts", {"job_name": ingested, "pattern": "+14082560700"})
    assert result["success"] is True
    assert result["total_matches"] == 2
    assert result["results"][0]["tablename"] == "callhistory"
    assert result["results"][0]["matches"][0]["phone_number"] == "+14082560700"


def test_search_artifacts_case_sensitivity(ingested):
    insensitive = execute_tool("searchArtifacts", {"job_name": ingested, "pattern": "meet me"})
    assert insensitive["total_matches"] == 1

    sensitive = execute_tool("searchArtifacts", {"job_name": ingested, "pattern": "meet me", "case_sensitive": True})
    assert sensitive["total_matches"] == 0


def test_search_artifacts_respects_limit(ingested):
    result = execute_tool("searchArtifacts", {"job_name": ingested, "pattern": "Incoming", "limit": 2})
    assert result["total_matches"] == 2
    assert result["limit_reached"] is True


def test_free_text_chunks(ingested):
    chunks = get_artifact_chunks(ingested)

    # Only non-empty whatsapp messages produce chunks; callhistory has no free-text column
    assert len(chunks) == 2
    assert all(chunk["metadata"]["tablename"] == "whatsappmessages" for chunk in chunks)
    assert all(chunk["id"].startswith("job_tools_whatsappmessages_") for chunk in chunks)

    pier = next(c for c in chunks if "pier" in c["document"])
    assert pier["document"].startswith("WhatsApp - Messages - Message: Meet me at the pier")
    assert "2020-03-23" in pier["document"]  # timestamp rendered for retrieval context
    assert pier["metadata"]["artifact_name"] == "WhatsApp - Messages"
