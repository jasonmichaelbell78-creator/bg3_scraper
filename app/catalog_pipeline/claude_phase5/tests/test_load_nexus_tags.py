# app/catalog_pipeline/claude_phase5/tests/test_load_nexus_tags.py
import json
import sqlite3

import pytest

from app.catalog_pipeline.claude_phase5.load_nexus_tags import (
    parse_tags_line,
    load_nexus_listing_lookup,
)
from app.catalog_pipeline.claude_phase5.tests.fixtures import (
    create_fixture_db,
    insert_listing,
)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    create_fixture_db(c)
    yield c
    c.close()


def test_parse_tags_line_extracts_fields():
    line = json.dumps({"nexus_mod_id": 24291, "tags": ["Photo Mode", "Patch 8 Compatible"], "_fetched_at": "x"})
    parsed = parse_tags_line(line)
    assert parsed == {"nexus_mod_id": "24291", "tags": ["Photo Mode", "Patch 8 Compatible"]}


def test_parse_tags_line_handles_empty_tags_list():
    line = json.dumps({"nexus_mod_id": 100, "tags": [], "_fetched_at": "x"})
    parsed = parse_tags_line(line)
    assert parsed == {"nexus_mod_id": "100", "tags": []}


def test_load_nexus_listing_lookup_only_includes_nexus_platform(conn):
    insert_listing(conn, 1, "nexus", "24291")
    insert_listing(conn, 2, "modio", "5000")
    conn.commit()
    lookup = load_nexus_listing_lookup(conn)
    assert lookup == {"24291": 1}

from app.catalog_pipeline.claude_phase5.load_nexus_tags import insert_nexus_tags


def test_insert_nexus_tags_inserts_all_tags_for_mapped_mod(conn, tmp_path):
    insert_listing(conn, 1, "nexus", "24291")
    conn.commit()
    f = tmp_path / "tags.jsonl"
    f.write_text(json.dumps({"nexus_mod_id": 24291, "tags": ["A", "B"], "_fetched_at": "x"}) + "\n")

    lookup = load_nexus_listing_lookup(conn)
    counts = insert_nexus_tags(conn, f, lookup)
    conn.commit()

    assert counts == {
        "mods_seen": 1,
        "tags_inserted": 2,
        "skipped_unmapped_mods": 0,
        "skipped_duplicate_tags": 0,
    }
    rows = conn.execute("SELECT listing_id, tag FROM platform_tags ORDER BY tag").fetchall()
    assert rows == [(1, "A"), (1, "B")]


def test_insert_nexus_tags_skips_unmapped_mod(conn, tmp_path):
    # no matching platform_listings row inserted at all
    f = tmp_path / "tags.jsonl"
    f.write_text(json.dumps({"nexus_mod_id": 99999, "tags": ["A"], "_fetched_at": "x"}) + "\n")

    lookup = load_nexus_listing_lookup(conn)
    counts = insert_nexus_tags(conn, f, lookup)

    assert counts["tags_inserted"] == 0
    assert counts["skipped_unmapped_mods"] == 1
    assert conn.execute("SELECT COUNT(*) FROM platform_tags").fetchone()[0] == 0


def test_insert_nexus_tags_skips_duplicate_tag_within_file(conn, tmp_path):
    insert_listing(conn, 1, "nexus", "24291")
    conn.commit()
    f = tmp_path / "tags.jsonl"
    # Same mod appears twice in the source file with an overlapping tag --
    # simulates a messy/overlapping fetch rather than assuming the source is clean.
    f.write_text(
        json.dumps({"nexus_mod_id": 24291, "tags": ["A", "B"], "_fetched_at": "x"}) + "\n"
        + json.dumps({"nexus_mod_id": 24291, "tags": ["B", "C"], "_fetched_at": "y"}) + "\n"
    )

    lookup = load_nexus_listing_lookup(conn)
    counts = insert_nexus_tags(conn, f, lookup)

    assert counts["mods_seen"] == 2
    assert counts["tags_inserted"] == 3  # A, B, C -- second B skipped
    assert counts["skipped_duplicate_tags"] == 1
    rows = conn.execute("SELECT tag FROM platform_tags ORDER BY tag").fetchall()
    assert rows == [("A",), ("B",), ("C",)]


def test_insert_nexus_tags_blank_lines_ignored(conn, tmp_path):
    insert_listing(conn, 1, "nexus", "24291")
    conn.commit()
    f = tmp_path / "tags.jsonl"
    f.write_text("\n" + json.dumps({"nexus_mod_id": 24291, "tags": [], "_fetched_at": "x"}) + "\n\n")

    lookup = load_nexus_listing_lookup(conn)
    counts = insert_nexus_tags(conn, f, lookup)
    assert counts["mods_seen"] == 1
    assert counts["tags_inserted"] == 0


import hashlib

from app.catalog_pipeline.claude_phase5.load_nexus_tags import run_migration
from app.catalog_pipeline.claude_phase5.tests.fixtures import insert_existing_tag


def _sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        digest.update(fh.read())
    return digest.hexdigest()


@pytest.fixture
def db_and_source(tmp_path):
    db_path = tmp_path / "candidate.db"
    conn = sqlite3.connect(str(db_path))
    create_fixture_db(conn)
    insert_listing(conn, 1, "nexus", "24291")
    insert_listing(conn, 2, "modio", "5000")
    insert_existing_tag(conn, 2, "Existing ModIO Tag")  # pre-existing unrelated data
    conn.commit()
    conn.close()

    tags_path = tmp_path / "tags.jsonl"
    tags_path.write_text(json.dumps({"nexus_mod_id": 24291, "tags": ["Patch 8 Compatible"], "_fetched_at": "x"}) + "\n")
    return db_path, tags_path


def test_run_migration_full_run_inserts_rows(db_and_source):
    db_path, tags_path = db_and_source
    sha256 = _sha256_of(db_path)
    receipt = run_migration(db_path, sha256, tags_path)

    assert receipt["tags_inserted"] == 1
    assert receipt["platform_tags_rows_before"] == 1  # the pre-existing mod.io row
    assert receipt["platform_tags_rows_after"] == 2

    conn = sqlite3.connect(str(db_path))
    row = conn.execute("SELECT listing_id, tag FROM platform_tags WHERE listing_id = 1").fetchone()
    conn.close()
    assert row == (1, "Patch 8 Compatible")


def test_run_migration_hash_mismatch_raises(db_and_source):
    db_path, tags_path = db_and_source
    with pytest.raises(ValueError):
        run_migration(db_path, "wrong-hash-deadbeef", tags_path)


def test_run_migration_second_run_raises_integrity_error(db_and_source):
    db_path, tags_path = db_and_source
    first_sha256 = _sha256_of(db_path)
    run_migration(db_path, first_sha256, tags_path)

    second_sha256 = _sha256_of(db_path)
    with pytest.raises(sqlite3.IntegrityError):
        run_migration(db_path, second_sha256, tags_path)


def test_run_migration_writes_migration_history_row(db_and_source):
    db_path, tags_path = db_and_source
    sha256 = _sha256_of(db_path)
    run_migration(db_path, sha256, tags_path)

    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT migration_name, schema_version, row_count_before, row_count_after "
        "FROM migration_history WHERE migration_name = 'b26-phase5-nexus-tags'"
    ).fetchone()
    conn.close()
    assert row == ("b26-phase5-nexus-tags", "phase5", "1", "2")


def test_run_migration_rolls_back_on_malformed_source_line(db_and_source):
    db_path, tags_path = db_and_source
    # Second line is invalid JSON -- must abort the whole transaction, not
    # partially insert the first (valid) line before failing.
    tags_path.write_text(
        json.dumps({"nexus_mod_id": 24291, "tags": ["Patch 8 Compatible"], "_fetched_at": "x"}) + "\n"
        + "{not valid json\n"
    )
    sha256 = _sha256_of(db_path)

    with pytest.raises(json.JSONDecodeError):
        run_migration(db_path, sha256, tags_path)

    conn = sqlite3.connect(str(db_path))
    count = conn.execute("SELECT COUNT(*) FROM platform_tags").fetchone()[0]
    history_count = conn.execute(
        "SELECT COUNT(*) FROM migration_history WHERE migration_name = 'b26-phase5-nexus-tags'"
    ).fetchone()[0]
    conn.close()
    # Only the pre-existing mod.io row survives -- the attempted Nexus insert
    # and the migration_history claim row were both rolled back.
    assert count == 1
    assert history_count == 0