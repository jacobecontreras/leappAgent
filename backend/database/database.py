import os
import json
import sqlite3
import logging
from typing import List, Dict, Any
from contextlib import contextmanager

DB_NAME = "leapp_forensics.db"
DEFAULT_STATUS = "processing"

logger = logging.getLogger(__name__)

def init_database():
    # Create database file in same directory as this script
    conn = get_db_connection()
    cursor = conn.cursor()

    # Main report metadata table: stores info about each uploaded report
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_name TEXT UNIQUE NOT NULL,         -- Unique identifier for each report job
            report_path TEXT NOT NULL,              -- File system path to the report directory
            upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'processing',      -- processing/completed/failed
            error_message TEXT,                      -- Error details if processing failed
            leapp_version TEXT                       -- LEAPP version from the manifest, if present
        )
    ''')

    # Existing installs created reports before leapp_version existed
    try:
        cursor.execute("ALTER TABLE reports ADD COLUMN leapp_version TEXT")
    except sqlite3.OperationalError:
        pass

    # Artifact catalog parsed from the report's _lava_data.lava manifest.
    # The artifact data itself stays in the report's _lava_artifacts.db,
    # which is only ever opened read-only.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS artifact_catalog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_name TEXT NOT NULL,                -- Links to reports table
            category TEXT,                          -- LAVA category (e.g. 'Call History')
            artifact_name TEXT NOT NULL,           -- Human-readable artifact name
            tablename TEXT NOT NULL,               -- Table name in _lava_artifacts.db
            description TEXT,                      -- Module description from manifest meta
            record_count INTEGER,                  -- Row count reported by the manifest
            column_map TEXT,                       -- JSON: sanitized column -> human header
            object_columns TEXT,                   -- JSON: [{name, type}] typed columns (datetime etc.)
            source_path TEXT,                      -- Original evidence file the artifact came from
            FOREIGN KEY (job_name) REFERENCES reports(job_name) ON DELETE CASCADE,
            UNIQUE(job_name, tablename)
        )
    ''')

    # SHA-256 manifest of source evidence files hashed at ingest
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ingested_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_name TEXT NOT NULL,                -- Links to reports table
            file_path TEXT NOT NULL,               -- Absolute path to source file
            file_name TEXT NOT NULL,               -- Base filename
            sha256 TEXT NOT NULL,                  -- SHA-256 of file contents at ingest
            size_bytes INTEGER,                    -- File size at ingest
            hashed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (job_name) REFERENCES reports(job_name) ON DELETE CASCADE
        )
    ''')

    # AI settings for the application
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ai_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            setting_key TEXT UNIQUE NOT NULL,       -- 'chat_model', 'embed_model', 'disable_embedding'
            setting_value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Remove settings from the pre-Ollama versions of the app
    cursor.execute("DELETE FROM ai_settings WHERE setting_key IN ('api_key', 'rules', 'model')")

    # Remove tables from the pre-LAVA versions of the app (TSV/timeline copies)
    for legacy_table in ('artifact_types', 'artifact_data', 'timeline_events'):
        cursor.execute(f"DROP TABLE IF EXISTS {legacy_table}")

    # Save changes and close connection
    conn.commit()
    conn.close()

def reset_database():
    """Reset the database by dropping all tables except ai_settings"""
    with get_db_cursor() as cursor:
        # List of tables to drop
        tables = ['reports', 'artifact_catalog', 'ingested_files']
        
        for table in tables:
            cursor.execute(f"DROP TABLE IF EXISTS {table}")
            
    # Re-initialize the database to recreate empty tables
    init_database()
    logger.info("Database reset successfully")

def get_db_connection():
    """Get database connection (path overridable via LEAPP_DB_PATH for tests)"""
    db_path = os.environ.get("LEAPP_DB_PATH", os.path.join(os.path.dirname(__file__), DB_NAME))
    return sqlite3.connect(db_path)

@contextmanager
def get_db_cursor():
    """Context manager for database operations"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def insert_report_metadata(job_name: str, report_path: str):
    """Insert report metadata"""
    with get_db_cursor() as cursor:
        cursor.execute(
            "INSERT INTO reports (job_name, report_path, status) VALUES (?, ?, ?)",
            (job_name, report_path, DEFAULT_STATUS)
        )

def update_report_status(job_name: str, status: str, error_message: str = None):
    """Update report processing status"""
    with get_db_cursor() as cursor:
        if error_message:
            cursor.execute(
                "UPDATE reports SET status = ?, error_message = ? WHERE job_name = ?",
                (status, error_message, job_name)
            )
        else:
            cursor.execute(
                "UPDATE reports SET status = ? WHERE job_name = ?",
                (status, job_name)
            )

def set_report_leapp_version(job_name: str, leapp_version: str):
    """Record the LEAPP version that produced the report, when the manifest provides it"""
    with get_db_cursor() as cursor:
        cursor.execute(
            "UPDATE reports SET leapp_version = ? WHERE job_name = ?",
            (leapp_version, job_name)
        )

def store_artifact_catalog(job_name: str, entries: List[Dict[str, Any]]):
    """Store the artifact catalog parsed from the report's LAVA manifest"""
    with get_db_cursor() as cursor:
        for entry in entries:
            cursor.execute('''
                INSERT INTO artifact_catalog
                    (job_name, category, artifact_name, tablename, description,
                     record_count, column_map, object_columns, source_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                job_name,
                entry.get('category'),
                entry['name'],
                entry['tablename'],
                entry.get('description'),
                entry.get('record_count'),
                json.dumps(entry.get('column_map', {})),
                json.dumps(entry.get('object_columns', [])),
                entry.get('source_path')
            ))

        logger.info(f"Stored artifact catalog for job {job_name}: {len(entries)} artifacts")

def store_ingested_file(job_name: str, file_path: str, sha256: str, size_bytes: int):
    """Record a source file's hash in the ingest manifest"""
    with get_db_cursor() as cursor:
        cursor.execute(
            "INSERT INTO ingested_files (job_name, file_path, file_name, sha256, size_bytes) VALUES (?, ?, ?, ?, ?)",
            (job_name, file_path, os.path.basename(file_path), sha256, size_bytes)
        )

# AI Settings Management Functions

def get_ai_setting(setting_key: str) -> str:
    """Get a specific AI setting value"""
    with get_db_cursor() as cursor:
        cursor.execute("SELECT setting_value FROM ai_settings WHERE setting_key = ?", (setting_key,))
        result = cursor.fetchone()
        return result[0] if result else None

def set_ai_setting(setting_key: str, setting_value: str):
    """Set a specific AI setting value"""
    with get_db_cursor() as cursor:
        cursor.execute('''
            INSERT OR REPLACE INTO ai_settings (setting_key, setting_value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        ''', (setting_key, setting_value))

def get_all_ai_settings() -> Dict[str, str]:
    """Get all AI settings as a dictionary"""
    with get_db_cursor() as cursor:
        cursor.execute("SELECT setting_key, setting_value FROM ai_settings")
        return {row[0]: row[1] for row in cursor.fetchall()}