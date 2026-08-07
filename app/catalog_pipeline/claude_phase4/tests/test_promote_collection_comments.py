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
)
from app.catalog_pipeline.claude_phase4.tests.fixtures import (
    create_fixture_db,
    add_collections_tables,
    insert_collection,
)


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
    inserted = insert_collection_comments(conn, "modio", f, "deadbeef", lookup)
    conn.commit()
    assert inserted == 1
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
    inserted = insert_collection_comments(conn, "modio", f, "deadbeef", lookup)
    assert inserted == 0
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
