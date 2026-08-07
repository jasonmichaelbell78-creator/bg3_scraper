import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from app.catalog_pipeline.claude_phase4.promote_collection_comments import (
    build_collection_comment_uuid,
    load_collection_lookup,
    parse_modio_comment_line,
    parse_nexus_comment_line,
    insert_collection_comments,
    run_migration,
)
from app.catalog_pipeline.claude_phase4.tests.fixtures import (
    create_fixture_db,
    add_collections_tables,
    add_catalog_collections_table,
    insert_collection,
)


def _sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        digest.update(fh.read())
    return digest.hexdigest()


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    create_fixture_db(c)
    add_collections_tables(c)
    yield c
    c.close()


def test_build_collection_comment_uuid_deterministic():
    a = build_collection_comment_uuid("modio", "2498", "1739146")
    b = build_collection_comment_uuid("modio", "2498", "1739146")
    c = build_collection_comment_uuid("modio", "2498", "999999")
    assert a == b
    assert a != c


def test_parse_modio_comment_line_skips_sentinel():
    line = json.dumps({"collection_id": 55, "_status": "no_comments"})
    assert parse_modio_comment_line(line) is None


def test_parse_modio_comment_line_extracts_real_comment():
    line = json.dumps(
        {
            "collection_id": 2498,
            "id": 1739146,
            "reply_id": 1724844,
            "date_added": 1782165590,
            "content": "Thank you for your response !",
            "user": {"id": 35831440, "username": "Lvmbda"},
        }
    )
    parsed = parse_modio_comment_line(line)
    assert parsed["collection_native_id"] == "2498"
    assert parsed["source_comment_id"] == "1739146"
    assert parsed["parent_source_comment_id"] == "1724844"
    assert parsed["body"] == "Thank you for your response !"
    assert parsed["author_display_name"] == "Lvmbda"
    assert parsed["author_user_id"] == "35831440"


def test_parse_nexus_comment_line_skips_sentinel():
    line = json.dumps({"collection_slug": "bvfixx", "_status": "no_comments"})
    assert parse_nexus_comment_line(line) is None


def test_parse_nexus_comment_line_extracts_real_comment():
    line = json.dumps(
        {
            "collection_slug": "bvfixx",
            "comment_id": "50814",
            "body": "test body",
            "created_at": "2023-10-05T23:39:09Z",
            "creator_name": "SKYRIMAN123",
            "parent_comment_id": None,
        }
    )
    parsed = parse_nexus_comment_line(line)
    assert parsed["collection_native_id"] == "bvfixx"
    assert parsed["source_comment_id"] == "50814"
    assert parsed["parent_source_comment_id"] is None
    assert parsed["body"] == "test body"
    assert parsed["author_display_name"] == "SKYRIMAN123"


def test_load_collection_lookup(conn):
    insert_collection(conn, "u1", "modio", "2498")
    insert_collection(conn, "u2", "nexus", "bvfixx")
    conn.commit()
    lookup = load_collection_lookup(conn)
    assert lookup[("modio", "2498")] == "u1"
    assert lookup[("nexus", "bvfixx")] == "u2"


def test_insert_collection_comments_modio(conn, tmp_path):
    insert_collection(conn, "u1", "modio", "2498")
    conn.commit()
    f = tmp_path / "modio_comments.jsonl"
    f.write_text(
        json.dumps({"collection_id": 55, "_status": "no_comments"}) + "\n"
        + json.dumps(
            {
                "collection_id": 2498,
                "id": 1739146,
                "reply_id": None,
                "date_added": 1782165590,
                "content": "hello",
                "user": {"id": 1, "username": "a"},
            }
        )
        + "\n"
    )
    lookup = load_collection_lookup(conn)
    inserted, skipped_unmapped = insert_collection_comments(conn, "modio", f, "deadbeef", lookup)
    conn.commit()
    assert inserted == 1
    assert skipped_unmapped == 0
    row = conn.execute(
        "SELECT collection_uuid, source_comment_id, body FROM catalog_collection_comments"
    ).fetchone()
    assert row == ("u1", "1739146", "hello")


def test_insert_collection_comments_skips_unmapped_collection(conn, tmp_path):
    # no matching catalog_collections row inserted at all
    f = tmp_path / "modio_comments.jsonl"
    f.write_text(
        json.dumps(
            {"collection_id": 9999, "id": 1, "content": "x", "user": {"id": 1, "username": "a"}}
        )
        + "\n"
    )
    lookup = load_collection_lookup(conn)
    inserted, skipped_unmapped = insert_collection_comments(conn, "modio", f, "deadbeef", lookup)
    assert inserted == 0
    assert skipped_unmapped == 1
    assert conn.execute("SELECT COUNT(*) FROM catalog_collection_comments").fetchone()[0] == 0


def test_insert_collection_comments_idempotent(conn, tmp_path):
    insert_collection(conn, "u1", "modio", "2498")
    conn.commit()
    f = tmp_path / "modio_comments.jsonl"
    f.write_text(
        json.dumps(
            {"collection_id": 2498, "id": 1, "content": "x", "user": {"id": 1, "username": "a"}}
        )
        + "\n"
    )
    lookup = load_collection_lookup(conn)
    insert_collection_comments(conn, "modio", f, "deadbeef", lookup)
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        insert_collection_comments(conn, "modio", f, "deadbeef", lookup)


@pytest.fixture
def db_and_sources(tmp_path):
    db_path = tmp_path / "candidate.db"
    conn = sqlite3.connect(str(db_path))
    create_fixture_db(conn)
    add_catalog_collections_table(conn)
    insert_collection(conn, "u1", "modio", "2498")
    insert_collection(conn, "u2", "nexus", "bvfixx")
    conn.commit()
    conn.close()

    modio_path = tmp_path / "modio_comments.jsonl"
    modio_path.write_text(
        json.dumps(
            {"collection_id": 2498, "id": 1, "content": "hi", "user": {"id": 1, "username": "a"}}
        )
        + "\n"
    )
    nexus_path = tmp_path / "nexus_comments.jsonl"
    nexus_path.write_text(
        json.dumps({"collection_slug": "bvfixx", "comment_id": "500", "body": "hey"}) + "\n"
    )
    return db_path, modio_path, nexus_path


def test_run_migration_full_run_inserts_rows(db_and_sources):
    db_path, modio_path, nexus_path = db_and_sources
    sha256 = _sha256_of(db_path)
    receipt = run_migration(db_path, sha256, modio_path, nexus_path)
    assert receipt["modio_rows_inserted"] == 1
    assert receipt["nexus_rows_inserted"] == 1

    conn = sqlite3.connect(str(db_path))
    count = conn.execute("SELECT COUNT(*) FROM catalog_collection_comments").fetchone()[0]
    conn.close()
    assert count == 2


def test_run_migration_second_run_raises_integrity_error(db_and_sources):
    db_path, modio_path, nexus_path = db_and_sources
    first_sha256 = _sha256_of(db_path)
    run_migration(db_path, first_sha256, modio_path, nexus_path)

    second_sha256 = _sha256_of(db_path)
    with pytest.raises(sqlite3.IntegrityError):
        run_migration(db_path, second_sha256, modio_path, nexus_path)


def test_run_migration_second_run_does_not_change_row_counts(db_and_sources):
    db_path, modio_path, nexus_path = db_and_sources
    first_sha256 = _sha256_of(db_path)
    run_migration(db_path, first_sha256, modio_path, nexus_path)

    conn = sqlite3.connect(str(db_path))
    before_retry = conn.execute("SELECT COUNT(*) FROM catalog_collection_comments").fetchone()[0]
    conn.close()

    second_sha256 = _sha256_of(db_path)
    with pytest.raises(sqlite3.IntegrityError):
        run_migration(db_path, second_sha256, modio_path, nexus_path)

    conn = sqlite3.connect(str(db_path))
    after_retry = conn.execute("SELECT COUNT(*) FROM catalog_collection_comments").fetchone()[0]
    conn.close()
    assert after_retry == before_retry == 2


def test_run_migration_writes_migration_history_row(db_and_sources):
    db_path, modio_path, nexus_path = db_and_sources
    sha256 = _sha256_of(db_path)
    run_migration(db_path, sha256, modio_path, nexus_path)

    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT migration_name, schema_version, row_count_before, row_count_after "
        "FROM migration_history WHERE migration_name = 'b26-phase4-collection-comments'"
    ).fetchone()
    conn.close()
    assert row == ("b26-phase4-collection-comments", "phase4", "0", "2")
