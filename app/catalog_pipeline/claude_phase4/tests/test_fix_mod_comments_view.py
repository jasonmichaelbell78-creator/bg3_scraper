import hashlib
import sqlite3
import pytest

from app.catalog_pipeline.claude_phase4.fix_mod_comments_view import rebuild_mod_comments_view, run_fix
from app.catalog_pipeline.claude_phase4.tests.fixtures import (
    create_fixture_db,
    insert_corpus,
    insert_comment,
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


@pytest.fixture
def db_file(tmp_path):
    path = tmp_path / "candidate.db"
    conn = sqlite3.connect(str(path))
    create_fixture_db(conn)
    insert_corpus(conn, "buggy", "modio", "modio_fullsweep_comments_2026-07-10")
    insert_corpus(conn, "fixed", "modio", "modio_comments_deep_refresh_2026-07-21", supersedes="buggy")
    insert_comment(conn, "c1", "buggy", "100")
    insert_comment(conn, "c2", "fixed", "100")
    conn.commit()
    conn.close()
    return path


def test_run_fix_second_run_raises_integrity_error(db_file):
    first_sha256 = _sha256_of(db_file)
    run_fix(db_file, first_sha256)

    second_sha256 = _sha256_of(db_file)
    with pytest.raises(sqlite3.IntegrityError):
        run_fix(db_file, second_sha256)


def test_run_fix_second_run_does_not_change_row_counts(db_file):
    first_sha256 = _sha256_of(db_file)
    run_fix(db_file, first_sha256)

    conn = sqlite3.connect(str(db_file))
    before_retry = conn.execute("SELECT COUNT(*) FROM mod_comments").fetchone()[0]
    conn.close()

    second_sha256 = _sha256_of(db_file)
    with pytest.raises(sqlite3.IntegrityError):
        run_fix(db_file, second_sha256)

    conn = sqlite3.connect(str(db_file))
    after_retry = conn.execute("SELECT COUNT(*) FROM mod_comments").fetchone()[0]
    conn.close()
    assert after_retry == before_retry == 1


def test_run_fix_writes_migration_history_row(db_file):
    first_sha256 = _sha256_of(db_file)
    run_fix(db_file, first_sha256)

    conn = sqlite3.connect(str(db_file))
    row = conn.execute(
        "SELECT migration_name, schema_version, row_count_before, row_count_after "
        "FROM migration_history WHERE migration_name = 'b26-phase4-mod-comments-view-fix'"
    ).fetchone()
    conn.close()
    assert row == ("b26-phase4-mod-comments-view-fix", "phase4", "2", "1")
