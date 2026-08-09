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