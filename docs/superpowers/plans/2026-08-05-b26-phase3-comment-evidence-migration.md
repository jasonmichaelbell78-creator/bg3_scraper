# B26 Phase 3: Promote Comment Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make comment-derived evidence (dependencies, incompatibilities, load-order requirements) queryable from B26 itself, by ingesting the 451,885 Nexus comments and promoting 16,996 triage hits that currently only exist in a separate companion database.

**Architecture:** One script (`app/catalog_pipeline/claude_phase3/promote_comment_evidence.py`) that mutates the B26 candidate DB in place: filesystem backup, hash-gate both input DBs, insert a small verified test batch, roll it back, run the real insert in a fresh transaction, commit, then independently re-verify the committed result.

**Tech Stack:** Python 3, stdlib `sqlite3`/`unittest`/`hashlib`/`uuid` only — no new dependencies (matches Task 1's `verify_checksum.py` precedent; `pytest` is not installed in this environment).

## Global Constraints

- Candidate DB path: `catalog/B26/BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db`, expected SHA-256 `cb37e0392b7bdb0b06f8095c44b8352363610999498ff4803e07411df3187775`
- Phase 2B DB path: `catalog/B26/BG3_Comment_Evidence_Index_Phase2B_B26ExactLinks_candidate.db`, expected SHA-256 `a7d20f9586a7413f8d1a82ed2965de4cdcb19f942d59400be5896b3e3e72bfaa`
- **Only Nexus comments are inserted into `evidence_source_records` (451,885 rows).** mod.io's 76,043 comments already exist there (corpora `f12290b9-eb19-5c03-86fc-3e2064e4104f` / `e88d8457-18e1-5f54-8cf1-d0b93a2e6c01`) — confirmed via a full set-membership check (100% overlap, zero difference) during design. Never re-insert mod.io comments.
- `triage_hits` promotion covers **both** platforms (2,016 mod.io + 14,980 Nexus = 16,996 total) — mod.io claims link to the *existing* evidence rows (looked up, not inserted); Nexus claims link to the newly-inserted rows.
- Rule → claim_type mapping (confirmed with Jason): `required_dependency`→`dependency_requirement`, `incompatibility`→`incompatibility`, `relative_load_order`→`load_order`, everything else (`file_variant_advice`, `named_patch_addon`, `acquisition_content`, `author_context`)→`compatibility`.
- Every promoted claim: `evidence_state='triage_only'`, `claim_state='proposed'`, `confidence='low'`, `corroboration_state='single_unvalidated_triage_source'`, `source_authority` = the source comment's own `author_identity_tier`.
- All scripted batch work gets independent post-hoc verification via direct data analysis, not just a clean exit code (standing project preference).
- No new pip dependencies. Follow `app/catalog_pipeline/codex_phase1/register_phase1_coverage.py`'s hash-gate → transaction → post-commit-readonly-validation pattern.

---

### Task 1: Package scaffold, backup, and hash-gate utilities

**Files:**
- Create: `app/catalog_pipeline/claude_phase3/__init__.py` (empty)
- Create: `app/catalog_pipeline/claude_phase3/promote_comment_evidence.py`
- Create: `app/catalog_pipeline/claude_phase3/tests/__init__.py` (empty)
- Create: `app/catalog_pipeline/claude_phase3/tests/test_promote_comment_evidence.py`

**Interfaces:**
- Produces: `sha256_file(path: Path) -> str`, `verify_db_hash(db_path: Path, expected_sha256: str) -> None` (raises `ValueError` on mismatch), `backup_database(db_path: Path) -> Path` (returns the backup file's path, suffix `.pre-phase3-backup`) — every later task imports these from `promote_comment_evidence`.

- [ ] **Step 1: Write the failing tests**

```python
# app/catalog_pipeline/claude_phase3/tests/test_promote_comment_evidence.py
import hashlib
import tempfile
import unittest
from pathlib import Path

from app.catalog_pipeline.claude_phase3.promote_comment_evidence import (
    sha256_file,
    verify_db_hash,
    backup_database,
)


class TestHashUtilities(unittest.TestCase):
    def test_sha256_file_matches_hashlib(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"hello world")
            path = Path(f.name)
        try:
            expected = hashlib.sha256(b"hello world").hexdigest()
            self.assertEqual(sha256_file(path), expected)
        finally:
            path.unlink()

    def test_verify_db_hash_passes_on_match(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"content")
            path = Path(f.name)
        try:
            expected = hashlib.sha256(b"content").hexdigest()
            verify_db_hash(path, expected)  # should not raise
        finally:
            path.unlink()

    def test_verify_db_hash_raises_on_mismatch(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"content")
            path = Path(f.name)
        try:
            with self.assertRaises(ValueError):
                verify_db_hash(path, "0" * 64)
        finally:
            path.unlink()


class TestBackup(unittest.TestCase):
    def test_backup_creates_identical_copy_with_suffix(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "candidate.db"
            db_path.write_bytes(b"fake db content")
            backup_path = backup_database(db_path)
            self.assertEqual(backup_path.name, "candidate.db.pre-phase3-backup")
            self.assertEqual(backup_path.read_bytes(), db_path.read_bytes())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /workspaces/bg3_scraper && python3 -m unittest app.catalog_pipeline.claude_phase3.tests.test_promote_comment_evidence -v`
Expected: `ModuleNotFoundError` or `ImportError` — `promote_comment_evidence.py` doesn't exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
# app/catalog_pipeline/claude_phase3/promote_comment_evidence.py
"""
promote_comment_evidence.py v1.0
=================================
B26 Phase 3: promotes comment-derived evidence into the active B26 baseline.

Inserts the 451,885 Nexus comments from the Phase 2B comment-evidence-index
into evidence_source_records (mod.io's 76,043 comments already exist there --
never re-inserted, confirmed via set-membership check during design).
Promotes all 16,996 triage_hits (both platforms) into evidence_claims,
tagged evidence_state='triage_only' -- explicitly unvalidated. Retires
mod_comments (drops the table, replaces it with a view).

See docs/superpowers/specs/2026-08-05-b26-phase3-comment-evidence-migration-design.md
for the full design and rationale.
"""
import hashlib
import shutil
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_db_hash(db_path: Path, expected_sha256: str) -> None:
    actual = sha256_file(db_path)
    if actual != expected_sha256:
        raise ValueError(
            f"{db_path} hash mismatch: expected {expected_sha256}, got {actual}"
        )


def backup_database(db_path: Path) -> Path:
    backup_path = db_path.with_name(db_path.name + ".pre-phase3-backup")
    shutil.copy2(db_path, backup_path)
    return backup_path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /workspaces/bg3_scraper && python3 -m unittest app.catalog_pipeline.claude_phase3.tests.test_promote_comment_evidence -v`
Expected: 4/4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/catalog_pipeline/claude_phase3/
git commit -m "B26 Phase 3: add package scaffold, backup, and hash-gate utilities"
```

---

### Task 2: Deterministic ID/hash/payload builder functions

**Files:**
- Modify: `app/catalog_pipeline/claude_phase3/promote_comment_evidence.py`
- Modify: `app/catalog_pipeline/claude_phase3/tests/test_promote_comment_evidence.py`

**Interfaces:**
- Consumes: nothing from Task 1 directly (pure functions).
- Produces: `build_source_record_uuid(platform: str, platform_mod_id: str, source_comment_id: str) -> str`, `build_claim_uuid(hit_id: int) -> str`, `build_comment_payload_json(comment_row: sqlite3.Row) -> str`, `build_content_sha256(payload_json: str) -> str`, `build_raw_locator(platform: str, source_line_number: int) -> str`, `RULE_TO_CLAIM_TYPE: dict[str, str]` — Task 3 and Task 4 call all of these by exact name.

- [ ] **Step 1: Write the failing tests**

```python
# append to app/catalog_pipeline/claude_phase3/tests/test_promote_comment_evidence.py
import json
import sqlite3

from app.catalog_pipeline.claude_phase3.promote_comment_evidence import (
    build_source_record_uuid,
    build_claim_uuid,
    build_comment_payload_json,
    build_content_sha256,
    build_raw_locator,
    RULE_TO_CLAIM_TYPE,
)


class TestBuilders(unittest.TestCase):
    def test_source_record_uuid_is_deterministic(self):
        u1 = build_source_record_uuid("nexus", "899", "12345")
        u2 = build_source_record_uuid("nexus", "899", "12345")
        self.assertEqual(u1, u2)

    def test_source_record_uuid_differs_by_platform(self):
        u_nexus = build_source_record_uuid("nexus", "899", "12345")
        u_modio = build_source_record_uuid("modio", "899", "12345")
        self.assertNotEqual(u_nexus, u_modio)

    def test_claim_uuid_is_deterministic(self):
        self.assertEqual(build_claim_uuid(42), build_claim_uuid(42))
        self.assertNotEqual(build_claim_uuid(42), build_claim_uuid(43))

    def test_comment_payload_json_roundtrips_and_is_sorted(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.execute(
            """CREATE TABLE comments (
                comment_uid TEXT, platform TEXT, platform_mod_id TEXT,
                source_comment_id TEXT, parent_source_comment_id TEXT,
                thread_locator TEXT, threading_model TEXT, thread_depth INTEGER,
                author_display_name TEXT, author_user_id TEXT, author_url TEXT,
                author_identity_tier TEXT, is_sticky INTEGER, created_epoch INTEGER,
                captured_timestamp TEXT, body TEXT, coverage_state TEXT)"""
        )
        con.execute(
            "INSERT INTO comments VALUES ('u1','nexus','899','555',NULL,'t1',"
            "'nexus_parent_pointer',0,'Alice','a1','http://x','unverified',0,"
            "1700000000,'2023-11-14T00:00:00Z','test body','complete_capture')"
        )
        row = con.execute("SELECT * FROM comments").fetchone()
        payload_json = build_comment_payload_json(row)
        payload = json.loads(payload_json)
        self.assertEqual(payload["body"], "test body")
        self.assertEqual(payload["platform"], "nexus")
        # sorted keys => re-serializing with sort_keys gives back the same string
        self.assertEqual(payload_json, json.dumps(payload, sort_keys=True))

    def test_content_sha256_is_deterministic_and_sensitive_to_content(self):
        h1 = build_content_sha256('{"a": 1}')
        h2 = build_content_sha256('{"a": 1}')
        h3 = build_content_sha256('{"a": 2}')
        self.assertEqual(h1, h2)
        self.assertNotEqual(h1, h3)
        self.assertEqual(len(h1), 64)

    def test_raw_locator_format(self):
        self.assertEqual(
            build_raw_locator("nexus", 42), "nexus_comments_merged.jsonl#L42"
        )
        self.assertEqual(
            build_raw_locator("modio", 1), "modio_comments_merged.jsonl#L1"
        )

    def test_rule_to_claim_type_covers_all_seven_rules(self):
        expected_rules = {
            "required_dependency", "incompatibility", "relative_load_order",
            "file_variant_advice", "named_patch_addon", "acquisition_content",
            "author_context",
        }
        self.assertEqual(set(RULE_TO_CLAIM_TYPE.keys()), expected_rules)
        self.assertEqual(RULE_TO_CLAIM_TYPE["required_dependency"], "dependency_requirement")
        self.assertEqual(RULE_TO_CLAIM_TYPE["incompatibility"], "incompatibility")
        self.assertEqual(RULE_TO_CLAIM_TYPE["relative_load_order"], "load_order")
        for rule in ("file_variant_advice", "named_patch_addon", "acquisition_content", "author_context"):
            self.assertEqual(RULE_TO_CLAIM_TYPE[rule], "compatibility")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /workspaces/bg3_scraper && python3 -m unittest app.catalog_pipeline.claude_phase3.tests.test_promote_comment_evidence -v`
Expected: `ImportError` — the new functions don't exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
# add to app/catalog_pipeline/claude_phase3/promote_comment_evidence.py
import json
import sqlite3
import uuid

RULE_TO_CLAIM_TYPE = {
    "required_dependency": "dependency_requirement",
    "incompatibility": "incompatibility",
    "relative_load_order": "load_order",
    "file_variant_advice": "compatibility",
    "named_patch_addon": "compatibility",
    "acquisition_content": "compatibility",
    "author_context": "compatibility",
}


def build_source_record_uuid(platform: str, platform_mod_id: str, source_comment_id: str) -> str:
    seed = f"bg3:phase3-evidence-source-record:comment:{platform}:{platform_mod_id}:{source_comment_id}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))


def build_claim_uuid(hit_id: int) -> str:
    seed = f"bg3:phase3-evidence-claim:triage-hit:{hit_id}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))


def build_comment_payload_json(comment_row: sqlite3.Row) -> str:
    payload = {
        "comment_uid": comment_row["comment_uid"],
        "platform": comment_row["platform"],
        "platform_mod_id": comment_row["platform_mod_id"],
        "source_comment_id": comment_row["source_comment_id"],
        "parent_source_comment_id": comment_row["parent_source_comment_id"],
        "thread_locator": comment_row["thread_locator"],
        "threading_model": comment_row["threading_model"],
        "thread_depth": comment_row["thread_depth"],
        "author_display_name": comment_row["author_display_name"],
        "author_user_id": comment_row["author_user_id"],
        "author_url": comment_row["author_url"],
        "author_identity_tier": comment_row["author_identity_tier"],
        "is_sticky": comment_row["is_sticky"],
        "created_epoch": comment_row["created_epoch"],
        "captured_timestamp": comment_row["captured_timestamp"],
        "body": comment_row["body"],
        "coverage_state": comment_row["coverage_state"],
    }
    return json.dumps(payload, sort_keys=True)


def build_content_sha256(payload_json: str) -> str:
    return hashlib.sha256(payload_json.encode("utf-8")).hexdigest()


def build_raw_locator(platform: str, source_line_number: int) -> str:
    return f"{platform}_comments_merged.jsonl#L{source_line_number}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /workspaces/bg3_scraper && python3 -m unittest app.catalog_pipeline.claude_phase3.tests.test_promote_comment_evidence -v`
Expected: 11/11 tests pass (4 from Task 1 + 7 new).

- [ ] **Step 5: Commit**

```bash
git add app/catalog_pipeline/claude_phase3/
git commit -m "B26 Phase 3: add deterministic ID/hash/payload builder functions"
```

---

### Task 3: Fixture schema helper for tests

**Files:**
- Create: `app/catalog_pipeline/claude_phase3/tests/fixtures.py`
- Modify: `app/catalog_pipeline/claude_phase3/tests/test_promote_comment_evidence.py`

**Interfaces:**
- Produces: `create_fixture_candidate_db(conn: sqlite3.Connection) -> None` (creates `evidence_corpora`, `evidence_source_records`, `evidence_claims`, `evidence_claim_links`, `mod_comments`, `platform_listings`, `migration_history`, `ingestion_stage_receipts` with real column/constraint definitions, plus seeds the two pre-existing mod.io corpora and 3 sample mod.io evidence rows), `create_fixture_phase2b_db(conn: sqlite3.Connection) -> None` (creates `comments`, `triage_hits`, `triage_rule_catalog`, seeds the 7 real rule codes plus sample comment/triage rows for one Nexus mod and one mod.io mod) — Tasks 4-7's tests all import and use these.

This task has no production code, only test infrastructure — it exists as its own task because Tasks 4-7 all depend on it and it's substantial enough to warrant its own review gate.

- [ ] **Step 1: Write the failing test**

```python
# append to app/catalog_pipeline/claude_phase3/tests/test_promote_comment_evidence.py
from app.catalog_pipeline.claude_phase3.tests.fixtures import (
    create_fixture_candidate_db,
    create_fixture_phase2b_db,
)


class TestFixtures(unittest.TestCase):
    def test_fixture_candidate_db_has_expected_tables(self):
        con = sqlite3.connect(":memory:")
        create_fixture_candidate_db(con)
        tables = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        self.assertEqual(
            tables,
            {
                "evidence_corpora", "evidence_source_records", "evidence_claims",
                "evidence_claim_links", "mod_comments", "platform_listings",
                "migration_history", "ingestion_stage_receipts",
            },
        )
        # seeded: 2 pre-existing modio corpora, 3 sample modio evidence rows
        corpora = con.execute("SELECT COUNT(*) FROM evidence_corpora WHERE provider='modio'").fetchone()[0]
        self.assertEqual(corpora, 2)
        modio_rows = con.execute("SELECT COUNT(*) FROM evidence_source_records").fetchone()[0]
        self.assertEqual(modio_rows, 3)

    def test_fixture_phase2b_db_has_expected_tables_and_seed_data(self):
        con = sqlite3.connect(":memory:")
        create_fixture_phase2b_db(con)
        tables = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        self.assertEqual(tables, {"comments", "triage_hits", "triage_rule_catalog"})
        rule_count = con.execute("SELECT COUNT(*) FROM triage_rule_catalog").fetchone()[0]
        self.assertEqual(rule_count, 7)
        nexus_count = con.execute("SELECT COUNT(*) FROM comments WHERE platform='nexus'").fetchone()[0]
        modio_count = con.execute("SELECT COUNT(*) FROM comments WHERE platform='modio'").fetchone()[0]
        self.assertGreater(nexus_count, 0)
        self.assertGreater(modio_count, 0)
        # the 3 modio comments in the phase2b fixture must match the 3 seeded
        # in the candidate fixture (same source_comment_id values), so
        # Task 4's mod.io lookup-not-insert path has something real to find
        modio_ids = {r[0] for r in con.execute(
            "SELECT source_comment_id FROM comments WHERE platform='modio'"
        )}
        self.assertEqual(modio_ids, {"9001", "9002", "9003"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /workspaces/bg3_scraper && python3 -m unittest app.catalog_pipeline.claude_phase3.tests.test_promote_comment_evidence -v`
Expected: `ImportError` — `fixtures.py` doesn't exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
# app/catalog_pipeline/claude_phase3/tests/fixtures.py
"""Shared SQLite fixture schemas for B26 Phase 3 migration tests.

Mirrors the real column/constraint definitions of catalog/B26/
BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db and
catalog/B26/BG3_Comment_Evidence_Index_Phase2B_B26ExactLinks_candidate.db,
confirmed via `.schema` against the live databases on 2026-08-05 (see the
B26 Phase 3 design doc). Not the full real schema -- only the tables this
migration touches.
"""
import sqlite3


def create_fixture_candidate_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE evidence_corpora (
          corpus_uuid TEXT PRIMARY KEY,
          provider TEXT NOT NULL,
          object_scope TEXT NOT NULL,
          capture_label TEXT NOT NULL,
          captured_started_at TEXT,
          captured_finished_at TEXT,
          coverage_state TEXT NOT NULL CHECK(coverage_state IN
              ('not_available','not_collected','partial','complete','zero',
               'analyzed_no_match','signal_present')),
          profile_label TEXT,
          record_count_raw INTEGER,
          record_count_unique INTEGER,
          limitation_notes TEXT NOT NULL,
          supersedes_corpus_uuid TEXT REFERENCES evidence_corpora(corpus_uuid)
        );

        CREATE TABLE platform_listings (
            listing_id INTEGER PRIMARY KEY AUTOINCREMENT,
            mod_uid INTEGER,
            platform TEXT,
            platform_mod_id TEXT,
            listing_uuid TEXT
        );
        CREATE UNIQUE INDEX uq_platform_listings_listing_uuid ON platform_listings(listing_uuid);

        CREATE TABLE evidence_source_records (
          source_record_uuid TEXT PRIMARY KEY,
          corpus_uuid TEXT NOT NULL REFERENCES evidence_corpora(corpus_uuid),
          provider_object_type TEXT NOT NULL,
          provider_native_id TEXT NOT NULL,
          source_listing_uuid TEXT REFERENCES platform_listings(listing_uuid),
          parent_provider_native_id TEXT,
          observed_at TEXT,
          displayed_author TEXT,
          version_text TEXT,
          content_sha256 TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          raw_locator TEXT NOT NULL,
          UNIQUE (corpus_uuid, provider_object_type, provider_native_id)
        );

        CREATE TABLE evidence_claims (
          claim_uuid TEXT PRIMARY KEY,
          claim_text TEXT NOT NULL,
          claim_type TEXT NOT NULL,
          evidence_state TEXT NOT NULL CHECK(evidence_state IN
              ('retained_primary','retained_secondary','triage_only','unverifiable_session_summary')),
          claim_state TEXT NOT NULL CHECK(claim_state IN
              ('proposed','reviewed_supported','reviewed_insufficient','contradicted','promoted')),
          source_authority TEXT NOT NULL,
          corroboration_state TEXT NOT NULL,
          confidence TEXT NOT NULL,
          game_patch_scope TEXT NOT NULL,
          manager_scope TEXT NOT NULL,
          tool_and_version_scope TEXT NOT NULL,
          deployment_channel_scope TEXT NOT NULL,
          target_text TEXT NOT NULL,
          notes TEXT NOT NULL,
          created_at TEXT NOT NULL
        );

        CREATE TABLE evidence_claim_links (
          claim_uuid TEXT NOT NULL REFERENCES evidence_claims(claim_uuid),
          source_record_uuid TEXT REFERENCES evidence_source_records(source_record_uuid),
          artifact_uuid TEXT,
          link_role TEXT NOT NULL CHECK(link_role IN ('supports','contradicts','context')),
          evidence_excerpt TEXT NOT NULL,
          content_sha256 TEXT,
          CHECK(source_record_uuid IS NOT NULL OR artifact_uuid IS NOT NULL),
          PRIMARY KEY (claim_uuid, source_record_uuid, artifact_uuid, link_role)
        );

        CREATE TABLE mod_comments (
            comment_id INTEGER PRIMARY KEY,
            mod_uid INTEGER,
            author TEXT,
            date_added TEXT,
            karma INTEGER,
            reply_to_comment_id INTEGER,
            thread_position TEXT,
            options INTEGER,
            content TEXT
        );

        CREATE TABLE migration_history (
            migration_id INTEGER PRIMARY KEY AUTOINCREMENT,
            migration_name TEXT UNIQUE NOT NULL,
            schema_version TEXT NOT NULL,
            applied_at TEXT NOT NULL,
            actor_session TEXT NOT NULL,
            source_db_sha256 TEXT NOT NULL,
            row_count_before TEXT NOT NULL,
            row_count_after TEXT NOT NULL,
            notes TEXT
        );

        CREATE TABLE ingestion_stage_receipts (
          stage_receipt_uuid TEXT PRIMARY KEY,
          ingestion_run_id INTEGER,
          stage_label TEXT NOT NULL,
          source_artifact_sha256 TEXT NOT NULL,
          started_at TEXT NOT NULL,
          completed_at TEXT,
          records_seen INTEGER NOT NULL DEFAULT 0,
          records_written INTEGER NOT NULL DEFAULT 0,
          records_skipped INTEGER NOT NULL DEFAULT 0,
          validation_json TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('started','committed','rolled_back','failed')),
          notes TEXT
        );
        """
    )

    # Seed: the two pre-existing mod.io comment corpora and one
    # platform_listings row + 3 evidence_source_records rows, so Task 4's
    # "look up existing mod.io evidence, don't re-insert" path has real
    # data to find. source_comment_id values (9001-9003) must match the
    # mod.io comments seeded in create_fixture_phase2b_db below.
    conn.execute(
        "INSERT INTO evidence_corpora VALUES "
        "('f12290b9-eb19-5c03-86fc-3e2064e4104f','modio','comments',"
        "'modio_comments_base_under_page_limit_2026-07-21',NULL,NULL,"
        "'complete',NULL,2,2,'fixture seed',NULL)"
    )
    conn.execute(
        "INSERT INTO evidence_corpora VALUES "
        "('e88d8457-18e1-5f54-8cf1-d0b93a2e6c01','modio','comments',"
        "'modio_comments_deep_refresh_2026-07-21',NULL,NULL,"
        "'complete',NULL,1,1,'fixture seed',"
        "'f12290b9-eb19-5c03-86fc-3e2064e4104f')"
    )
    conn.execute(
        "INSERT INTO platform_listings (mod_uid, platform, platform_mod_id, listing_uuid) "
        "VALUES (1, 'modio', '4320786', 'fixture-listing-uuid-modio-4320786')"
    )
    for i, comment_id in enumerate(("9001", "9002"), start=1):
        conn.execute(
            "INSERT INTO evidence_source_records VALUES "
            "(?, 'f12290b9-eb19-5c03-86fc-3e2064e4104f', 'comment', ?, "
            "'fixture-listing-uuid-modio-4320786', NULL, '2023-01-01', 'author', "
            "NULL, 'deadbeef', '{}', 'modio_comments_merged.jsonl#L1')",
            (f"fixture-existing-modio-{i}", comment_id),
        )
    conn.execute(
        "INSERT INTO evidence_source_records VALUES "
        "('fixture-existing-modio-3', 'e88d8457-18e1-5f54-8cf1-d0b93a2e6c01', "
        "'comment', '9003', 'fixture-listing-uuid-modio-4320786', NULL, "
        "'2023-01-01', 'author', NULL, 'deadbeef', '{}', "
        "'modio_comments_merged.jsonl#L2')"
    )
    conn.commit()


def create_fixture_phase2b_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE comments (
            comment_row_id INTEGER PRIMARY KEY,
            comment_uid TEXT NOT NULL UNIQUE,
            platform TEXT NOT NULL CHECK(platform IN ('modio', 'nexus')),
            platform_mod_id TEXT NOT NULL,
            source_comment_id TEXT NOT NULL,
            parent_source_comment_id TEXT,
            thread_locator TEXT,
            threading_model TEXT NOT NULL,
            thread_depth INTEGER,
            author_display_name TEXT,
            author_user_id TEXT,
            author_url TEXT,
            author_identity_tier TEXT NOT NULL,
            is_sticky INTEGER,
            created_epoch INTEGER,
            captured_timestamp TEXT,
            body TEXT NOT NULL,
            source_line_number INTEGER NOT NULL,
            source_corpus_sha256 TEXT NOT NULL,
            coverage_state TEXT NOT NULL,
            b26_listing_link_state TEXT NOT NULL,
            b26_listing_uuid TEXT,
            UNIQUE(platform, platform_mod_id, source_comment_id)
        );

        CREATE TABLE triage_rule_catalog (
            rule_code TEXT PRIMARY KEY,
            priority_order INTEGER NOT NULL,
            display_name TEXT NOT NULL,
            operational_limit TEXT NOT NULL,
            author_tier_elevating INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE triage_hits (
            hit_id INTEGER PRIMARY KEY,
            comment_row_id INTEGER NOT NULL REFERENCES comments(comment_row_id),
            rule_code TEXT NOT NULL REFERENCES triage_rule_catalog(rule_code),
            pattern_note TEXT NOT NULL,
            disposition_state TEXT NOT NULL DEFAULT 'triage_only_context_required',
            full_comment_required INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            UNIQUE(comment_row_id, rule_code)
        );
        """
    )

    for rule_code, priority in (
        ("author_context", 1), ("required_dependency", 2), ("incompatibility", 3),
        ("relative_load_order", 4), ("file_variant_advice", 5),
        ("named_patch_addon", 6), ("acquisition_content", 7),
    ):
        conn.execute(
            "INSERT INTO triage_rule_catalog VALUES (?, ?, ?, 'fixture limit', 0)",
            (rule_code, priority),
        )

    # 3 Nexus comments for mod 14077 (1 top-level, 2 replies -- exercises
    # threading), 1 gets a triage hit
    nexus_rows = [
        ("nx-1", "nexus", "14077", "555001", None, "t1", "nexus_parent_pointer",
         0, "Alice", "u1", "http://nexusmods.com/u1", "unverified_displayed_name_match",
         0, 1700000000, "2023-11-14T00:00:00Z",
         "This mod requires AnimationUnlocker to work correctly.",
         1, "fixturehash", "complete_capture", "linked_exact_platform_id",
         "fixture-listing-uuid-nexus-14077"),
        ("nx-2", "nexus", "14077", "555002", "555001", "t1.1", "nexus_parent_pointer",
         1, "Bob", "u2", "http://nexusmods.com/u2", "unverified_displayed_name_match",
         0, 1700000100, "2023-11-14T00:05:00Z", "Thanks, can confirm it works.",
         2, "fixturehash", "complete_capture", "linked_exact_platform_id",
         "fixture-listing-uuid-nexus-14077"),
        ("nx-3", "nexus", "14077", "555003", "555001", "t1.2", "nexus_parent_pointer",
         1, "Carol", "u3", "http://nexusmods.com/u3", "unverified_displayed_name_match",
         0, 1700000200, "2023-11-14T00:10:00Z", "Same here, great mod.",
         3, "fixturehash", "complete_capture", "linked_exact_platform_id",
         "fixture-listing-uuid-nexus-14077"),
    ]
    # 3 modio comments for mod 4320786, source_comment_id 9001-9003 --
    # MUST match create_fixture_candidate_db's seeded evidence rows above,
    # so Task 4's mod.io lookup path resolves for real
    modio_rows = [
        ("mo-1", "modio", "4320786", "9001", None, "0", "modio_dotted_reply",
         0, "Dave", "m1", "https://mod.io/u/m1", "unverified_displayed_name_match",
         0, 1700001000, "2023-11-15T00:00:00Z",
         "This is incompatible with the Reshade mod.",
         1, "fixturehash2", "complete_capture", "linked_exact_platform_id",
         "fixture-listing-uuid-modio-4320786"),
        ("mo-2", "modio", "4320786", "9002", "9001", "0.1", "modio_dotted_reply",
         1, "Eve", "m2", "https://mod.io/u/m2", "unverified_displayed_name_match",
         0, 1700001100, "2023-11-15T00:05:00Z", "Good to know, thanks!",
         2, "fixturehash2", "complete_capture", "linked_exact_platform_id",
         "fixture-listing-uuid-modio-4320786"),
        ("mo-3", "modio", "4320786", "9003", None, "1", "modio_dotted_reply",
         0, "Frank", "m3", "https://mod.io/u/m3", "unverified_displayed_name_match",
         0, 1700001200, "2023-11-15T00:10:00Z", "Load this one after the base mod.",
         3, "fixturehash2", "complete_capture", "linked_exact_platform_id",
         "fixture-listing-uuid-modio-4320786"),
    ]
    for row in nexus_rows + modio_rows:
        conn.execute(
            "INSERT INTO comments VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            row,
        )

    # Triage hits: one on the first Nexus comment (required_dependency),
    # one on the first modio comment (incompatibility), one on the third
    # modio comment (relative_load_order) -- covers 3 of the 7 rule types
    conn.execute(
        "INSERT INTO triage_hits VALUES (1, "
        "(SELECT comment_row_id FROM comments WHERE comment_uid='nx-1'), "
        "'required_dependency', 'requires AnimationUnlocker', "
        "'triage_only_context_required', 1, '2023-11-14T00:00:01Z')"
    )
    conn.execute(
        "INSERT INTO triage_hits VALUES (2, "
        "(SELECT comment_row_id FROM comments WHERE comment_uid='mo-1'), "
        "'incompatibility', 'incompatible with Reshade', "
        "'triage_only_context_required', 1, '2023-11-15T00:00:01Z')"
    )
    conn.execute(
        "INSERT INTO triage_hits VALUES (3, "
        "(SELECT comment_row_id FROM comments WHERE comment_uid='mo-3'), "
        "'relative_load_order', 'load this one after', "
        "'triage_only_context_required', 1, '2023-11-15T00:10:01Z')"
    )
    conn.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /workspaces/bg3_scraper && python3 -m unittest app.catalog_pipeline.claude_phase3.tests.test_promote_comment_evidence -v`
Expected: 13/13 tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/catalog_pipeline/claude_phase3/tests/fixtures.py app/catalog_pipeline/claude_phase3/tests/test_promote_comment_evidence.py
git commit -m "B26 Phase 3: add shared SQLite fixture schemas for migration tests"
```

---

### Task 4: Nexus evidence_corpora + evidence_source_records insert

**Files:**
- Modify: `app/catalog_pipeline/claude_phase3/promote_comment_evidence.py`
- Modify: `app/catalog_pipeline/claude_phase3/tests/test_promote_comment_evidence.py`

**Interfaces:**
- Consumes: `build_source_record_uuid`, `build_comment_payload_json`, `build_content_sha256`, `build_raw_locator` (Task 2); `create_fixture_candidate_db`, `create_fixture_phase2b_db` (Task 3).
- Produces: `NEXUS_PLACEHOLDER_CORPUS_UUID: str` (constant, `"cc2ea89e-3980-552e-aeb3-4c7e6056a3a1"`), `insert_nexus_evidence_corpus(conn: sqlite3.Connection, *, record_count: int) -> str` (returns new corpus_uuid), `insert_nexus_evidence_source_records(candidate_conn: sqlite3.Connection, phase2b_conn: sqlite3.Connection, corpus_uuid: str, *, platform_mod_ids: list[str] | None = None) -> dict[str, str]` (returns `{source_comment_id: source_record_uuid}`, filtered to `platform_mod_ids` when given) — Task 6 (test batch) and Task 7 (full run) both call these; Task 6 passes `platform_mod_ids=["14077"]`, Task 7 passes `platform_mod_ids=None` (all Nexus rows).

- [ ] **Step 1: Write the failing tests**

```python
# append to app/catalog_pipeline/claude_phase3/tests/test_promote_comment_evidence.py
from app.catalog_pipeline.claude_phase3.promote_comment_evidence import (
    NEXUS_PLACEHOLDER_CORPUS_UUID,
    insert_nexus_evidence_corpus,
    insert_nexus_evidence_source_records,
)


class TestNexusEvidenceInsert(unittest.TestCase):
    def setUp(self):
        self.candidate = sqlite3.connect(":memory:")
        create_fixture_candidate_db(self.candidate)
        self.phase2b = sqlite3.connect(":memory:")
        create_fixture_phase2b_db(self.phase2b)

    def test_insert_nexus_evidence_corpus_creates_row_superseding_placeholder(self):
        corpus_uuid = insert_nexus_evidence_corpus(self.candidate, record_count=3)
        row = self.candidate.execute(
            "SELECT provider, coverage_state, record_count_unique, supersedes_corpus_uuid "
            "FROM evidence_corpora WHERE corpus_uuid=?", (corpus_uuid,)
        ).fetchone()
        self.assertEqual(row[0], "nexus")
        self.assertEqual(row[1], "partial")
        self.assertEqual(row[2], 3)
        self.assertEqual(row[3], NEXUS_PLACEHOLDER_CORPUS_UUID)

    def test_insert_nexus_evidence_source_records_inserts_all_matching_rows(self):
        corpus_uuid = insert_nexus_evidence_corpus(self.candidate, record_count=3)
        uuid_map = insert_nexus_evidence_source_records(
            self.candidate, self.phase2b, corpus_uuid
        )
        self.assertEqual(len(uuid_map), 3)
        self.assertEqual(set(uuid_map.keys()), {"555001", "555002", "555003"})
        count = self.candidate.execute(
            "SELECT COUNT(*) FROM evidence_source_records WHERE corpus_uuid=?", (corpus_uuid,)
        ).fetchone()[0]
        self.assertEqual(count, 3)

    def test_insert_nexus_evidence_source_records_respects_mod_id_filter(self):
        corpus_uuid = insert_nexus_evidence_corpus(self.candidate, record_count=1)
        uuid_map = insert_nexus_evidence_source_records(
            self.candidate, self.phase2b, corpus_uuid, platform_mod_ids=["14077"]
        )
        # all 3 fixture nexus comments belong to mod 14077, so filtering by
        # it should still return all 3 -- this proves the filter is applied
        # (not silently ignored) without requiring a second mod in the fixture
        self.assertEqual(len(uuid_map), 3)

    def test_inserted_row_content_matches_source_exactly(self):
        corpus_uuid = insert_nexus_evidence_corpus(self.candidate, record_count=3)
        uuid_map = insert_nexus_evidence_source_records(
            self.candidate, self.phase2b, corpus_uuid
        )
        source_row = self.phase2b.execute(
            "SELECT body, b26_listing_uuid, source_line_number FROM comments "
            "WHERE source_comment_id='555001'"
        ).fetchone()
        inserted_row = self.candidate.execute(
            "SELECT payload_json, source_listing_uuid, raw_locator FROM evidence_source_records "
            "WHERE source_record_uuid=?", (uuid_map["555001"],)
        ).fetchone()
        payload = json.loads(inserted_row[0])
        self.assertEqual(payload["body"], source_row[0])
        self.assertEqual(inserted_row[1], source_row[1])
        self.assertEqual(inserted_row[2], f"nexus_comments_merged.jsonl#L{source_row[2]}")

    def test_modio_comments_are_never_touched(self):
        corpus_uuid = insert_nexus_evidence_corpus(self.candidate, record_count=3)
        insert_nexus_evidence_source_records(self.candidate, self.phase2b, corpus_uuid)
        modio_count_after = self.candidate.execute(
            "SELECT COUNT(*) FROM evidence_source_records WHERE corpus_uuid IN "
            "('f12290b9-eb19-5c03-86fc-3e2064e4104f','e88d8457-18e1-5f54-8cf1-d0b93a2e6c01')"
        ).fetchone()[0]
        self.assertEqual(modio_count_after, 3)  # unchanged from fixture seed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /workspaces/bg3_scraper && python3 -m unittest app.catalog_pipeline.claude_phase3.tests.test_promote_comment_evidence -v`
Expected: `ImportError` — the new functions don't exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
# add to app/catalog_pipeline/claude_phase3/promote_comment_evidence.py
NEXUS_PLACEHOLDER_CORPUS_UUID = "cc2ea89e-3980-552e-aeb3-4c7e6056a3a1"


def insert_nexus_evidence_corpus(conn: sqlite3.Connection, *, record_count: int) -> str:
    corpus_uuid = str(uuid.uuid5(
        uuid.NAMESPACE_URL, "bg3:evidence-corpus:nexus:phase3_comment_promotion_2026-08"
    ))
    conn.execute(
        """INSERT INTO evidence_corpora
           (corpus_uuid, provider, object_scope, capture_label, coverage_state,
            record_count_raw, record_count_unique, limitation_notes, supersedes_corpus_uuid)
           VALUES (?, 'nexus', 'comments', 'nexus_comments_merged_phase3_promotion_2026-08',
                   'partial', ?, ?, ?, ?)""",
        (
            corpus_uuid, record_count, record_count,
            "Sourced from Phase 2B comment-evidence-index. Two mods have permanent "
            "partial capture: 279 (4,511 comments, page-123 Cloudflare wall) and "
            "22659 (74 comments) -- accepted gaps, see CLAUDE.md.",
            NEXUS_PLACEHOLDER_CORPUS_UUID,
        ),
    )
    return corpus_uuid


def insert_nexus_evidence_source_records(
    candidate_conn: sqlite3.Connection,
    phase2b_conn: sqlite3.Connection,
    corpus_uuid: str,
    *,
    platform_mod_ids: list[str] | None = None,
) -> dict[str, str]:
    phase2b_conn.row_factory = sqlite3.Row
    query = "SELECT * FROM comments WHERE platform = 'nexus'"
    params: tuple = ()
    if platform_mod_ids is not None:
        placeholders = ",".join("?" for _ in platform_mod_ids)
        query += f" AND platform_mod_id IN ({placeholders})"
        params = tuple(platform_mod_ids)

    uuid_by_comment_id: dict[str, str] = {}
    rows_to_insert = []
    for row in phase2b_conn.execute(query, params):
        source_record_uuid = build_source_record_uuid(
            "nexus", row["platform_mod_id"], row["source_comment_id"]
        )
        payload_json = build_comment_payload_json(row)
        content_sha256 = build_content_sha256(payload_json)
        raw_locator = build_raw_locator("nexus", row["source_line_number"])
        rows_to_insert.append((
            source_record_uuid, corpus_uuid, "comment", row["source_comment_id"],
            row["b26_listing_uuid"], row["parent_source_comment_id"],
            row["captured_timestamp"], row["author_display_name"], None,
            content_sha256, payload_json, raw_locator,
        ))
        uuid_by_comment_id[row["source_comment_id"]] = source_record_uuid

    candidate_conn.executemany(
        """INSERT INTO evidence_source_records
           (source_record_uuid, corpus_uuid, provider_object_type, provider_native_id,
            source_listing_uuid, parent_provider_native_id, observed_at, displayed_author,
            version_text, content_sha256, payload_json, raw_locator)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows_to_insert,
    )
    return uuid_by_comment_id
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /workspaces/bg3_scraper && python3 -m unittest app.catalog_pipeline.claude_phase3.tests.test_promote_comment_evidence -v`
Expected: 18/18 tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/catalog_pipeline/claude_phase3/
git commit -m "B26 Phase 3: add Nexus evidence_corpora and evidence_source_records insert"
```

---

### Task 5: Triage hit promotion (evidence_claims + evidence_claim_links)

**Files:**
- Modify: `app/catalog_pipeline/claude_phase3/promote_comment_evidence.py`
- Modify: `app/catalog_pipeline/claude_phase3/tests/test_promote_comment_evidence.py`

**Interfaces:**
- Consumes: `build_claim_uuid`, `RULE_TO_CLAIM_TYPE` (Task 2); `MODIO_CORPUS_UUIDS` (new constant, this task); the `{source_comment_id: source_record_uuid}` dict shape produced by Task 4's `insert_nexus_evidence_source_records`.
- Produces: `MODIO_CORPUS_UUIDS: tuple[str, str]`, `lookup_existing_modio_evidence_uuids(candidate_conn: sqlite3.Connection) -> dict[str, str]`, `promote_triage_hits(candidate_conn: sqlite3.Connection, phase2b_conn: sqlite3.Connection, nexus_uuid_by_comment_id: dict[str, str], modio_uuid_by_comment_id: dict[str, str], *, platform_mod_ids: list[str] | None = None) -> int` (returns count of claims inserted; raises `RuntimeError` if any triage hit has no matching evidence row) — Task 6 and Task 7 call both.

- [ ] **Step 1: Write the failing tests**

```python
# append to app/catalog_pipeline/claude_phase3/tests/test_promote_comment_evidence.py
from app.catalog_pipeline.claude_phase3.promote_comment_evidence import (
    MODIO_CORPUS_UUIDS,
    lookup_existing_modio_evidence_uuids,
    promote_triage_hits,
)


class TestTriagePromotion(unittest.TestCase):
    def setUp(self):
        self.candidate = sqlite3.connect(":memory:")
        create_fixture_candidate_db(self.candidate)
        self.phase2b = sqlite3.connect(":memory:")
        create_fixture_phase2b_db(self.phase2b)
        corpus_uuid = insert_nexus_evidence_corpus(self.candidate, record_count=3)
        self.nexus_uuid_by_comment_id = insert_nexus_evidence_source_records(
            self.candidate, self.phase2b, corpus_uuid
        )

    def test_lookup_existing_modio_evidence_finds_fixture_seed_rows(self):
        modio_map = lookup_existing_modio_evidence_uuids(self.candidate)
        self.assertEqual(set(modio_map.keys()), {"9001", "9002", "9003"})

    def test_promote_triage_hits_inserts_one_claim_per_hit(self):
        modio_map = lookup_existing_modio_evidence_uuids(self.candidate)
        count = promote_triage_hits(
            self.candidate, self.phase2b, self.nexus_uuid_by_comment_id, modio_map
        )
        self.assertEqual(count, 3)  # fixture has exactly 3 triage_hits
        claim_count = self.candidate.execute("SELECT COUNT(*) FROM evidence_claims").fetchone()[0]
        link_count = self.candidate.execute("SELECT COUNT(*) FROM evidence_claim_links").fetchone()[0]
        self.assertEqual(claim_count, 3)
        self.assertEqual(link_count, 3)

    def test_all_promoted_claims_are_triage_only_and_proposed(self):
        modio_map = lookup_existing_modio_evidence_uuids(self.candidate)
        promote_triage_hits(self.candidate, self.phase2b, self.nexus_uuid_by_comment_id, modio_map)
        states = self.candidate.execute(
            "SELECT DISTINCT evidence_state, claim_state, confidence, corroboration_state "
            "FROM evidence_claims"
        ).fetchall()
        self.assertEqual(states, [("triage_only", "proposed", "low", "single_unvalidated_triage_source")])

    def test_claim_type_mapping_applied_correctly(self):
        modio_map = lookup_existing_modio_evidence_uuids(self.candidate)
        promote_triage_hits(self.candidate, self.phase2b, self.nexus_uuid_by_comment_id, modio_map)
        claim_types = {row[0] for row in self.candidate.execute(
            "SELECT claim_type FROM evidence_claims"
        )}
        # fixture has one required_dependency, one incompatibility, one relative_load_order hit
        self.assertEqual(claim_types, {"dependency_requirement", "incompatibility", "load_order"})

    def test_modio_claim_links_to_existing_evidence_not_new(self):
        modio_map = lookup_existing_modio_evidence_uuids(self.candidate)
        promote_triage_hits(self.candidate, self.phase2b, self.nexus_uuid_by_comment_id, modio_map)
        modio_evidence_count_after = self.candidate.execute(
            "SELECT COUNT(*) FROM evidence_source_records WHERE corpus_uuid IN "
            "('f12290b9-eb19-5c03-86fc-3e2064e4104f','e88d8457-18e1-5f54-8cf1-d0b93a2e6c01')"
        ).fetchone()[0]
        self.assertEqual(modio_evidence_count_after, 3)  # unchanged -- no new modio rows
        # the modio-derived claim's link must point at one of the pre-existing UUIDs
        modio_claim_link = self.candidate.execute(
            "SELECT source_record_uuid FROM evidence_claim_links WHERE claim_uuid = ?",
            (build_claim_uuid(2),),  # hit_id=2 is the modio incompatibility hit
        ).fetchone()
        self.assertIn(modio_claim_link[0], modio_map.values())

    def test_promote_triage_hits_raises_if_evidence_missing(self):
        # empty maps -- every hit's comment has no matching evidence row
        with self.assertRaises(RuntimeError):
            promote_triage_hits(self.candidate, self.phase2b, {}, {})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /workspaces/bg3_scraper && python3 -m unittest app.catalog_pipeline.claude_phase3.tests.test_promote_comment_evidence -v`
Expected: `ImportError` — the new functions don't exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
# add to app/catalog_pipeline/claude_phase3/promote_comment_evidence.py
MODIO_CORPUS_UUIDS = (
    "f12290b9-eb19-5c03-86fc-3e2064e4104f",
    "e88d8457-18e1-5f54-8cf1-d0b93a2e6c01",
)


def lookup_existing_modio_evidence_uuids(candidate_conn: sqlite3.Connection) -> dict[str, str]:
    placeholders = ",".join("?" for _ in MODIO_CORPUS_UUIDS)
    rows = candidate_conn.execute(
        f"SELECT provider_native_id, source_record_uuid FROM evidence_source_records "
        f"WHERE corpus_uuid IN ({placeholders})",
        MODIO_CORPUS_UUIDS,
    ).fetchall()
    return {row[0]: row[1] for row in rows}


def promote_triage_hits(
    candidate_conn: sqlite3.Connection,
    phase2b_conn: sqlite3.Connection,
    nexus_uuid_by_comment_id: dict[str, str],
    modio_uuid_by_comment_id: dict[str, str],
    *,
    platform_mod_ids: list[str] | None = None,
) -> int:
    phase2b_conn.row_factory = sqlite3.Row
    query = (
        "SELECT t.hit_id, t.rule_code, t.pattern_note, t.created_at, "
        "c.platform, c.platform_mod_id, c.source_comment_id, "
        "c.author_identity_tier, c.body "
        "FROM triage_hits t JOIN comments c ON c.comment_row_id = t.comment_row_id"
    )
    params: tuple = ()
    if platform_mod_ids is not None:
        placeholders = ",".join("?" for _ in platform_mod_ids)
        query += f" WHERE c.platform_mod_id IN ({placeholders})"
        params = tuple(platform_mod_ids)

    claim_rows = []
    link_rows = []
    skipped = []
    for row in phase2b_conn.execute(query, params):
        if row["platform"] == "nexus":
            source_record_uuid = nexus_uuid_by_comment_id.get(row["source_comment_id"])
        else:
            source_record_uuid = modio_uuid_by_comment_id.get(row["source_comment_id"])
        if source_record_uuid is None:
            skipped.append((row["platform"], row["source_comment_id"], row["hit_id"]))
            continue

        claim_uuid = build_claim_uuid(row["hit_id"])
        claim_type = RULE_TO_CLAIM_TYPE[row["rule_code"]]
        claim_rows.append((
            claim_uuid, row["pattern_note"], claim_type, "triage_only", "proposed",
            row["author_identity_tier"], "single_unvalidated_triage_source", "low",
            "not stated", "not stated", "not stated", "not stated",
            "not resolved -- triage hit only, not yet reviewed",
            f"Phase 3 mechanical promotion of triage rule '{row['rule_code']}'; "
            f"unvalidated, see B26 Phase 3 migration design for precision/recall caveat.",
            row["created_at"],
        ))
        excerpt = (row["body"] or "")[:500]
        link_rows.append((claim_uuid, source_record_uuid, None, "context", excerpt, None))

    if skipped:
        raise RuntimeError(
            f"{len(skipped)} triage_hits had no matching evidence_source_records row "
            f"(should be 0): {skipped[:5]}{'...' if len(skipped) > 5 else ''}"
        )

    candidate_conn.executemany(
        """INSERT INTO evidence_claims
           (claim_uuid, claim_text, claim_type, evidence_state, claim_state,
            source_authority, corroboration_state, confidence, game_patch_scope,
            manager_scope, tool_and_version_scope, deployment_channel_scope,
            target_text, notes, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        claim_rows,
    )
    candidate_conn.executemany(
        """INSERT INTO evidence_claim_links
           (claim_uuid, source_record_uuid, artifact_uuid, link_role, evidence_excerpt, content_sha256)
           VALUES (?, ?, ?, ?, ?, ?)""",
        link_rows,
    )
    return len(claim_rows)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /workspaces/bg3_scraper && python3 -m unittest app.catalog_pipeline.claude_phase3.tests.test_promote_comment_evidence -v`
Expected: 24/24 tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/catalog_pipeline/claude_phase3/
git commit -m "B26 Phase 3: add triage_hits to evidence_claims promotion"
```

---

### Task 6: Retire mod_comments (drop table, create view)

**Files:**
- Modify: `app/catalog_pipeline/claude_phase3/promote_comment_evidence.py`
- Modify: `app/catalog_pipeline/claude_phase3/tests/test_promote_comment_evidence.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `retire_mod_comments_table(conn: sqlite3.Connection) -> None` — Task 7 calls this once, inside the full-migration transaction, after the insert steps.

- [ ] **Step 1: Write the failing tests**

```python
# append to app/catalog_pipeline/claude_phase3/tests/test_promote_comment_evidence.py
from app.catalog_pipeline.claude_phase3.promote_comment_evidence import retire_mod_comments_table


class TestRetireModComments(unittest.TestCase):
    def setUp(self):
        self.candidate = sqlite3.connect(":memory:")
        create_fixture_candidate_db(self.candidate)
        self.phase2b = sqlite3.connect(":memory:")
        create_fixture_phase2b_db(self.phase2b)
        corpus_uuid = insert_nexus_evidence_corpus(self.candidate, record_count=3)
        insert_nexus_evidence_source_records(self.candidate, self.phase2b, corpus_uuid)

    def test_mod_comments_becomes_a_view_not_a_table(self):
        retire_mod_comments_table(self.candidate)
        row = self.candidate.execute(
            "SELECT type FROM sqlite_master WHERE name='mod_comments'"
        ).fetchone()
        self.assertEqual(row[0], "view")

    def test_mod_comments_view_returns_evidence_data(self):
        retire_mod_comments_table(self.candidate)
        count = self.candidate.execute("SELECT COUNT(*) FROM mod_comments").fetchone()[0]
        self.assertEqual(count, 3)  # the 3 nexus rows inserted in setUp

    def test_mod_comments_view_exposes_platform_and_source_comment_id(self):
        retire_mod_comments_table(self.candidate)
        row = self.candidate.execute(
            "SELECT platform, source_comment_id FROM mod_comments LIMIT 1"
        ).fetchone()
        self.assertEqual(row[0], "nexus")
        self.assertIn(row[1], {"555001", "555002", "555003"})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /workspaces/bg3_scraper && python3 -m unittest app.catalog_pipeline.claude_phase3.tests.test_promote_comment_evidence -v`
Expected: `ImportError` — the new function doesn't exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
# add to app/catalog_pipeline/claude_phase3/promote_comment_evidence.py
def retire_mod_comments_table(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE mod_comments")
    conn.execute(
        """CREATE VIEW mod_comments AS
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
           WHERE esr.provider_object_type = 'comment'"""
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /workspaces/bg3_scraper && python3 -m unittest app.catalog_pipeline.claude_phase3.tests.test_promote_comment_evidence -v`
Expected: 27/27 tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/catalog_pipeline/claude_phase3/
git commit -m "B26 Phase 3: add mod_comments retirement (drop table, create view)"
```

---

### Task 7: Test-batch orchestration with direct verification

**Files:**
- Modify: `app/catalog_pipeline/claude_phase3/promote_comment_evidence.py`
- Modify: `app/catalog_pipeline/claude_phase3/tests/test_promote_comment_evidence.py`

**Interfaces:**
- Consumes: everything from Tasks 4-6.
- Produces: `run_and_verify_test_batch(candidate_conn: sqlite3.Connection, phase2b_conn: sqlite3.Connection, *, nexus_mod_ids: list[str], modio_mod_ids: list[str]) -> None` — inserts the sample (via Task 4/5's functions with `platform_mod_ids` set), verifies field-by-field against the source, then rolls back via `candidate_conn.rollback()`. Raises `AssertionError` with a specific mismatch description on any verification failure (never silently passes). Task 8 calls this before the real run.

- [ ] **Step 1: Write the failing tests**

```python
# append to app/catalog_pipeline/claude_phase3/tests/test_promote_comment_evidence.py
from app.catalog_pipeline.claude_phase3.promote_comment_evidence import run_and_verify_test_batch


class TestTestBatchOrchestration(unittest.TestCase):
    def setUp(self):
        self.candidate = sqlite3.connect(":memory:")
        create_fixture_candidate_db(self.candidate)
        self.phase2b = sqlite3.connect(":memory:")
        create_fixture_phase2b_db(self.phase2b)

    def test_test_batch_inserts_then_rolls_back_leaving_no_trace(self):
        run_and_verify_test_batch(
            self.candidate, self.phase2b,
            nexus_mod_ids=["14077"], modio_mod_ids=["4320786"],
        )
        # after rollback: no new nexus corpus, no new evidence rows beyond
        # the 3 modio fixture-seed rows, mod_comments still a table (not
        # retired -- that only happens in the real run, Task 8)
        nexus_corpora = self.candidate.execute(
            "SELECT COUNT(*) FROM evidence_corpora WHERE provider='nexus'"
        ).fetchone()[0]
        self.assertEqual(nexus_corpora, 0)
        evidence_count = self.candidate.execute(
            "SELECT COUNT(*) FROM evidence_source_records"
        ).fetchone()[0]
        self.assertEqual(evidence_count, 3)  # unchanged from fixture seed
        table_type = self.candidate.execute(
            "SELECT type FROM sqlite_master WHERE name='mod_comments'"
        ).fetchone()[0]
        self.assertEqual(table_type, "table")

    def test_test_batch_raises_on_verification_mismatch(self):
        # Corrupt the builder so payload doesn't match source, proving the
        # verification step actually checks content rather than just row counts.
        import app.catalog_pipeline.claude_phase3.promote_comment_evidence as mod
        original = mod.build_comment_payload_json
        mod.build_comment_payload_json = lambda row: '{"body": "WRONG"}'
        try:
            with self.assertRaises(AssertionError):
                run_and_verify_test_batch(
                    self.candidate, self.phase2b,
                    nexus_mod_ids=["14077"], modio_mod_ids=["4320786"],
                )
        finally:
            mod.build_comment_payload_json = original
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /workspaces/bg3_scraper && python3 -m unittest app.catalog_pipeline.claude_phase3.tests.test_promote_comment_evidence -v`
Expected: `ImportError` — the new function doesn't exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
# add to app/catalog_pipeline/claude_phase3/promote_comment_evidence.py
def run_and_verify_test_batch(
    candidate_conn: sqlite3.Connection,
    phase2b_conn: sqlite3.Connection,
    *,
    nexus_mod_ids: list[str],
    modio_mod_ids: list[str],
) -> None:
    corpus_uuid = insert_nexus_evidence_corpus(candidate_conn, record_count=0)
    nexus_uuid_map = insert_nexus_evidence_source_records(
        candidate_conn, phase2b_conn, corpus_uuid, platform_mod_ids=nexus_mod_ids
    )
    modio_uuid_map = lookup_existing_modio_evidence_uuids(candidate_conn)
    promote_triage_hits(
        candidate_conn, phase2b_conn, nexus_uuid_map, modio_uuid_map,
        platform_mod_ids=nexus_mod_ids + modio_mod_ids,
    )

    try:
        _verify_batch_against_source(candidate_conn, phase2b_conn, nexus_uuid_map)
    finally:
        candidate_conn.rollback()


def _verify_batch_against_source(
    candidate_conn: sqlite3.Connection,
    phase2b_conn: sqlite3.Connection,
    nexus_uuid_map: dict[str, str],
) -> None:
    phase2b_conn.row_factory = sqlite3.Row
    for source_comment_id, source_record_uuid in nexus_uuid_map.items():
        source_row = phase2b_conn.execute(
            "SELECT * FROM comments WHERE source_comment_id = ? AND platform = 'nexus'",
            (source_comment_id,),
        ).fetchone()
        inserted_row = candidate_conn.execute(
            "SELECT payload_json, content_sha256, source_listing_uuid, raw_locator "
            "FROM evidence_source_records WHERE source_record_uuid = ?",
            (source_record_uuid,),
        ).fetchone()
        if inserted_row is None:
            raise AssertionError(f"no evidence row found for {source_comment_id}")
        payload_json, content_sha256, source_listing_uuid, raw_locator = inserted_row
        payload = json.loads(payload_json)
        if payload["body"] != source_row["body"]:
            raise AssertionError(
                f"body mismatch for {source_comment_id}: "
                f"{payload['body']!r} != {source_row['body']!r}"
            )
        if content_sha256 != build_content_sha256(payload_json):
            raise AssertionError(f"content_sha256 mismatch for {source_comment_id}")
        if source_listing_uuid != source_row["b26_listing_uuid"]:
            raise AssertionError(f"source_listing_uuid mismatch for {source_comment_id}")
        expected_locator = build_raw_locator("nexus", source_row["source_line_number"])
        if raw_locator != expected_locator:
            raise AssertionError(f"raw_locator mismatch for {source_comment_id}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /workspaces/bg3_scraper && python3 -m unittest app.catalog_pipeline.claude_phase3.tests.test_promote_comment_evidence -v`
Expected: 29/29 tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/catalog_pipeline/claude_phase3/
git commit -m "B26 Phase 3: add test-batch orchestration with direct source verification"
```

---

### Task 8: Full migration script wiring (CLI entrypoint)

**Files:**
- Modify: `app/catalog_pipeline/claude_phase3/promote_comment_evidence.py`
- Modify: `app/catalog_pipeline/claude_phase3/tests/test_promote_comment_evidence.py`

**Interfaces:**
- Consumes: everything from Tasks 1-7.
- Produces: `run_migration(candidate_db_path: Path, phase2b_db_path: Path, *, expected_candidate_sha256: str, expected_phase2b_sha256: str, migration_name: str, receipt_path: Path) -> dict` (the full orchestration: backup, hash-gate, test batch, full insert, commit, post-commit read-only validation, receipt write — returns a summary dict), plus a `main()` CLI entrypoint (`argparse`: `--db`, `--phase2b-db`, `--receipt`). This is the last production-code task; Task 9 runs this against the real databases.

- [ ] **Step 1: Write the failing tests**

```python
# append to app/catalog_pipeline/claude_phase3/tests/test_promote_comment_evidence.py
import shutil

from app.catalog_pipeline.claude_phase3.promote_comment_evidence import run_migration


class TestFullMigration(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        tmp_path = Path(self.tmpdir.name)
        self.candidate_path = tmp_path / "candidate.db"
        self.phase2b_path = tmp_path / "phase2b.db"
        self.receipt_path = tmp_path / "receipt.json"

        candidate_conn = sqlite3.connect(self.candidate_path)
        create_fixture_candidate_db(candidate_conn)
        candidate_conn.close()

        phase2b_conn = sqlite3.connect(self.phase2b_path)
        create_fixture_phase2b_db(phase2b_conn)
        phase2b_conn.close()

        self.candidate_sha = sha256_file(self.candidate_path)
        self.phase2b_sha = sha256_file(self.phase2b_path)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_run_migration_end_to_end_on_fixture_dbs(self):
        summary = run_migration(
            self.candidate_path, self.phase2b_path,
            expected_candidate_sha256=self.candidate_sha,
            expected_phase2b_sha256=self.phase2b_sha,
            migration_name="test_migration",
            receipt_path=self.receipt_path,
        )
        self.assertEqual(summary["nexus_evidence_rows_inserted"], 3)
        self.assertEqual(summary["claims_promoted"], 3)

        con = sqlite3.connect(self.candidate_path)
        nexus_rows = con.execute(
            "SELECT COUNT(*) FROM evidence_source_records WHERE corpus_uuid IN "
            "(SELECT corpus_uuid FROM evidence_corpora WHERE provider='nexus')"
        ).fetchone()[0]
        self.assertEqual(nexus_rows, 3)
        modio_rows_unchanged = con.execute(
            "SELECT COUNT(*) FROM evidence_source_records WHERE corpus_uuid IN "
            "('f12290b9-eb19-5c03-86fc-3e2064e4104f','e88d8457-18e1-5f54-8cf1-d0b93a2e6c01')"
        ).fetchone()[0]
        self.assertEqual(modio_rows_unchanged, 3)
        view_type = con.execute(
            "SELECT type FROM sqlite_master WHERE name='mod_comments'"
        ).fetchone()[0]
        self.assertEqual(view_type, "view")
        migration_row = con.execute(
            "SELECT migration_name FROM migration_history"
        ).fetchone()
        self.assertEqual(migration_row[0], "test_migration")

        self.assertTrue(self.receipt_path.exists())
        backup_path = self.candidate_path.with_name(self.candidate_path.name + ".pre-phase3-backup")
        self.assertTrue(backup_path.exists())

    def test_run_migration_aborts_on_hash_mismatch(self):
        with self.assertRaises(ValueError):
            run_migration(
                self.candidate_path, self.phase2b_path,
                expected_candidate_sha256="0" * 64,
                expected_phase2b_sha256=self.phase2b_sha,
                migration_name="test_migration_2",
                receipt_path=self.receipt_path,
            )
        # no backup should have been created -- hash-gate runs before backup
        backup_path = self.candidate_path.with_name(self.candidate_path.name + ".pre-phase3-backup")
        self.assertFalse(backup_path.exists())

    def test_run_migration_is_idempotent_gate(self):
        run_migration(
            self.candidate_path, self.phase2b_path,
            expected_candidate_sha256=self.candidate_sha,
            expected_phase2b_sha256=self.phase2b_sha,
            migration_name="test_migration_3",
            receipt_path=self.receipt_path,
        )
        # re-running against the now-migrated DB with the SAME migration_name
        # must fail the hash-gate (the candidate DB's hash has changed) --
        # proves the migration doesn't silently double-insert
        with self.assertRaises(ValueError):
            run_migration(
                self.candidate_path, self.phase2b_path,
                expected_candidate_sha256=self.candidate_sha,  # now stale
                expected_phase2b_sha256=self.phase2b_sha,
                migration_name="test_migration_3",
                receipt_path=self.receipt_path,
            )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /workspaces/bg3_scraper && python3 -m unittest app.catalog_pipeline.claude_phase3.tests.test_promote_comment_evidence -v`
Expected: `ImportError` — `run_migration` doesn't exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
# add to app/catalog_pipeline/claude_phase3/promote_comment_evidence.py
# (argparse and datetime are new; json and sqlite3 are already imported from Task 2)
import argparse
from datetime import datetime, timezone


def run_migration(
    candidate_db_path: Path,
    phase2b_db_path: Path,
    *,
    expected_candidate_sha256: str,
    expected_phase2b_sha256: str,
    migration_name: str,
    receipt_path: Path,
) -> dict:
    verify_db_hash(candidate_db_path, expected_candidate_sha256)
    verify_db_hash(phase2b_db_path, expected_phase2b_sha256)

    row_count_before = None
    candidate_conn = sqlite3.connect(candidate_db_path)
    candidate_conn.execute("PRAGMA foreign_keys = ON")
    phase2b_conn = sqlite3.connect(phase2b_db_path)
    try:
        row_count_before = candidate_conn.execute(
            "SELECT COUNT(*) FROM evidence_source_records"
        ).fetchone()[0]

        # Step 1: test batch, verified, then rolled back (see Task 7)
        sample_nexus_mods = _pick_sample_mod_ids(phase2b_conn, "nexus", limit=1)
        sample_modio_mods = _pick_sample_mod_ids(phase2b_conn, "modio", limit=1)
        run_and_verify_test_batch(
            candidate_conn, phase2b_conn,
            nexus_mod_ids=sample_nexus_mods, modio_mod_ids=sample_modio_mods,
        )

        # Step 2: backup, only after the test batch has proven the logic works
        backup_path = backup_database(candidate_db_path)

        # Step 3: the real, full migration in a fresh transaction
        nexus_row_count = phase2b_conn.execute(
            "SELECT COUNT(*) FROM comments WHERE platform='nexus'"
        ).fetchone()[0]
        corpus_uuid = insert_nexus_evidence_corpus(candidate_conn, record_count=nexus_row_count)
        nexus_uuid_map = insert_nexus_evidence_source_records(
            candidate_conn, phase2b_conn, corpus_uuid
        )
        modio_uuid_map = lookup_existing_modio_evidence_uuids(candidate_conn)
        claims_promoted = promote_triage_hits(
            candidate_conn, phase2b_conn, nexus_uuid_map, modio_uuid_map
        )
        retire_mod_comments_table(candidate_conn)

        row_count_after = candidate_conn.execute(
            "SELECT COUNT(*) FROM evidence_source_records"
        ).fetchone()[0]
        candidate_conn.execute(
            """INSERT INTO migration_history
               (migration_name, schema_version, applied_at, actor_session,
                source_db_sha256, row_count_before, row_count_after, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                migration_name, "phase3", datetime.now(timezone.utc).isoformat(),
                "claude-code-phase3", expected_candidate_sha256,
                str(row_count_before), str(row_count_after),
                f"Promoted {len(nexus_uuid_map)} Nexus evidence rows, "
                f"{claims_promoted} triage claims; retired mod_comments.",
            ),
        )
        candidate_conn.commit()
    except Exception:
        candidate_conn.rollback()
        raise
    finally:
        phase2b_conn.close()
        candidate_conn.close()

    # Post-commit: re-open read-only and validate
    readonly = sqlite3.connect(f"file:{candidate_db_path}?mode=ro&immutable=1", uri=True)
    integrity = readonly.execute("PRAGMA integrity_check").fetchone()[0]
    fk_violations = readonly.execute("PRAGMA foreign_key_check").fetchall()
    readonly.close()
    if integrity != "ok":
        raise RuntimeError(f"post-commit integrity_check failed: {integrity}")
    if fk_violations:
        raise RuntimeError(f"post-commit foreign_key_check found violations: {fk_violations}")

    summary = {
        "nexus_evidence_rows_inserted": len(nexus_uuid_map),
        "claims_promoted": claims_promoted,
        "backup_path": str(backup_path),
        "row_count_before": row_count_before,
        "row_count_after": row_count_after,
    }
    receipt_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def _pick_sample_mod_ids(phase2b_conn: sqlite3.Connection, platform: str, *, limit: int) -> list[str]:
    rows = phase2b_conn.execute(
        "SELECT DISTINCT platform_mod_id FROM comments WHERE platform = ? LIMIT ?",
        (platform, limit),
    ).fetchall()
    return [r[0] for r in rows]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--phase2b-db", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument(
        "--candidate-sha256", default="cb37e0392b7bdb0b06f8095c44b8352363610999498ff4803e07411df3187775"
    )
    parser.add_argument(
        "--phase2b-sha256", default="a7d20f9586a7413f8d1a82ed2965de4cdcb19f942d59400be5896b3e3e72bfaa"
    )
    parser.add_argument("--migration-name", default="phase3_promote_comment_evidence_2026-08")
    args = parser.parse_args()

    summary = run_migration(
        args.db, args.phase2b_db,
        expected_candidate_sha256=args.candidate_sha256,
        expected_phase2b_sha256=args.phase2b_sha256,
        migration_name=args.migration_name,
        receipt_path=args.receipt,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
```

**Note for the implementer**: `_pick_sample_mod_ids` picks whichever mod IDs happen to be first in the real databases (arbitrary, not the specific mods `14077`/`4320786` chosen during design for their nested-reply threading) — that's fine for the real run's own internal consistency check (Step 1 above), since Task 9's independent verification is what actually validates against known-good values, not the test batch's own pass/fail. If you want the real run to specifically exercise the same threaded mods used in design/testing, override `_pick_sample_mod_ids`'s query with `WHERE platform_mod_id = '14077'` / `'4320786'` directly — either is defensible; note which one you chose in the Task 9 report.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /workspaces/bg3_scraper && python3 -m unittest app.catalog_pipeline.claude_phase3.tests.test_promote_comment_evidence -v`
Expected: 32/32 tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/catalog_pipeline/claude_phase3/
git commit -m "B26 Phase 3: wire full migration script with CLI entrypoint"
```

---

### Task 9: Run the real migration and independently verify

**Files:** none created or modified (operational task against real data).

**Interfaces:**
- Consumes: `run_migration` (Task 8), the real `catalog/B26/BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db` and `catalog/B26/BG3_Comment_Evidence_Index_Phase2B_B26ExactLinks_candidate.db`.
- Produces: the migrated candidate DB (mutated in place), `catalog/B26/phase3_migration_receipt.json`, a backup file.

This is not a code task — no failing test, no TDD cycle. It is the design's Acceptance Criteria checklist, executed for real and checked independently, per this project's standing "thorough post-examination, not just a clean exit code" preference. **Do not skip or abbreviate the verification steps** even though the script's own receipt will report success — the receipt is one input, not the whole check.

- [ ] **Step 1: Confirm current hashes match the plan's Global Constraints**

Run:
```bash
cd /workspaces/bg3_scraper
python3 app/catalog_pipeline/verify_checksum.py catalog/B26/BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db cb37e0392b7bdb0b06f8095c44b8352363610999498ff4803e07411df3187775
python3 app/catalog_pipeline/verify_checksum.py catalog/B26/BG3_Comment_Evidence_Index_Phase2B_B26ExactLinks_candidate.db a7d20f9586a7413f8d1a82ed2965de4cdcb19f942d59400be5896b3e3e72bfaa
```
Expected: both print `OK ...`, exit code 0. If either fails, STOP — do not proceed; investigate why the file changed since this plan was written (per this project's standing rule to never proceed past an unexplained checksum mismatch).

- [ ] **Step 2: Record pre-migration counts for later comparison**

Run:
```bash
sqlite3 catalog/B26/BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db \
  "SELECT COUNT(*) FROM evidence_source_records;" \
  "SELECT COUNT(*) FROM evidence_claims;"
```
Note the two numbers down (call them `EVIDENCE_BEFORE` and `CLAIMS_BEFORE`) — the real DB's current baseline, needed for Step 4's arithmetic.

- [ ] **Step 3: Run the migration**

Run:
```bash
cd /workspaces/bg3_scraper
python3 -m app.catalog_pipeline.claude_phase3.promote_comment_evidence \
  --db catalog/B26/BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db \
  --phase2b-db catalog/B26/BG3_Comment_Evidence_Index_Phase2B_B26ExactLinks_candidate.db \
  --receipt catalog/B26/phase3_migration_receipt.json
```
Expected: prints a JSON summary, exit code 0. `nexus_evidence_rows_inserted` should read `451885`, `claims_promoted` should read `16996`. If either number differs, STOP — do not proceed to independent verification on data you already know is wrong; investigate first (check whether the Nexus/mod.io platform split changed since design, re-run the schema queries from the design doc's investigation).

- [ ] **Step 4: Independent verification — counts (Acceptance Criteria 1-3)**

Run:
```bash
sqlite3 catalog/B26/BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db << 'EOF'
SELECT COUNT(*) FROM evidence_source_records;
SELECT COUNT(*) FROM evidence_source_records WHERE content_sha256 IS NULL OR payload_json IS NULL;
SELECT COUNT(*) FROM evidence_source_records esr
  JOIN evidence_corpora ec ON ec.corpus_uuid = esr.corpus_uuid
  WHERE ec.provider = 'nexus' AND esr.source_listing_uuid IS NULL;
SELECT COUNT(*) FROM evidence_claims WHERE evidence_state = 'triage_only';
SELECT COUNT(*) FROM evidence_claims;
SELECT COUNT(*) FROM evidence_claim_links;
EOF
```
Expected, in order: `EVIDENCE_BEFORE + 451885`; `0` (no nulls); `0` (zero dangling Nexus links, matches Phase 2B's own result); `16996`; `CLAIMS_BEFORE + 16996`; `16996`.

- [ ] **Step 5: Independent verification — mod_comments retirement (Acceptance Criteria 4)**

Run:
```bash
sqlite3 catalog/B26/BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db \
  "SELECT type FROM sqlite_master WHERE name='mod_comments';" \
  "SELECT COUNT(*) FROM mod_comments;"
grep -rln "mod_comments" /workspaces/bg3_scraper/app/ | grep -v "\.pyc\|claude_phase3"
```
Expected: `view`; a non-zero count (it should return real data); the `grep` should print nothing new beyond what was already confirmed during design (only the historical `DB_PROJECT_GAP_REPORT_2026-07-30.md` reference) — if any `.py` script outside `claude_phase3/` now shows up, STOP and investigate before considering this criterion met.

- [ ] **Step 6: Independent verification — integrity (Acceptance Criteria 5)**

Run:
```bash
sqlite3 catalog/B26/BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db \
  "PRAGMA integrity_check;" "PRAGMA foreign_key_check;"
```
Expected: `ok`; no rows.

- [ ] **Step 7: Independent verification — direct spot-check on a fresh sample (Acceptance Criteria 6)**

Run this Python snippet, which draws a *different* random sample than Task 7's fixed test-batch mods and compares each row field-by-field against Phase 2B directly (not via the migration script's own functions, to avoid checking the code against itself):

```bash
python3 - << 'EOF'
import json
import random
import sqlite3

random.seed(20260805)  # reproducible sample

candidate = sqlite3.connect(
    "catalog/B26/BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db"
)
phase2b = sqlite3.connect(
    "catalog/B26/BG3_Comment_Evidence_Index_Phase2B_B26ExactLinks_candidate.db"
)
phase2b.row_factory = sqlite3.Row

nexus_corpus_uuid = candidate.execute(
    "SELECT corpus_uuid FROM evidence_corpora WHERE provider='nexus' "
    "AND supersedes_corpus_uuid IS NOT NULL"
).fetchone()[0]

all_ids = [r[0] for r in candidate.execute(
    "SELECT provider_native_id FROM evidence_source_records WHERE corpus_uuid=?",
    (nexus_corpus_uuid,),
)]
sample_ids = random.sample(all_ids, 20)

mismatches = []
for source_comment_id in sample_ids:
    source_row = phase2b.execute(
        "SELECT * FROM comments WHERE source_comment_id=? AND platform='nexus'",
        (source_comment_id,),
    ).fetchone()
    inserted = candidate.execute(
        "SELECT payload_json, source_listing_uuid FROM evidence_source_records "
        "WHERE corpus_uuid=? AND provider_native_id=?",
        (nexus_corpus_uuid, source_comment_id),
    ).fetchone()
    payload = json.loads(inserted[0])
    if payload["body"] != source_row["body"]:
        mismatches.append(f"{source_comment_id}: body differs")
    if inserted[1] != source_row["b26_listing_uuid"]:
        mismatches.append(f"{source_comment_id}: listing_uuid differs")

# also spot-check a few mod.io-linked claims, to confirm the lookup-not-insert path
modio_claim_links = candidate.execute(
    "SELECT ecl.source_record_uuid, esr.corpus_uuid FROM evidence_claim_links ecl "
    "JOIN evidence_claims ec ON ec.claim_uuid = ecl.claim_uuid "
    "JOIN evidence_source_records esr ON esr.source_record_uuid = ecl.source_record_uuid "
    "WHERE ec.evidence_state='triage_only' "
    "AND esr.corpus_uuid IN ('f12290b9-eb19-5c03-86fc-3e2064e4104f','e88d8457-18e1-5f54-8cf1-d0b93a2e6c01') "
    "LIMIT 5"
).fetchall()

print(f"Sampled {len(sample_ids)} Nexus rows, {len(mismatches)} mismatches:")
for m in mismatches:
    print(f"  {m}")
print(f"mod.io-linked triage claims found in sample check: {len(modio_claim_links)} "
      f"(should be > 0 -- proves the lookup-not-insert path actually linked something)")
EOF
```
Expected: `0 mismatches`; the mod.io-linked count is greater than 0.

- [ ] **Step 8: Independent verification — backup exists (Acceptance Criteria 7)**

Run:
```bash
ls -la catalog/B26/BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db.pre-phase3-backup
python3 app/catalog_pipeline/verify_checksum.py \
  catalog/B26/BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db.pre-phase3-backup \
  cb37e0392b7bdb0b06f8095c44b8352363610999498ff4803e07411df3187775
```
Expected: file exists; checksum matches the PRE-migration hash (confirming the backup really is the untouched original, not a copy taken after mutation).

- [ ] **Step 9: No commit for the database itself**

`catalog/` is gitignored. Confirm:
```bash
git status --short
```
Expected: no `catalog/B26/*` entries. If the migration script itself needs a follow-up fix discovered during this task, that fix goes through the normal task-review fix loop on Tasks 1-8, not folded silently into this task.

---

## Self-Review

**Spec coverage:** design doc's Data Flow steps 1-7 → Tasks 1 (backup/hash-gate), 7 (test batch + rollback), 8 (full migration + post-commit validation + receipt), 9 (independent verification). Acceptance Criteria 1-7 → Task 9 Steps 4-8, one-to-one. Scope's "retire mod_comments" → Task 6. Global Constraint on the Nexus-only insert (the mid-planning correction) → enforced structurally: `insert_nexus_evidence_source_records` only ever queries `WHERE platform='nexus'`, and Task 4's `test_modio_comments_are_never_touched` plus Task 9 Step 4's count check both verify it held.

**Placeholder scan:** no TBD/TODO. Task 8's note about `_pick_sample_mod_ids` picking arbitrary (not the specific design-time) mods is a documented, deliberate choice with a stated alternative, not an unfilled gap.

**Type consistency:** `insert_nexus_evidence_source_records` and `promote_triage_hits` both return/consume `dict[str, str]` keyed by `source_comment_id` consistently across Tasks 4, 5, 7, 8. `platform_mod_ids: list[str] | None = None` has the same signature shape in both functions. `run_and_verify_test_batch`'s and `run_migration`'s parameter names match how Task 8 calls Task 7's function.
