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