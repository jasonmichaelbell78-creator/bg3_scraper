import sqlite3
import pytest

from app.catalog_pipeline.claude_phase4.fix_mod_comments_view import rebuild_mod_comments_view
from app.catalog_pipeline.claude_phase4.tests.fixtures import (
    create_fixture_db,
    insert_corpus,
    insert_comment,
    insert_corpus as _ic,
)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    create_fixture_db(c)
    yield c
    c.close()


def test_superseded_corpus_rows_excluded_after_fix(conn):
    insert_corpus(conn, "buggy", "modio", "modio_fullsweep_comments_2026-07-10")
    insert_corpus(conn, "fixed", "modio", "modio_comments_deep_refresh_2026-07-21", supersedes="buggy")
    insert_comment(conn, "c1", "buggy", "100")
    insert_comment(conn, "c2", "fixed", "100")
    conn.commit()

    before = conn.execute("SELECT COUNT(*) FROM mod_comments").fetchone()[0]
    assert before == 2  # bug reproduced: both rows visible pre-fix

    rebuild_mod_comments_view(conn)

    after = conn.execute("SELECT COUNT(*) FROM mod_comments").fetchone()[0]
    assert after == 1
    remaining = conn.execute("SELECT comment_uuid FROM mod_comments").fetchone()[0]
    assert remaining == "c2"


def test_non_superseded_corpus_rows_untouched(conn):
    insert_corpus(conn, "solo", "nexus", "nexus_comments_merged_phase3_promotion_2026-08")
    insert_comment(conn, "c3", "solo", "200")
    conn.commit()

    rebuild_mod_comments_view(conn)

    after = conn.execute("SELECT COUNT(*) FROM mod_comments").fetchone()[0]
    assert after == 1


def test_chained_supersession_excludes_every_superseded_corpus(conn):
    # corpus A superseded by B, B superseded by C -- A and B both excluded, C kept
    insert_corpus(conn, "a", "modio", "v1")
    insert_corpus(conn, "b", "modio", "v2", supersedes="a")
    insert_corpus(conn, "c", "modio", "v3", supersedes="b")
    insert_comment(conn, "ca", "a", "1")
    insert_comment(conn, "cb", "b", "1")
    insert_comment(conn, "cc", "c", "1")
    conn.commit()

    rebuild_mod_comments_view(conn)

    remaining = {r[0] for r in conn.execute("SELECT comment_uuid FROM mod_comments")}
    assert remaining == {"cc"}
