# B26 Phase 4: Comment Dedup Fix + Collection Comments Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the two DB-completeness gaps found during the 2026-08-07 audit of `catalog/B26/BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db`: (1) `mod_comments` currently double-counts ~56K superseded mod.io comments because the view ignores `evidence_corpora.supersedes_corpus_uuid`, and (2) Collections' own comment threads (157 real mod.io + 4,965 real Nexus comments) were captured in the 2026-07-24 sweep but never migrated into the DB at all.

**Architecture:** Two independent, additive migrations against the same candidate DB, following the B26 Phase 3 pattern (`app/catalog_pipeline/claude_phase3/promote_comment_evidence.py`): hash-gate the DB first, back it up, run inside one transaction, verify post-commit, write a JSON receipt. Task 1 replaces one view (no new tables). Task 2 adds one new table (`catalog_collection_comments`) — kept separate from `evidence_source_records`/`platform_listings` because collection comments key off `catalog_collections`, not mod listings, and Collections already has its own dedicated `catalog_*` tables rather than being folded into the generic evidence schema.

**Tech Stack:** Python 3, stdlib `sqlite3`, `pytest`. No new dependencies.

## Global Constraints

- Never modify `catalog/B26/*.db` without a `.pre-phaseN-backup` copy first (same rule Phase 3 followed) — `catalog/` is gitignored, so a bad run isn't recoverable from git.
- Both migrations must be idempotent: a second run against an already-migrated DB must fail cleanly (`IntegrityError` from a `UNIQUE` constraint), not silently duplicate rows or silently no-op.
  **Correction 2026-08-07 (final review), superseded 2026-08-07 (Qodo PR review):** the final review found `run_migration()`'s real double-run failure was `OperationalError: table already exists`, not the stated `IntegrityError` -- and this file was first updated to just document that mismatch rather than fix it. An automated PR review (Qodo) correctly flagged that as leaving the actual stated contract broken, not just mis-described, and pointed at this project's existing `migration_history` table (`migration_name TEXT UNIQUE NOT NULL`, already used by Phase 3 for exactly this) as the fix. Both `run_fix()` and `run_migration()` now insert a `migration_history` row with a fixed `migration_name` as the *first* write inside their transaction, before any schema change -- a rerun hits `IntegrityError` on that insert deterministically, restoring the original contract for real (verified via `test_run_fix_second_run_raises_integrity_error` and `test_run_migration_second_run_raises_integrity_error`) rather than just correcting the sentence describing it. Both scripts also gained `PRAGMA foreign_keys = ON` in the same pass (Qodo's other finding), matching Phase 3's own pattern, which they'd omitted.
- Reuse `sha256_file`, `verify_db_hash`, and `backup_database` from `app.catalog_pipeline.claude_phase3.promote_comment_evidence` rather than reimplementing them (DRY — Phase 3 already built and tested these).
- Source files are read-only inputs, never modified: `data/collections/modio/modio_collections_comments.jsonl` (sha256 `8254971d357a878c9223cb442e08f7141ec88210f08c9e12b177e5478e0de31d`, 968 lines, 811 `_status:"no_comments"` sentinels + 157 real comments) and `data/collections/nexus/nexus_collections_comments.jsonl` (sha256 `0cdb38f54e419b7ed54705ef831771bb668602be68edd7b3b3849f6474179354`, 4999 lines, 34 sentinels + 4965 real comments).
- Both tasks operate on `catalog/B26/BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db` — confirm its current sha256 with `sha256sum` immediately before running either migration for real, and abort on mismatch (per this project's standing "never proceed past an unexplained checksum mismatch" rule, see CLAUDE.md's B26 Phase 3 section).

---

## Task 1: Fix `mod_comments` to respect corpus supersession

**Files:**
- Create: `app/catalog_pipeline/claude_phase4/__init__.py`
- Create: `app/catalog_pipeline/claude_phase4/fix_mod_comments_view.py`
- Create: `app/catalog_pipeline/claude_phase4/tests/__init__.py`
- Create: `app/catalog_pipeline/claude_phase4/tests/fixtures.py`
- Create: `app/catalog_pipeline/claude_phase4/tests/test_fix_mod_comments_view.py`

**Interfaces:**
- Consumes: `sha256_file(path: Path) -> str`, `verify_db_hash(db_path: Path, expected_sha256: str) -> None`, `backup_database(db_path: Path) -> Path` from `app.catalog_pipeline.claude_phase3.promote_comment_evidence`.
- Produces: `rebuild_mod_comments_view(conn: sqlite3.Connection) -> None` — drops and recreates the view. `run_fix(db_path: Path, expected_sha256: str) -> dict` — full pipeline, returns a receipt dict with keys `pre_migration_sha256`, `backup_path`, `modio_rows_before`, `modio_rows_after`, `nexus_rows_before`, `nexus_rows_after`, `post_migration_sha256`. Later tasks/scripts don't depend on this task's output, so no further interface constraints.

- [ ] **Step 1: Write the fixture schema for this task's tests**

`app/catalog_pipeline/claude_phase4/tests/fixtures.py`:

```python
"""Shared SQLite fixture schema for B26 Phase 4 tests."""
import sqlite3


def create_fixture_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE evidence_corpora (
          corpus_uuid TEXT PRIMARY KEY,
          provider TEXT NOT NULL,
          object_scope TEXT NOT NULL,
          capture_label TEXT NOT NULL,
          captured_started_at TEXT,
          captured_finished_at TEXT,
          coverage_state TEXT NOT NULL,
          profile_label TEXT,
          record_count_raw INTEGER,
          record_count_unique INTEGER,
          limitation_notes TEXT NOT NULL,
          supersedes_corpus_uuid TEXT REFERENCES evidence_corpora(corpus_uuid)
        );

        CREATE TABLE evidence_source_records (
          source_record_uuid TEXT PRIMARY KEY,
          corpus_uuid TEXT NOT NULL REFERENCES evidence_corpora(corpus_uuid),
          provider_object_type TEXT NOT NULL,
          provider_native_id TEXT NOT NULL,
          source_listing_uuid TEXT,
          parent_provider_native_id TEXT,
          observed_at TEXT,
          displayed_author TEXT,
          version_text TEXT,
          content_sha256 TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          raw_locator TEXT NOT NULL,
          UNIQUE (corpus_uuid, provider_object_type, provider_native_id)
        );

        CREATE VIEW mod_comments AS
           SELECT
               esr.source_record_uuid AS comment_uuid,
               ec.provider AS platform,
               esr.provider_native_id AS source_comment_id,
               esr.source_listing_uuid AS listing_uuid,
               esr.parent_provider_native_id AS parent_source_comment_id,
               esr.displayed_author AS author,
               esr.observed_at AS observed_at,
               esr.payload_json AS payload_json
           FROM evidence_source_records esr
           JOIN evidence_corpora ec ON ec.corpus_uuid = esr.corpus_uuid
           WHERE esr.provider_object_type = 'comment';
        """
    )


def insert_corpus(conn, corpus_uuid, provider, capture_label, supersedes=None):
    conn.execute(
        """INSERT INTO evidence_corpora
           (corpus_uuid, provider, object_scope, capture_label, coverage_state,
            limitation_notes, supersedes_corpus_uuid)
           VALUES (?, ?, 'comments', ?, 'complete', 'test', ?)""",
        (corpus_uuid, provider, capture_label, supersedes),
    )


def insert_comment(conn, source_record_uuid, corpus_uuid, native_id):
    conn.execute(
        """INSERT INTO evidence_source_records
           (source_record_uuid, corpus_uuid, provider_object_type, provider_native_id,
            content_sha256, payload_json, raw_locator)
           VALUES (?, ?, 'comment', ?, 'x', '{}', 'x')""",
        (source_record_uuid, corpus_uuid, native_id),
    )
```

- [ ] **Step 2: Write the failing test**

`app/catalog_pipeline/claude_phase4/tests/test_fix_mod_comments_view.py`:

```python
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


def test_chained_supersession_only_excludes_directly_superseded(conn):
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /workspaces/bg3_scraper && python3 -m pytest app/catalog_pipeline/claude_phase4/tests/test_fix_mod_comments_view.py -v`
Expected: `ModuleNotFoundError: No module named 'app.catalog_pipeline.claude_phase4.fix_mod_comments_view'`

- [ ] **Step 4: Write the implementation**

`app/catalog_pipeline/claude_phase4/__init__.py` (empty file).

`app/catalog_pipeline/claude_phase4/fix_mod_comments_view.py`:

```python
"""
fix_mod_comments_view.py v1.0
==============================
B26 Phase 4, part 1: fixes mod_comments to respect evidence_corpora's own
supersedes_corpus_uuid column.

Found 2026-08-07: the corrected mod.io comment corpora
(modio_comments_base_under_page_limit_2026-07-21,
modio_comments_deep_refresh_2026-07-21) correctly declare
supersedes_corpus_uuid pointing at the buggy, ~100-comment-capped
modio_fullsweep_comments_2026-07-10 corpus -- but mod_comments never
filtered on that column, so all three corpora's rows surfaced at once:
132,276 mod.io rows in the view instead of the correct 76,043 (56,231 of
the buggy corpus's 56,233 rows are literal duplicates of rows already
present in the corrected corpora). This rebuilds the view to exclude any
corpus_uuid referenced by another corpus's supersedes_corpus_uuid, which
generalizes to any future supersession, not just this one.
"""
import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.catalog_pipeline.claude_phase3.promote_comment_evidence import (
    sha256_file,
    verify_db_hash,
    backup_database,
)

NEW_VIEW_SQL = """
CREATE VIEW mod_comments AS
   SELECT
       esr.source_record_uuid AS comment_uuid,
       ec.provider AS platform,
       esr.provider_native_id AS source_comment_id,
       esr.source_listing_uuid AS listing_uuid,
       esr.parent_provider_native_id AS parent_source_comment_id,
       esr.displayed_author AS author,
       esr.observed_at AS observed_at,
       esr.payload_json AS payload_json
   FROM evidence_source_records esr
   JOIN evidence_corpora ec ON ec.corpus_uuid = esr.corpus_uuid
   WHERE esr.provider_object_type = 'comment'
     AND ec.corpus_uuid NOT IN (
         SELECT supersedes_corpus_uuid FROM evidence_corpora
         WHERE supersedes_corpus_uuid IS NOT NULL
     )
"""


def rebuild_mod_comments_view(conn: sqlite3.Connection) -> None:
    conn.execute("DROP VIEW mod_comments")
    conn.execute(NEW_VIEW_SQL)


def run_fix(db_path: Path, expected_sha256: str) -> dict:
    verify_db_hash(db_path, expected_sha256)
    backup_path = backup_database(db_path)

    conn = sqlite3.connect(str(db_path))
    try:
        before = dict(
            conn.execute(
                "SELECT platform, COUNT(*) FROM mod_comments GROUP BY platform"
            ).fetchall()
        )
        rebuild_mod_comments_view(conn)
        after = dict(
            conn.execute(
                "SELECT platform, COUNT(*) FROM mod_comments GROUP BY platform"
            ).fetchall()
        )
        conn.commit()
    finally:
        conn.close()

    post_sha256 = sha256_file(db_path)
    receipt = {
        "migration_name": "b26-phase4-mod-comments-view-fix",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "pre_migration_sha256": expected_sha256,
        "backup_path": str(backup_path),
        "modio_rows_before": before.get("modio", 0),
        "modio_rows_after": after.get("modio", 0),
        "nexus_rows_before": before.get("nexus", 0),
        "nexus_rows_after": after.get("nexus", 0),
        "post_migration_sha256": post_sha256,
    }
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--candidate-sha256", required=True)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()

    receipt = run_fix(args.db, args.candidate_sha256)
    args.receipt.write_text(json.dumps(receipt, indent=2))
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /workspaces/bg3_scraper && python3 -m pytest app/catalog_pipeline/claude_phase4/tests/test_fix_mod_comments_view.py -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add app/catalog_pipeline/claude_phase4/__init__.py \
        app/catalog_pipeline/claude_phase4/fix_mod_comments_view.py \
        app/catalog_pipeline/claude_phase4/tests/__init__.py \
        app/catalog_pipeline/claude_phase4/tests/fixtures.py \
        app/catalog_pipeline/claude_phase4/tests/test_fix_mod_comments_view.py
git commit -m "B26 Phase 4: fix mod_comments view to respect corpus supersession"
```

---

## Task 2: Migrate Collections' own comment threads into the DB

**Files:**
- Create: `app/catalog_pipeline/claude_phase4/promote_collection_comments.py`
- Modify: `app/catalog_pipeline/claude_phase4/tests/fixtures.py` (add `catalog_collections` + new table)
- Create: `app/catalog_pipeline/claude_phase4/tests/test_promote_collection_comments.py`

**Interfaces:**
- Consumes: `sha256_file`, `verify_db_hash`, `backup_database` from Phase 3 (same as Task 1).
- Produces: `build_collection_comment_uuid(platform: str, collection_native_id: str, source_comment_id: str) -> str`, `load_collection_lookup(conn: sqlite3.Connection) -> dict[tuple[str, str], str]` (keyed by `(platform, collection_native_id)` → `collection_uuid`), `parse_modio_comment_line(line: str) -> dict | None` (returns `None` for `_status` sentinel lines), `parse_nexus_comment_line(line: str) -> dict | None`, `insert_collection_comments(conn, platform: str, filepath: Path, corpus_sha256: str, collection_lookup: dict) -> int` (returns rows inserted), `run_migration(db_path: Path, expected_sha256: str, modio_path: Path, nexus_path: Path) -> dict`.

- [ ] **Step 1: Extend the fixture with `catalog_collections` and the new table**

Add to `app/catalog_pipeline/claude_phase4/tests/fixtures.py`:

```python
def add_collections_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE catalog_collections (
            collection_uuid TEXT PRIMARY KEY,
            platform TEXT NOT NULL CHECK(platform IN ('modio', 'nexus')),
            collection_native_id TEXT NOT NULL,
            collection_slug TEXT,
            collection_name TEXT NOT NULL,
            UNIQUE(platform, collection_native_id)
        );

        CREATE TABLE catalog_collection_comments (
            comment_uuid TEXT PRIMARY KEY,
            collection_uuid TEXT NOT NULL REFERENCES catalog_collections(collection_uuid),
            platform TEXT NOT NULL CHECK(platform IN ('modio', 'nexus')),
            source_comment_id TEXT NOT NULL,
            parent_source_comment_id TEXT,
            author_display_name TEXT,
            author_user_id TEXT,
            observed_at TEXT,
            body TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            source_corpus_sha256 TEXT NOT NULL,
            source_line_number INTEGER NOT NULL,
            UNIQUE(platform, source_comment_id)
        );
        CREATE INDEX idx_catalog_collection_comments_collection
            ON catalog_collection_comments(collection_uuid, platform);
        """
    )


def insert_collection(conn, collection_uuid, platform, native_id, name="Test"):
    conn.execute(
        "INSERT INTO catalog_collections (collection_uuid, platform, collection_native_id, collection_slug, collection_name) VALUES (?, ?, ?, ?, ?)",
        (collection_uuid, platform, native_id, native_id, name),
    )
```

- [ ] **Step 2: Write the failing tests**

`app/catalog_pipeline/claude_phase4/tests/test_promote_collection_comments.py`:

```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /workspaces/bg3_scraper && python3 -m pytest app/catalog_pipeline/claude_phase4/tests/test_promote_collection_comments.py -v`
Expected: `ModuleNotFoundError: No module named 'app.catalog_pipeline.claude_phase4.promote_collection_comments'`

- [ ] **Step 4: Write the implementation**

`app/catalog_pipeline/claude_phase4/promote_collection_comments.py`:

```python
"""
promote_collection_comments.py v1.0
====================================
B26 Phase 4, part 2: migrates the mod.io and Nexus Collections comment
corpora (captured 2026-07-24, never previously loaded into the DB) into a
new catalog_collection_comments table, keyed to catalog_collections rather
than platform_listings -- collection comments aren't about a single mod.

Real counts (verified 2026-08-07 against the source files directly, not
assumed from prior documentation): data/collections/modio/
modio_collections_comments.jsonl has 968 lines, 811 of them "_status":
"no_comments" sentinels, leaving 157 real comments across 843 collections
(the 2026-07-24 CLAUDE.md entry's "968 real comment rows" figure was
actually the file's total line count, not the real-comment count --
corrected here). data/collections/nexus/nexus_collections_comments.jsonl
has 4999 lines, 34 sentinels, 4965 real comments across 87 collections.
"""
import argparse
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.catalog_pipeline.claude_phase3.promote_comment_evidence import (
    sha256_file,
    verify_db_hash,
    backup_database,
)


def build_collection_comment_uuid(platform: str, collection_native_id: str, source_comment_id: str) -> str:
    seed = f"bg3:phase4-collection-comment:{platform}:{collection_native_id}:{source_comment_id}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))


def parse_modio_comment_line(line: str):
    row = json.loads(line)
    if "_status" in row:
        return None
    user = row.get("user") or {}
    observed_at = None
    if row.get("date_added") is not None:
        observed_at = datetime.fromtimestamp(row["date_added"], tz=timezone.utc).isoformat()
    return {
        "collection_native_id": str(row["collection_id"]),
        "source_comment_id": str(row["id"]),
        "parent_source_comment_id": (
            str(row["reply_id"]) if row.get("reply_id") not in (None, 0) else None
        ),
        "author_display_name": user.get("username"),
        "author_user_id": str(user["id"]) if user.get("id") is not None else None,
        "observed_at": observed_at,
        "body": row.get("content") or "",
        "payload_json": json.dumps(row),
    }


def parse_nexus_comment_line(line: str):
    row = json.loads(line)
    if "_status" in row:
        return None
    return {
        "collection_native_id": row["collection_slug"],
        "source_comment_id": str(row["comment_id"]),
        "parent_source_comment_id": (
            str(row["parent_comment_id"]) if row.get("parent_comment_id") is not None else None
        ),
        "author_display_name": row.get("creator_name"),
        "author_user_id": None,
        "observed_at": row.get("created_at"),
        "body": row.get("body") or "",
        "payload_json": json.dumps(row),
    }


PARSERS = {"modio": parse_modio_comment_line, "nexus": parse_nexus_comment_line}


def load_collection_lookup(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        "SELECT platform, collection_native_id, collection_uuid FROM catalog_collections"
    ).fetchall()
    return {(platform, native_id): uid for platform, native_id, uid in rows}


def insert_collection_comments(
    conn: sqlite3.Connection,
    platform: str,
    filepath: Path,
    corpus_sha256: str,
    collection_lookup: dict,
) -> int:
    parser = PARSERS[platform]
    inserted = 0
    with open(filepath, "r", encoding="utf-8") as fh:
        for line_number, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            parsed = parser(line)
            if parsed is None:
                continue
            collection_uuid = collection_lookup.get((platform, parsed["collection_native_id"]))
            if collection_uuid is None:
                continue
            comment_uuid = build_collection_comment_uuid(
                platform, parsed["collection_native_id"], parsed["source_comment_id"]
            )
            conn.execute(
                """INSERT INTO catalog_collection_comments
                   (comment_uuid, collection_uuid, platform, source_comment_id,
                    parent_source_comment_id, author_display_name, author_user_id,
                    observed_at, body, payload_json, source_corpus_sha256, source_line_number)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    comment_uuid,
                    collection_uuid,
                    platform,
                    parsed["source_comment_id"],
                    parsed["parent_source_comment_id"],
                    parsed["author_display_name"],
                    parsed["author_user_id"],
                    parsed["observed_at"],
                    parsed["body"],
                    parsed["payload_json"],
                    corpus_sha256,
                    line_number,
                ),
            )
            inserted += 1
    return inserted


def run_migration(db_path: Path, expected_sha256: str, modio_path: Path, nexus_path: Path) -> dict:
    verify_db_hash(db_path, expected_sha256)
    backup_path = backup_database(db_path)
    modio_sha256 = sha256_file(modio_path)
    nexus_sha256 = sha256_file(nexus_path)

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE catalog_collection_comments (
                comment_uuid TEXT PRIMARY KEY,
                collection_uuid TEXT NOT NULL REFERENCES catalog_collections(collection_uuid),
                platform TEXT NOT NULL CHECK(platform IN ('modio', 'nexus')),
                source_comment_id TEXT NOT NULL,
                parent_source_comment_id TEXT,
                author_display_name TEXT,
                author_user_id TEXT,
                observed_at TEXT,
                body TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                source_corpus_sha256 TEXT NOT NULL,
                source_line_number INTEGER NOT NULL,
                UNIQUE(platform, source_comment_id)
            )
            """
        )
        conn.execute(
            """CREATE INDEX idx_catalog_collection_comments_collection
               ON catalog_collection_comments(collection_uuid, platform)"""
        )

        lookup = load_collection_lookup(conn)
        modio_inserted = insert_collection_comments(conn, "modio", modio_path, modio_sha256, lookup)
        nexus_inserted = insert_collection_comments(conn, "nexus", nexus_path, nexus_sha256, lookup)
        conn.commit()
    finally:
        conn.close()

    post_sha256 = sha256_file(db_path)
    return {
        "migration_name": "b26-phase4-collection-comments",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "pre_migration_sha256": expected_sha256,
        "backup_path": str(backup_path),
        "modio_source_sha256": modio_sha256,
        "nexus_source_sha256": nexus_sha256,
        "modio_rows_inserted": modio_inserted,
        "nexus_rows_inserted": nexus_inserted,
        "post_migration_sha256": post_sha256,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--candidate-sha256", required=True)
    parser.add_argument(
        "--modio-comments", type=Path,
        default=Path("data/collections/modio/modio_collections_comments.jsonl"),
    )
    parser.add_argument(
        "--nexus-comments", type=Path,
        default=Path("data/collections/nexus/nexus_collections_comments.jsonl"),
    )
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()

    receipt = run_migration(args.db, args.candidate_sha256, args.modio_comments, args.nexus_comments)
    args.receipt.write_text(json.dumps(receipt, indent=2))
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /workspaces/bg3_scraper && python3 -m pytest app/catalog_pipeline/claude_phase4/tests/test_promote_collection_comments.py -v`
Expected: 8 passed

- [ ] **Step 6: Commit**

```bash
git add app/catalog_pipeline/claude_phase4/promote_collection_comments.py \
        app/catalog_pipeline/claude_phase4/tests/fixtures.py \
        app/catalog_pipeline/claude_phase4/tests/test_promote_collection_comments.py
git commit -m "B26 Phase 4: add catalog_collection_comments migration"
```

---

## Task 3: Run both migrations for real against the candidate DB, verify, and push

**Files:**
- No new files. Runs the scripts from Tasks 1 and 2 against the real DB.

**Interfaces:**
- Consumes: `run_fix` from `fix_mod_comments_view.py`, `run_migration` from `promote_collection_comments.py`.
- Produces: two receipt JSON files, an updated DB, updated CLAUDE.md.

- [ ] **Step 1: Confirm current DB hash matches the last known-good value**

Run: `cd /workspaces/bg3_scraper && sha256sum catalog/B26/BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db`
Expected: `cb37e0392b7bdb0b06f8095c44b8352363610999498ff4803e07411df3187775` (the value recorded in `Google Drive/PROJECT_RECORD.md` and the 2026-07-30 gap report). If it doesn't match, stop — something changed the DB since this plan was written and the discrepancy needs explaining before proceeding, not overriding.

**Corrected 2026-08-07:** the hash above is stale -- it's the pre-Phase-3 baseline, and Phase 3 already changed the file before this plan was written. The real migration run used the corrected hash `cdefc2946953c396908e9d358d39e7f93eb31d86a71bed0a73b79a8a2cf8bf05` instead (cross-checked against `catalog/B26/phase3_migration_receipt.json`). Use that value, not the one above, if replaying this step -- expect a mismatch against the `cb37e039...` value and don't treat it as a real discrepancy.

- [ ] **Step 2: Run the mod_comments view fix**

Run:
```bash
python3 -m app.catalog_pipeline.claude_phase4.fix_mod_comments_view \
  --db catalog/B26/BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db \
  --candidate-sha256 cb37e0392b7bdb0b06f8095c44b8352363610999498ff4803e07411df3187775 \
  --receipt catalog/B26/phase4_view_fix_receipt.json
```
Expected in the printed receipt: `modio_rows_before: 132276`, `modio_rows_after: 76043`, `nexus_rows_before`/`nexus_rows_after` unchanged (451885).

- [ ] **Step 3: Run the collection-comments migration**

Run:
```bash
POST_FIX_SHA256=$(sha256sum catalog/B26/BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db | cut -d' ' -f1)
python3 -m app.catalog_pipeline.claude_phase4.promote_collection_comments \
  --db catalog/B26/BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db \
  --candidate-sha256 "$POST_FIX_SHA256" \
  --receipt catalog/B26/phase4_collection_comments_receipt.json
```
Note: the `--candidate-sha256` for this step must be the DB's hash *after* Step 2 (the view fix changed the file), not the original `cb37e039...` value — hence computing it fresh into `$POST_FIX_SHA256` first. Expected in the printed receipt: `modio_rows_inserted: 157`, `nexus_rows_inserted: 4965`.

- [ ] **Step 4: Independently verify — don't trust the scripts' own receipts alone**

Run:
```bash
sqlite3 catalog/B26/BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db <<'EOF'
select platform, count(*) from mod_comments group by platform;
select platform, count(*) from catalog_collection_comments group by platform;
PRAGMA integrity_check;
PRAGMA foreign_key_check;
EOF
```
Expected: `modio 76043`, `nexus 451885` from the first query; `modio 157`, `nexus 4965` from the second; `ok` from `integrity_check`; zero rows from `foreign_key_check`.

- [ ] **Step 5: Update CLAUDE.md marking Phase 4 complete**

Change the "B26 Phase 4 candidates" section header from "found during a completeness audit" to note completion, and update Next-steps item 11 from "planned, not yet executed" to "complete", recording the actual row counts confirmed in Step 4.

- [ ] **Step 6: Commit and push per this project's branch-then-PR convention**

```bash
git checkout -b b26-phase4-migration-complete
git add catalog/B26/phase4_view_fix_receipt.json catalog/B26/phase4_collection_comments_receipt.json CLAUDE.md
git commit -m "B26 Phase 4: run comment-dedup fix and collection-comments migration"
git push -u origin b26-phase4-migration-complete
gh pr create --title "B26 Phase 4: comment dedup fix + collection comments migration" --body "Runs both Phase 4 migrations against the live candidate DB and records the verified results in CLAUDE.md. See docs/superpowers/plans/2026-08-07-b26-phase4-collection-comments-and-comment-dedup.md."
```
(Direct pushes to `main` are rejected by this repo's `block_push_to_main.py` hook — same PR-based flow Phase 3 used.)

---

## Non-code follow-ups (not implementation tasks — decisions/conferences, not code)

These don't fit the TDD task structure above because there's no code to write; listed here so they aren't lost.

1. **Nexus `platform_listings` count question** (2026-07-30 gap report §2.4, still open): 11,809 rows doesn't cleanly match the documented 16,191-mod full sweep or the 3,662-mod curated tier list. Raise at the next Codex conference — the filtering/dedup logic that produced 11,809 lives in Codex's Phase 1 Coverage migration, not this repo's own code, so it can't be resolved by reading local files alone.
2. **Nexus Collections file-placement decision** (open since 2026-07-24): confirm with the user/conference whether `data/collections/{modio,nexus}/` is the intended permanent location, or whether it should move to match some other roadmap structure.

## Self-Review Notes

- **Spec coverage**: both gaps from the 2026-08-07 CLAUDE.md audit entry have a task (Task 1 for the dedup bug, Task 2 for the missing collection comments). The two non-code items from that entry are listed above rather than forced into fake code tasks.
- **Placeholder scan**: no TBD/TODO markers; every step has real code or a real, copy-pasteable shell command with expected output.
- **Type consistency**: `run_fix`/`run_migration` signatures match what Task 3's Step 2/3 commands actually pass. `collection_lookup` dict shape (`(platform, native_id) -> collection_uuid`) is identical between `load_collection_lookup`'s definition and every call site in tests and `run_migration`.
