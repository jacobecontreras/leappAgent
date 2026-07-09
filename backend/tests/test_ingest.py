import hashlib

from database.database import get_db_cursor, insert_report_metadata
from services.settings_service import settings_service
from utils import processing_utils
from utils.hash_utils import sha256_file
from utils.processing_utils import validate_leapp_directory, process_leapp_report

from test_parsers import make_timeline_db


def make_leapp_report(tmp_path):
    tsv_dir = tmp_path / "_TSV Exports"
    tsv_dir.mkdir()
    (tsv_dir / "Contacts.tsv").write_text("Name\tPhone\nAlice\t555-0100\n")

    timeline_dir = tmp_path / "_Timeline"
    timeline_dir.mkdir()
    make_timeline_db(str(timeline_dir / "tl.db"), [("k1", "App Usage", "data")])
    return tmp_path


def test_validate_without_kml_exports(tmp_path):
    make_leapp_report(tmp_path)
    assert validate_leapp_directory(str(tmp_path)) is True


def test_validate_missing_dirs(tmp_path):
    (tmp_path / "_TSV Exports").mkdir()
    assert validate_leapp_directory(str(tmp_path)) is False


def test_sha256_file(tmp_path):
    file_path = tmp_path / "sample.tsv"
    file_path.write_bytes(b"forensic evidence\n")
    assert sha256_file(str(file_path)) == hashlib.sha256(b"forensic evidence\n").hexdigest()


def test_process_report_hashes_and_skips_embedding(tmp_db, tmp_path, monkeypatch):
    make_leapp_report(tmp_path)
    settings_service.set_disable_embedding(True)
    embed_calls = []
    monkeypatch.setattr(processing_utils, "embed_job_data", lambda job: embed_calls.append(job))

    insert_report_metadata("job_test", str(tmp_path))
    process_leapp_report("job_test", str(tmp_path))

    with get_db_cursor() as cursor:
        cursor.execute("SELECT file_name, sha256, size_bytes FROM ingested_files WHERE job_name = 'job_test'")
        rows = {row[0]: (row[1], row[2]) for row in cursor.fetchall()}

        cursor.execute("SELECT status FROM reports WHERE job_name = 'job_test'")
        status = cursor.fetchone()[0]

    assert status == "completed"
    assert set(rows.keys()) == {"Contacts.tsv", "tl.db"}

    tsv_path = tmp_path / "_TSV Exports" / "Contacts.tsv"
    expected_hash = hashlib.sha256(tsv_path.read_bytes()).hexdigest()
    assert rows["Contacts.tsv"] == (expected_hash, tsv_path.stat().st_size)

    assert embed_calls == []


def test_process_report_embeds_when_enabled(tmp_db, tmp_path, monkeypatch):
    make_leapp_report(tmp_path)
    settings_service.set_disable_embedding(False)

    embed_calls = []
    monkeypatch.setattr(processing_utils, "embed_job_data", lambda job: embed_calls.append(job))

    insert_report_metadata("job_embed", str(tmp_path))
    process_leapp_report("job_embed", str(tmp_path))

    assert embed_calls == ["job_embed"]
