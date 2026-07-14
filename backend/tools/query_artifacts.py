import logging
import sqlite3
from typing import Dict, Any
from services import lava_db

from .shared_utils import build_error_response

logger = logging.getLogger(__name__)


def query_artifacts(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """Run a read-only SELECT against the report's LAVA evidence database."""
    job_name = input_data["job_name"]
    sql = input_data["sql"]

    try:
        result = lava_db.run_query(job_name, sql)
        return {"success": True, "sql": sql, **result}

    except (FileNotFoundError, ValueError, sqlite3.Error) as e:
        # Surface the exact SQL error so the model can correct its query
        return build_error_response("query_error", str(e), sql=sql)
    except Exception as e:
        logger.error(f"Query failed: {str(e)}")
        return build_error_response("database_error", f"Database error: {str(e)}")
