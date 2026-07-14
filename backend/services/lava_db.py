import os
import sqlite3
import logging
from typing import Dict, Any

from database.database import get_db_cursor
from parsers.lava_manifest import LAVA_DB_NAME

MAX_QUERY_ROWS = 200
MAX_CELL_CHARS = 500

# SQLite authorizer action codes permitted during query compilation.
# Everything else (writes, ATTACH, PRAGMA, transactions) is denied.
_ALLOWED_ACTIONS = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
    sqlite3.SQLITE_RECURSIVE,
}

logger = logging.getLogger(__name__)


def _authorizer(action, arg1, arg2, db_name, trigger):
    return sqlite3.SQLITE_OK if action in _ALLOWED_ACTIONS else sqlite3.SQLITE_DENY


def resolve_lava_db_path(job_name: str) -> str:
    """Resolve a report's _lava_artifacts.db path, or raise FileNotFoundError"""
    with get_db_cursor() as cursor:
        cursor.execute("SELECT report_path FROM reports WHERE job_name = ?", (job_name,))
        row = cursor.fetchone()

    if not row:
        raise FileNotFoundError(f"Report '{job_name}' not found")

    db_path = os.path.join(row[0], LAVA_DB_NAME)
    if not os.path.isfile(db_path):
        raise FileNotFoundError(f"LAVA database not found at {db_path} - the report directory may have moved")
    return db_path


def open_lava_db(job_name: str) -> sqlite3.Connection:
    """Open a report's evidence database read-only.

    mode=ro plus query_only means the handle physically cannot write; the
    authorizer additionally rejects non-read operations at compile time.
    """
    db_path = resolve_lava_db_path(job_name)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only=ON")
    conn.set_authorizer(_authorizer)
    return conn


def format_cell(value):
    """Make a cell safe for tool output: summarize blobs, truncate long text"""
    if isinstance(value, bytes):
        return f"<blob {len(value)} bytes>"
    if isinstance(value, str) and len(value) > MAX_CELL_CHARS:
        return value[:MAX_CELL_CHARS] + "... [truncated]"
    return value


def run_query(job_name: str, sql: str) -> Dict[str, Any]:
    """Execute a single read-only SELECT against a report's evidence database.

    Raises ValueError for disallowed SQL and sqlite3.Error for SQL mistakes;
    callers surface those messages to the model so it can self-correct.
    """
    statement = sql.strip().rstrip(";").strip()
    if not statement:
        raise ValueError("SQL query cannot be empty")
    if ";" in statement:
        raise ValueError("Only a single SQL statement is allowed")
    if statement.split(None, 1)[0].upper() not in ("SELECT", "WITH"):
        raise ValueError("Only SELECT queries are allowed")

    conn = open_lava_db(job_name)
    try:
        cursor = conn.execute(statement)
        columns = [description[0] for description in cursor.description or []]
        rows = cursor.fetchmany(MAX_QUERY_ROWS + 1)
    finally:
        conn.close()

    truncated = len(rows) > MAX_QUERY_ROWS
    rows = [[format_cell(cell) for cell in row] for row in rows[:MAX_QUERY_ROWS]]

    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "truncated": truncated,
    }
