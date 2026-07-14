import logging
from typing import Dict, Any
from database.database import get_db_cursor

from .shared_utils import build_error_response

logger = logging.getLogger(__name__)


def artifact_list(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """List a report's artifacts from its LAVA catalog, grouped by category."""
    job_name = input_data["job_name"]

    try:
        with get_db_cursor() as cursor:
            # Check if report exists and get available reports for error message
            cursor.execute("SELECT job_name FROM reports WHERE job_name = ? LIMIT 1", (job_name,))
            if not cursor.fetchone():
                cursor.execute("SELECT job_name FROM reports ORDER BY upload_date DESC LIMIT 10")
                available_reports = [row[0] for row in cursor.fetchall()]
                reports_list = ", ".join(f"'{name}'" for name in available_reports)
                return build_error_response(
                    "report_not_found",
                    f"Report '{job_name}' not found. Available reports: {reports_list}",
                    available_reports=available_reports
                )

            cursor.execute("""
                SELECT category, artifact_name, tablename, record_count
                FROM artifact_catalog
                WHERE job_name = ?
                ORDER BY category, artifact_name
            """, (job_name,))
            rows = cursor.fetchall()

            categories = {}
            for category, artifact_name, tablename, record_count in rows:
                categories.setdefault(category, []).append({
                    "name": artifact_name,
                    "tablename": tablename,
                    "record_count": record_count
                })

            return {
                "success": True,
                "categories": categories,
                "artifact_count": len(rows)
            }

    except Exception as e:
        logger.error(f"Failed to fetch artifact list: {str(e)}")
        return build_error_response("database_error", f"Database error: {str(e)}")
