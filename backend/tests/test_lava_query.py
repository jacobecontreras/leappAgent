import sqlite3

import pytest

from database.database import insert_report_metadata
from services import lava_db
from services.lava_db import run_query, open_lava_db, MAX_QUERY_ROWS, MAX_CELL_CHARS

from conftest import make_lava_report


@pytest.fixture
def report(tmp_db, tmp_path):
    make_lava_report(tmp_path, call_count=MAX_QUERY_ROWS + 5, long_message=True)
    insert_report_metadata("job_q", str(tmp_path))
    return "job_q"


def test_select_works(report):
    result = run_query(report, "SELECT phone_number, COUNT(*) AS n FROM callhistory GROUP BY phone_number ORDER BY n DESC")
    assert result["columns"] == ["phone_number", "n"]
    assert result["row_count"] == 2
    assert result["truncated"] is False


def test_cte_works(report):
    result = run_query(report, "WITH x AS (SELECT * FROM callhistory) SELECT COUNT(*) FROM x")
    assert result["rows"][0][0] == MAX_QUERY_ROWS + 5


def test_trailing_semicolon_allowed(report):
    result = run_query(report, "SELECT COUNT(*) FROM whatsappmessages;")
    assert result["row_count"] == 1


@pytest.mark.parametrize("sql", [
    "DELETE FROM callhistory",
    "UPDATE callhistory SET phone_number = 'x'",
    "INSERT INTO callhistory VALUES (1, 'x', 'y')",
    "PRAGMA user_version = 5",
    "ATTACH ':memory:' AS other",
    "DROP TABLE callhistory",
    "SELECT 1; SELECT 2",
    "",
])
def test_disallowed_sql_rejected(report, sql):
    with pytest.raises(ValueError):
        run_query(report, sql)


def test_write_hidden_in_cte_rejected(report):
    with pytest.raises(sqlite3.Error):
        run_query(report, "WITH x AS (SELECT 1) INSERT INTO callhistory VALUES (1, 'x', 'y')")


def test_connection_is_read_only(report):
    conn = open_lava_db(report)
    try:
        with pytest.raises(sqlite3.Error):
            conn.execute("CREATE TABLE hax (x)")
    finally:
        conn.close()


def test_row_cap_sets_truncated(report):
    result = run_query(report, "SELECT * FROM callhistory")
    assert result["row_count"] == MAX_QUERY_ROWS
    assert result["truncated"] is True


def test_long_cells_truncated(report):
    result = run_query(report, "SELECT message FROM whatsappmessages WHERE sender_name = 'Dave'")
    cell = result["rows"][0][0]
    assert cell.endswith("... [truncated]")
    assert len(cell) < 600


def test_unknown_report(tmp_db):
    with pytest.raises(FileNotFoundError):
        run_query("nope", "SELECT 1")


def test_moved_report_directory(tmp_db, tmp_path):
    insert_report_metadata("job_moved", str(tmp_path / "gone"))
    with pytest.raises(FileNotFoundError):
        lava_db.resolve_lava_db_path("job_moved")
