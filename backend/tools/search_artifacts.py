import json
import logging
import sqlite3
from typing import Dict, Any
from database.database import get_db_cursor
from services import lava_db

from .shared_utils import build_error_response

logger = logging.getLogger(__name__)

# Cap per artifact so one noisy table cannot flood the result
PER_ARTIFACT_LIMIT = 25

# Column types with non-text semantics, excluded from pattern matching
NON_TEXT_TYPES = ("datetime", "date", "bytes", "media")


def search_artifacts(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """Search for a text pattern across every artifact table in a report."""
    job_name = input_data["job_name"]
    pattern = input_data["pattern"].strip()
    case_sensitive = input_data["case_sensitive"]
    limit = input_data["limit"]

    if not pattern:
        return build_error_response("validation_error", "Search pattern cannot be empty")

    try:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT job_name FROM reports WHERE job_name = ? LIMIT 1", (job_name,))
            if not cursor.fetchone():
                return build_error_response("report_not_found", f"Report '{job_name}' not found")

            cursor.execute("""
                SELECT artifact_name, tablename, column_map, object_columns
                FROM artifact_catalog
                WHERE job_name = ?
                ORDER BY tablename
            """, (job_name,))
            catalog = cursor.fetchall()

        conn = lava_db.open_lava_db(job_name)
        try:
            results = []
            total_matches = 0

            for artifact_name, tablename, column_map, object_columns in catalog:
                columns = list(json.loads(column_map or "{}").keys())
                typed = {c["name"]: c["type"] for c in json.loads(object_columns or "[]")}
                searchable = [c for c in columns if typed.get(c) not in NON_TEXT_TYPES]
                if not searchable:
                    continue

                if case_sensitive:
                    condition = " OR ".join(f'instr("{c}", ?) > 0' for c in searchable)
                else:
                    condition = " OR ".join(f'"{c}" LIKE \'%\' || ? || \'%\'' for c in searchable)

                per_table_cap = min(PER_ARTIFACT_LIMIT, limit - total_matches)
                query = f'SELECT * FROM "{tablename}" WHERE {condition} LIMIT {per_table_cap}'
                try:
                    result_cursor = conn.execute(query, [pattern] * len(searchable))
                    rows = result_cursor.fetchall()
                except sqlite3.OperationalError as e:
                    # Catalog/table drift; skip this artifact rather than abort the search
                    logger.warning(f"Skipping '{tablename}' during search: {e}")
                    continue
                if not rows:
                    continue

                result_columns = [d[0] for d in result_cursor.description]
                matches = [
                    {column: lava_db.format_cell(value) for column, value in zip(result_columns, row)}
                    for row in rows
                ]
                results.append({
                    "artifact": artifact_name,
                    "tablename": tablename,
                    "match_count": len(matches),
                    "matches": matches
                })
                total_matches += len(matches)
                if total_matches >= limit:
                    break
        finally:
            conn.close()

        return {
            "success": True,
            "pattern": pattern,
            "total_matches": total_matches,
            "limit_reached": total_matches >= limit,
            "results": results
        }

    except (FileNotFoundError, sqlite3.Error) as e:
        return build_error_response("query_error", str(e))
    except Exception as e:
        logger.error(f"Search failed: {str(e)}")
        return build_error_response("database_error", f"Database error: {str(e)}")
