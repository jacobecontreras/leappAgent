from tools import execute_tool


def test_unknown_tool(tmp_db):
    result = execute_tool("nonexistentTool", {})
    assert result["success"] is False
    assert result["error_type"] == "tool_not_found"


def test_validation_error(tmp_db):
    result = execute_tool("viewArtifactList", {})  # missing required job_name
    assert result["success"] is False
    assert result["error_type"] == "validation_error"
    assert "job_name" in result["error"]


def test_extra_field_rejected(tmp_db):
    result = execute_tool("viewArtifactList", {"job_name": "report_1", "bogus": 1})
    assert result["success"] is False
    assert result["error_type"] == "validation_error"


def test_valid_dispatch(tmp_db):
    result = execute_tool("viewReportList", {})
    assert result["success"] is True
    assert result["reports"] == []
