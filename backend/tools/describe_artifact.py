import json
import logging
import sqlite3
from typing import Dict, Any
from database.database import get_db_cursor
from services import lava_db

from .shared_utils import build_error_response

logger = logging.getLogger(__name__)

SAMPLE_ROWS = 3


def describe_artifact(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """Describe one artifact table: columns, types, provenance, sample rows."""
    job_name = input_data["job_name"]
    tablename = input_data["tablename"]

    try:
        with get_db_cursor() as cursor:
            cursor.execute("""
                SELECT category, artifact_name, description, record_count,
                       column_map, object_columns, source_path
                FROM artifact_catalog
                WHERE job_name = ? AND tablename = ?
            """, (job_name, tablename))
            row = cursor.fetchone()

            if not row:
                cursor.execute(
                    "SELECT tablename FROM artifact_catalog WHERE job_name = ? ORDER BY tablename",
                    (job_name,)
                )
                valid = [r[0] for r in cursor.fetchall()]
                if not valid:
                    return build_error_response(
                        "report_not_found",
                        f"No artifact catalog for report '{job_name}' - check the report name with viewReportList"
                    )
                return build_error_response(
                    "artifact_not_found",
                    f"No artifact table '{tablename}' in report '{job_name}'. Valid tablenames: {', '.join(valid)}"
                )

        category, artifact_name, description, record_count, column_map, object_columns, source_path = row
        column_map = json.loads(column_map or "{}")
        typed_columns = {col["name"]: col["type"] for col in json.loads(object_columns or "[]")}

        columns = []
        for column, label in column_map.items():
            info = {"column": column, "label": label}
            column_type = typed_columns.get(column)
            if column_type in ("datetime", "date"):
                info["type"] = f"{column_type} (epoch seconds UTC - use datetime({column}, 'unixepoch'))"
            elif column_type:
                info["type"] = column_type
            columns.append(info)

        sample = lava_db.run_query(job_name, f'SELECT * FROM "{tablename}" LIMIT {SAMPLE_ROWS}')

        return {
            "success": True,
            "artifact": artifact_name,
            "category": category,
            "tablename": tablename,
            "description": description,
            "record_count": record_count,
            "evidence_source_path": source_path,
            "columns": columns,
            "sample_rows": {"columns": sample["columns"], "rows": sample["rows"]}
        }

    except (FileNotFoundError, ValueError, sqlite3.Error) as e:
        return build_error_response("query_error", str(e))
    except Exception as e:
        logger.error(f"Failed to describe artifact: {str(e)}")
        return build_error_response("database_error", f"Database error: {str(e)}")
