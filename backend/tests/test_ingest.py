import json
import hashlib

from database.database import get_db_cursor, insert_report_metadata
from services.settings_service import settings_service
from utils import processing_utils
from utils.hash_utils import sha256_file
from utils.processing_utils import validate_leapp_directory, process_leapp_report

from conftest import make_lava_report


def test_validate_lava_report(tmp_path):
    make_lava_report(tmp_path)
    assert validate_leapp_directory(str(tmp_path)) is True


def test_validate_json_manifest(tmp_path):
    make_lava_report(tmp_path)
    (tmp_path / "_lava_data.lava").rename(tmp_path / "_lava_data.json")
    assert validate_leapp_directory(str(tmp_path)) is True


def test_validate_missing_manifest(tmp_path):
    make_lava_report(tmp_path)
    (tmp_path / "_lava_data.lava").unlink()
    assert validate_leapp_directory(str(tmp_path)) is False


def test_validate_missing_db(tmp_path):
    make_lava_report(tmp_path)
    (tmp_path / "_lava_artifacts.db").unlink()
    assert validate_leapp_directory(str(tmp_path)) is False


def test_sha256_file(tmp_path):
    file_path = tmp_path / "sample.bin"
    file_path.write_bytes(b"forensic evidence\n")
    assert sha256_file(str(file_path)) == hashlib.sha256(b"forensic evidence\n").hexdigest()


def test_incomplete_report_fails(tmp_db, tmp_path, monkeypatch):
    make_lava_report(tmp_path, complete=False)
    monkeypatch.setattr(processing_utils, "embed_job_data", lambda job: None)

    insert_report_metadata("job_incomplete", str(tmp_path))
    process_leapp_report("job_incomplete", str(tmp_path))

    with get_db_cursor() as cursor:
        cursor.execute("SELECT status, error_message FROM reports WHERE job_name = 'job_incomplete'")
        status, error_message = cursor.fetchone()

    assert status == "failed"
    assert "processing_status" in error_message


def test_process_report_hashes_and_stores_catalog(tmp_db, tmp_path, monkeypatch):
    make_lava_report(tmp_path)
    settings_service.set_disable_embedding(True)
    monkeypatch.setattr(processing_utils, "embed_job_data", lambda job: None)

    insert_report_metadata("job_test", str(tmp_path))
    process_leapp_report("job_test", str(tmp_path))

    with get_db_cursor() as cursor:
        cursor.execute("SELECT file_name, sha256 FROM ingested_files WHERE job_name = 'job_test'")
        hashes = {row[0]: row[1] for row in cursor.fetchall()}

        cursor.execute("SELECT status, leapp_version FROM reports WHERE job_name = 'job_test'")
        status, leapp_version = cursor.fetchone()

        cursor.execute("""
            SELECT category, artifact_name, tablename, description, record_count, column_map, object_columns
            FROM artifact_catalog WHERE job_name = 'job_test' ORDER BY tablename
        """)
        catalog = cursor.fetchall()

    assert status == "completed"
    assert leapp_version == "2.3.0"

    # Exactly the two LAVA files are hashed
    assert set(hashes.keys()) == {"_lava_artifacts.db", "_lava_data.lava"}
    db_path = tmp_path / "_lava_artifacts.db"
    assert hashes["_lava_artifacts.db"] == hashlib.sha256(db_path.read_bytes()).hexdigest()

    assert len(catalog) == 2
    call_history = catalog[0]
    assert call_history[0] == "Call History"
    assert call_history[2] == "callhistory"
    assert call_history[3] == "Call logs from CallHistory.storedata"
    assert call_history[4] == 3
    assert json.loads(call_history[5])["phone_number"] == "Phone Number"
    assert {"name": "starting_timestamp", "type": "datetime"} in json.loads(call_history[6])


def test_process_report_accepts_json_manifest(tmp_db, tmp_path, monkeypatch):
    make_lava_report(tmp_path)
    (tmp_path / "_lava_data.lava").rename(tmp_path / "_lava_data.json")
    settings_service.set_disable_embedding(True)
    monkeypatch.setattr(processing_utils, "embed_job_data", lambda job: None)

    insert_report_metadata("job_json", str(tmp_path))
    process_leapp_report("job_json", str(tmp_path))

    with get_db_cursor() as cursor:
        cursor.execute("SELECT file_name FROM ingested_files WHERE job_name = 'job_json'")
        hashed = {row[0] for row in cursor.fetchall()}
        cursor.execute("SELECT status FROM reports WHERE job_name = 'job_json'")
        status = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM artifact_catalog WHERE job_name = 'job_json'")
        catalog_count = cursor.fetchone()[0]

    assert status == "completed"
    assert hashed == {"_lava_artifacts.db", "_lava_data.json"}
    assert catalog_count == 2


def test_embedding_gated_by_setting(tmp_db, tmp_path, monkeypatch):
    make_lava_report(tmp_path)
    embed_calls = []
    monkeypatch.setattr(processing_utils, "embed_job_data", lambda job: embed_calls.append(job))

    settings_service.set_disable_embedding(True)
    insert_report_metadata("job_skip", str(tmp_path))
    process_leapp_report("job_skip", str(tmp_path))
    assert embed_calls == []

    settings_service.set_disable_embedding(False)
    insert_report_metadata("job_embed", str(tmp_path))
    process_leapp_report("job_embed", str(tmp_path))
    assert embed_calls == ["job_embed"]
