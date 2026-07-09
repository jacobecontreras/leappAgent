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
            error_message TEXT                       -- Error details if processing failed
        )
    ''')

    # Information about TSV files found in each report
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS artifact_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_name TEXT NOT NULL,                -- Links to reports table
            file_name TEXT NOT NULL,               -- Original TSV filename
            artifact_name TEXT,                    -- Display name (cleaned up filename)
            FOREIGN KEY (job_name) REFERENCES reports(job_name) ON DELETE CASCADE,
            UNIQUE(job_name, file_name)           -- Prevent duplicate files per report
        )
    ''')

    # Actual data rows from TSV files, stored as JSON
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS artifact_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_name TEXT NOT NULL,                -- Links to reports table
            artifact_type_id INTEGER NOT NULL,     -- Links to artifact_types table
            row_index INTEGER NOT NULL,            -- Row number from original TSV
            data_json TEXT NOT NULL,                -- Row data serialized as JSON
            FOREIGN KEY (job_name) REFERENCES reports(job_name) ON DELETE CASCADE,
            FOREIGN KEY (artifact_type_id) REFERENCES artifact_types(id) ON DELETE CASCADE
        )
    ''')

    # Timeline events from Timeline directory files
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS timeline_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_name TEXT NOT NULL,                -- Links to reports table
            key TEXT,                               -- Event identifier/unique key
            activity TEXT,                          -- Event description
            datalist TEXT,                          -- Additional event information
            source_artifact TEXT,                   -- Source file for this event
            FOREIGN KEY (job_name) REFERENCES reports(job_name) ON DELETE CASCADE
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

    # Save changes and close connection
    conn.commit()
    conn.close()

def reset_database():
    """Reset the database by dropping all tables except ai_settings"""
    with get_db_cursor() as cursor:
        # List of tables to drop
        tables = ['reports', 'artifact_types', 'artifact_data', 'timeline_events', 'ingested_files']
        
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

def store_tsv_data(job_name: str, tsv_data: Dict[str, List[Dict[str, Any]]]):
    """Store TSV data in database"""
    with get_db_cursor() as cursor:
        for file_name, rows in tsv_data.items():
            # Clean up filename for display
            artifact_name = file_name.replace('.tsv', '').replace('_', ' ').title()
            # Insert artifact type metadata
            cursor.execute(
                "INSERT INTO artifact_types (job_name, file_name, artifact_name) VALUES (?, ?, ?)",
                (job_name, file_name, artifact_name)
            )
            artifact_type_id = cursor.lastrowid

            # Store each row as JSON data
            for row_index, row_data in enumerate(rows):
                cursor.execute(
                    "INSERT INTO artifact_data (job_name, artifact_type_id, row_index, data_json) VALUES (?, ?, ?, ?)",
                    (job_name, artifact_type_id, row_index, json.dumps(row_data))
                )

        logger.info(f"Stored TSV data for job {job_name}: {len(tsv_data)} files")

def store_ingested_file(job_name: str, file_path: str, sha256: str, size_bytes: int):
    """Record a source file's hash in the ingest manifest"""
    with get_db_cursor() as cursor:
        cursor.execute(
            "INSERT INTO ingested_files (job_name, file_path, file_name, sha256, size_bytes) VALUES (?, ?, ?, ?, ?)",
            (job_name, file_path, os.path.basename(file_path), sha256, size_bytes)
        )

def store_timeline_data(job_name: str, timeline_data: List[Dict[str, Any]]):
    """Store timeline data in database"""
    with get_db_cursor() as cursor:
        for event in timeline_data:
            cursor.execute(
                "INSERT INTO timeline_events (job_name, key, activity, datalist, source_artifact) VALUES (?, ?, ?, ?, ?)",
                (job_name, event.get('key'), event.get('activity'), event.get('datalist'),
                 event.get('source_artifact'))
            )

        logger.info(f"Stored timeline data for job {job_name}: {len(timeline_data)} events")

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