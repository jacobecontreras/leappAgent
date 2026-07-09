import sqlite3

import parsers.leapp_db_parser as leapp_db_parser
from parsers.tsv_parser import parse_tsv_directory
from parsers.leapp_db_parser import parse_timeline_db


def make_timeline_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE data (key TEXT, activity TEXT, datalist TEXT)")
    conn.executemany("INSERT INTO data VALUES (?, ?, ?)", rows)
    conn.commit()
    conn.close()


def test_parse_tsv_directory(tmp_path):
    (tmp_path / "Contacts.tsv").write_text("Name\tPhone\nAlice\t555-0100\nBob\t555-0101\n")
    (tmp_path / "notes.txt").write_text("ignored")

    data = parse_tsv_directory(str(tmp_path))
    assert list(data.keys()) == ["Contacts.tsv"]
    assert data["Contacts.tsv"][0] == {"Name": "Alice", "Phone": "555-0100"}
    assert len(data["Contacts.tsv"]) == 2


def test_parse_timeline_db(tmp_path):
    db_path = tmp_path / "tl.db"
    make_timeline_db(str(db_path), [("k1", "App Usage", "some data")])

    events = parse_timeline_db(str(db_path))
    assert events == [{"key": "k1", "activity": "App Usage", "datalist": "some data", "source_artifact": "tl.db"}]


def test_parse_timeline_db_missing_file(tmp_path):
    assert parse_timeline_db(str(tmp_path / "missing.db")) == []


def test_spatial_parser_removed():
    assert not hasattr(leapp_db_parser, "parse_spatial_db")
