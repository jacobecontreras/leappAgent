import os
import sqlite3
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

def parse_leapp_db(db_path: str, query: str, field_mapping: List[str], source_artifact: str) -> List[Dict[str, Any]]:
    """Parse LEAPP database with flexible query and field mapping"""
    if not os.path.exists(db_path):
        logger.warning(f"Database file not found: {db_path}")
        return []

    data = []
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()

        # Convert rows to dictionaries using field mapping
        for row in rows:
            row_data = {
                field: row[i]
                for i, field in enumerate(field_mapping)
            }
            row_data['source_artifact'] = source_artifact
            data.append(row_data)

        conn.close()
        logger.info(f"Successfully parsed {len(data)} records from {source_artifact}")

    except Exception as e:
        logger.error(f"Error parsing {source_artifact} data: {e}")

    return data

def parse_timeline_db(db_path: str) -> List[Dict[str, Any]]:
    """Parse LEAPP's TL database into ours"""
    return parse_leapp_db(
        db_path=db_path,
        query="SELECT key, activity, datalist FROM data",
        field_mapping=['key', 'activity', 'datalist'],
        source_artifact='tl.db'
    )