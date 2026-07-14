import json
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any
from services.chroma_service import chroma_service
from services import lava_db
from database.database import get_db_cursor

logger = logging.getLogger(__name__)

# Column-name fragments that indicate free-text content worth embedding.
# Structured columns are served by SQL; only prose benefits from similarity search.
FREE_TEXT_COLUMN_PATTERNS = (
    'message', 'text', 'note', 'subject', 'title', 'body', 'summary', 'comment', 'description'
)

NON_TEXT_TYPES = ('datetime', 'date', 'bytes', 'media', 'phonenumber')


def _render_timestamp(value) -> str:
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def get_artifact_chunks(job_name: str) -> List[Dict[str, Any]]:
    """Build embedding chunks from a report's free-text columns.

    Reads the LAVA evidence database directly (read-only); one chunk per row
    that has non-empty content in a free-text column.
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute("""
                SELECT artifact_name, tablename, column_map, object_columns
                FROM artifact_catalog
                WHERE job_name = ?
                ORDER BY tablename
            """, (job_name,))
            catalog = cursor.fetchall()

        if not catalog:
            return []

        conn = lava_db.open_lava_db(job_name)
        chunks = []
        try:
            for artifact_name, tablename, column_map, object_columns in catalog:
                column_map = json.loads(column_map or "{}")
                typed = {c["name"]: c["type"] for c in json.loads(object_columns or "[]")}

                text_columns = [
                    column for column in column_map
                    if typed.get(column) not in NON_TEXT_TYPES
                    and any(pattern in column.lower() for pattern in FREE_TEXT_COLUMN_PATTERNS)
                ]
                if not text_columns:
                    continue

                time_column = next(
                    (c["name"] for c in json.loads(object_columns or "[]") if c["type"] in ("datetime", "date")),
                    None
                )

                selected = ["rowid"] + ([time_column] if time_column else []) + text_columns
                select_list = ", ".join(f'"{c}"' for c in selected)
                condition = " OR ".join(f'("{c}" IS NOT NULL AND "{c}" != \'\')' for c in text_columns)
                query = f'SELECT {select_list} FROM "{tablename}" WHERE {condition}'

                try:
                    rows = conn.execute(query).fetchall()
                except Exception as e:
                    logger.warning(f"Skipping '{tablename}' during embedding: {e}")
                    continue

                time_offset = 2 if time_column else 1
                for row in rows:
                    parts = []
                    for index, column in enumerate(text_columns):
                        value = row[time_offset + index]
                        if value:
                            parts.append(f"{column_map[column]}: {lava_db.format_cell(value)}")
                    if not parts:
                        continue

                    document = f"{artifact_name} - " + "; ".join(parts)
                    if time_column:
                        rendered = _render_timestamp(row[1])
                        if rendered:
                            document += f" ({rendered})"

                    chunks.append({
                        "id": f"{job_name}_{tablename}_{row[0]}",
                        "document": document,
                        "metadata": {
                            "job_name": job_name,
                            "tablename": tablename,
                            "artifact_name": artifact_name
                        }
                    })
        finally:
            conn.close()

        logger.info(f"Built {len(chunks)} free-text chunks for job: {job_name}")
        return chunks

    except Exception as e:
        logger.error(f"Error building chunks for {job_name}: {e}")
        return []


def embed_job_data(job_name: str) -> bool:
    """Embed all free-text chunks for a job using Chroma service"""
    chunks = get_artifact_chunks(job_name)

    # Return early if no data found
    if not chunks:
        logger.info(f"No free-text data to embed for job: {job_name}")
        return False

    try:
        # Delegate embedding to Chroma service
        success = chroma_service.embed_and_store_chunks(job_name, chunks)

        # Log result
        if success:
            logger.info(f"Successfully embedded data for job: {job_name}")
        else:
            logger.error(f"Failed to embed data for job: {job_name}")
        return success

    except Exception as e:
        logger.error(f"Error embedding data for job {job_name}: {e}")
        return False
