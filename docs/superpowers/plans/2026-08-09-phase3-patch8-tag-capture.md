# Phase 3, Workstream 1: Patch-8 Tag Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fetch every Nexus BG3 mod's full tag list in bulk (the real gap — mod.io's side is already in the DB) and load it into the existing `platform_tags` table, closing the patch-8-compatibility gap from the Gap Report.

**Architecture:** A standalone fetch script (`nexus_tags_scraper.py`) pulls all Nexus tags via one paginated, unauthenticated GraphQL query and writes them to a gitignored JSONL file. A separate migration script (`load_nexus_tags.py`), following this project's established `claude_phase3`/`claude_phase4` hash-gate/backup/transaction/receipt discipline, loads that JSONL into `platform_tags`, resolving each Nexus mod ID to a `listing_id` via `platform_listings`.

**Tech Stack:** Python 3.14 (`py` launcher), `requests`, `sqlite3` (stdlib), `pytest`.

## Global Constraints

- Every DB write hash-gates against a known-good pre-migration SHA-256 first and refuses to proceed on an unexplained mismatch (standing project rule — see CLAUDE.md).
- Every DB write backs up the database first, using its own distinct backup-file suffix (the Phase 4 postmortem found shared suffixes silently clobber each other — each migration script gets a unique suffix).
- Every DB write happens inside a single transaction; any failure rolls back cleanly, leaving the DB untouched.
- Every migration writes a JSON receipt (gitignored, under `catalog/B26/`) and is independently re-verified after running (row counts re-queried directly, `PRAGMA integrity_check`, zero FK violations) — never trust only the script's own printed summary.
- Scraper output files always open in **append mode if they already exist**, regardless of `--resume` (the v1.13 data-loss lesson in CLAUDE.md — a script must never silently truncate prior output).
- Out of scope, per the approved design doc (`docs/superpowers/specs/2026-08-09-phase3-patch8-tag-capture-design.md`): no changes to `nexus_bg3_scraper.py`, no refresh of mod.io's existing `platform_tags` data, no `risk_flags` involvement, no `conflict_checker.py` / loadout-advisor code.

---

### Task 1: Build and validate `nexus_tags_scraper.py`

**Files:**
- Create: `app/scripts/nexus_tags_scraper.py`

**Interfaces:**
- Produces: `data/nexus/nexus_tags.jsonl` — one JSON line per Nexus mod: `{"nexus_mod_id": <int>, "tags": [<str>, ...], "_fetched_at": <ISO8601 str>}`. Task 3 onward consumes this exact shape (`nexus_mod_id`, `tags`).

- [ ] **Step 1: Write the fetch script**

```python
#!/usr/bin/env python3
"""
nexus_tags_scraper.py  v1.0  (2026-08-09)
================================================================================
Bulk-fetches every BG3 Nexus mod's full tag list via the unauthenticated
GraphQL API -- the real gap behind Phase 3's patch-8 tag capture workstream
(see docs/superpowers/specs/2026-08-09-phase3-patch8-tag-capture-design.md).

nexus_bg3_scraper.py's v1 REST API calls have NO tags field at all (confirmed
live 2026-08-09 -- the existing has_non_english_tag(mod.get("tags") or [])
filter has always silently operated on an empty list). Tags only exist via
GraphQL's mods() query, under a per-mod `tags { name }` field -- confirmed
live to include e.g. "Patch 8 Compatible".

Query, same host/endpoint as nexus_collections_scraper.py:
  https://api.nexusmods.com/v2/graphql
  mods(filter: {gameId: {value: "3474"}}, count, offset) {
    totalCount
    nodes { modId tags { name } }
  }
-- offset/count paginated (not Relay cursor-based), confirmed live: no auth
needed, ~189 pages at count=100 for ~18,870 current BG3 Nexus mods.

USAGE:
  py nexus_tags_scraper.py           # full sweep
  py nexus_tags_scraper.py --limit 3  # test on first 3 pages (~300 mods)
  py nexus_tags_scraper.py --resume   # continue from last completed offset
================================================================================
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parents[2]
GRAPHQL_URL = "https://api.nexusmods.com/v2/graphql"
GAME_ID = "3474"
PAGE_SIZE = 100
REQUEST_DELAY = 0.3

DATA_DIR = BASE_DIR / "data" / "nexus"
DATA_DIR.mkdir(parents=True, exist_ok=True)
TAGS_FILE = DATA_DIR / "nexus_tags.jsonl"
PROGRESS_FILE = DATA_DIR / "nexus_tags_progress.json"

TAGS_QUERY = """
query($gid: String!, $count: Int!, $offset: Int!) {
  mods(filter: {gameId: {value: $gid}}, count: $count, offset: $offset) {
    totalCount
    nodes { modId tags { name } }
  }
}
"""


def gql(session: requests.Session, variables: dict) -> dict:
    resp = session.post(GRAPHQL_URL, json={"query": TAGS_QUERY, "variables": variables}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(f"GraphQL error: {data['errors']}")
    return data["data"]


def load_progress() -> int:
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text()).get("next_offset", 0)
    return 0


def save_progress(next_offset: int) -> None:
    PROGRESS_FILE.write_text(json.dumps({"next_offset": next_offset}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="Only fetch the first N pages (0 = all)")
    parser.add_argument("--resume", action="store_true", help="Continue from the last completed offset")
    args = parser.parse_args()

    session = requests.Session()
    offset = load_progress() if args.resume else 0
    # Always append if the file already exists, regardless of --resume -- the
    # v1.13 data-loss lesson (CLAUDE.md): a script must never silently
    # truncate prior output just because --resume was forgotten.
    mode = "a" if TAGS_FILE.exists() else "w"

    pages_fetched = 0
    total_mods_written = 0

    with open(TAGS_FILE, mode, encoding="utf-8") as out:
        while True:
            data = gql(session, {"gid": GAME_ID, "count": PAGE_SIZE, "offset": offset})
            page = data["mods"]
            nodes = page["nodes"]
            total_count = page["totalCount"]
            now = datetime.now(timezone.utc).isoformat()

            for node in nodes:
                out.write(json.dumps({
                    "nexus_mod_id": node["modId"],
                    "tags": [t["name"] for t in (node.get("tags") or [])],
                    "_fetched_at": now,
                }, ensure_ascii=False) + "\n")
            out.flush()
            total_mods_written += len(nodes)

            offset += len(nodes)
            pages_fetched += 1
            save_progress(offset)
            print(f"page {pages_fetched}: offset {offset}/{total_count} ({total_mods_written} mods written)")

            if not nodes or offset >= total_count:
                break
            if args.limit and pages_fetched >= args.limit:
                print(f"--limit {args.limit} reached, stopping early")
                break
            time.sleep(REQUEST_DELAY)

    print(f"\nDone. {total_mods_written} mod tag-list rows written to {TAGS_FILE}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run a small live validation**

Run: `py app/scripts/nexus_tags_scraper.py --limit 2`
Expected: prints 2 pages, ends with "Done. ~200 mod tag-list rows written to .../data/nexus/nexus_tags.jsonl".

- [ ] **Step 3: Verify the output shape**

Run:
```bash
py -c "
import json
rows = [json.loads(l) for l in open('data/nexus/nexus_tags.jsonl', encoding='utf-8')]
print('rows:', len(rows))
print('sample:', rows[0])
print('has patch8 tag on any row:', any('Patch 8 Compatible' in r['tags'] for r in rows))
"
```
Expected: `rows` is ~200, `sample` has `nexus_mod_id` (int), `tags` (list of str), `_fetched_at` (str). Confirm at least one row's `tags` contains `"Patch 8 Compatible"` given a 20% base rate across ~200 mods (not guaranteed on every run, but check manually if false — a real absence across 200 mods would be worth a second look before trusting the full sweep).

- [ ] **Step 4: Clean up the validation run's output**

The `--limit 2` test data must not leak into the real full sweep as duplicate rows (the script always appends). Delete the test artifacts before Task 2:
```bash
rm data/nexus/nexus_tags.jsonl data/nexus/nexus_tags_progress.json
```

- [ ] **Step 5: Commit**

```bash
git add app/scripts/nexus_tags_scraper.py
git commit -m "Add nexus_tags_scraper.py to bulk-fetch Nexus mod tags via GraphQL"
```

---

### Task 2: Run the full Nexus tags sweep

**Files:** none (this task only produces gitignored data output, no code changes)

**Interfaces:**
- Consumes: `app/scripts/nexus_tags_scraper.py` from Task 1.
- Produces: a complete `data/nexus/nexus_tags.jsonl` (all ~18,870 mods) that Task 6 consumes as the migration's source file.

- [ ] **Step 1: Run the full sweep**

Run: `py app/scripts/nexus_tags_scraper.py`
Expected: ~189 pages printed, no errors, ends with "Done. ~18,870 mod tag-list rows written...". Takes a few minutes given the 0.3s inter-page delay.

- [ ] **Step 2: Verify completeness**

Run:
```bash
py -c "
import json
rows = [json.loads(l) for l in open('data/nexus/nexus_tags.jsonl', encoding='utf-8')]
print('total rows:', len(rows))
print('unique mod ids:', len(set(r['nexus_mod_id'] for r in rows)))
patch8 = sum(1 for r in rows if 'Patch 8 Compatible' in r['tags'])
print('Patch 8 Compatible count:', patch8)
"
```
Expected: `total rows` == `unique mod ids` (no duplicate mods — the script never re-fetches an offset range twice in a single run), both close to the live `totalCount` seen in Step 1 output. `Patch 8 Compatible` count should land in the same order of magnitude as the ~3,793 found live during design (the exact number will differ slightly since mods are added/tagged continuously — that's expected, not a bug).

- [ ] **Step 3: No commit needed**

`data/` is gitignored — confirm with `git status` that no new files are staged (the JSONL and progress file should not appear as untracked-to-be-added).

---

### Task 3: Migration scaffolding — parsing and listing lookup (TDD)

**Files:**
- Create: `app/catalog_pipeline/claude_phase5/__init__.py` (empty)
- Create: `app/catalog_pipeline/claude_phase5/tests/__init__.py` (empty)
- Create: `app/catalog_pipeline/claude_phase5/tests/fixtures.py`
- Create: `app/catalog_pipeline/claude_phase5/load_nexus_tags.py`
- Test: `app/catalog_pipeline/claude_phase5/tests/test_load_nexus_tags.py`

**Interfaces:**
- Consumes: `sha256_file`, `verify_db_hash`, `backup_database` from `app.catalog_pipeline.claude_phase3.promote_comment_evidence` (exact same import Phase 4's scripts use).
- Produces: `parse_tags_line(line: str) -> dict` (raises on malformed JSON, deliberately — see Task 5's rollback test), `load_nexus_listing_lookup(conn: sqlite3.Connection) -> dict[str, int]`. Task 4 and Task 5 both consume these two functions by name.

- [ ] **Step 1: Create the package files**

```bash
touch "app/catalog_pipeline/claude_phase5/__init__.py"
touch "app/catalog_pipeline/claude_phase5/tests/__init__.py"
```

- [ ] **Step 2: Write the test fixture module**

```python
# app/catalog_pipeline/claude_phase5/tests/fixtures.py
"""Shared SQLite fixture schema for B26 Phase 5 (patch-8 tag capture) tests."""
import sqlite3


def create_fixture_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE mods (
            mod_uid INTEGER PRIMARY KEY
        );

        CREATE TABLE platform_listings (
            listing_id INTEGER PRIMARY KEY AUTOINCREMENT,
            mod_uid INTEGER REFERENCES mods(mod_uid),
            platform TEXT,
            platform_mod_id TEXT,
            url TEXT,
            author TEXT,
            category_id INTEGER,
            category_name TEXT,
            category_validated TEXT DEFAULT 'unchecked',
            version TEXT,
            last_updated TEXT,
            endorsements_or_downloads INTEGER,
            status TEXT,
            category_check_basis TEXT,
            listing_uuid TEXT
        );

        CREATE TABLE platform_tags (
            tag_id INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_id INTEGER REFERENCES platform_listings(listing_id),
            tag TEXT
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
        """
    )


def insert_listing(conn: sqlite3.Connection, listing_id: int, platform: str, platform_mod_id: str) -> None:
    conn.execute(
        "INSERT INTO platform_listings (listing_id, platform, platform_mod_id) VALUES (?, ?, ?)",
        (listing_id, platform, platform_mod_id),
    )


def insert_existing_tag(conn: sqlite3.Connection, listing_id: int, tag: str) -> None:
    conn.execute(
        "INSERT INTO platform_tags (listing_id, tag) VALUES (?, ?)",
        (listing_id, tag),
    )
```

- [ ] **Step 3: Write the failing tests for parsing and lookup**

```python
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
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `pytest app/catalog_pipeline/claude_phase5/tests/test_load_nexus_tags.py -v`
Expected: FAIL with `ImportError` / `ModuleNotFoundError` — `load_nexus_tags.py` doesn't exist yet.

- [ ] **Step 5: Write the minimal implementation**

```python
# app/catalog_pipeline/claude_phase5/load_nexus_tags.py
"""
load_nexus_tags.py v1.0
========================
B26 Phase 5, workstream 1: loads the bulk Nexus tag capture (from
nexus_tags_scraper.py) into the existing platform_tags table. mod.io's side
of this table is already populated (B25-era, 7,921/8,158 listings) --
Nexus has zero rows before this migration. See
docs/superpowers/specs/2026-08-09-phase3-patch8-tag-capture-design.md for
the full design and the correction to the original research doc's "already
fetched" claim (Nexus's v1 REST API has no tags field at all; only GraphQL
exposes them).
"""
import json
import sqlite3
from pathlib import Path

from app.catalog_pipeline.claude_phase3.promote_comment_evidence import (
    sha256_file,
    verify_db_hash,
    backup_database,
)


def parse_tags_line(line: str) -> dict:
    row = json.loads(line)
    return {
        "nexus_mod_id": str(row["nexus_mod_id"]),
        "tags": row.get("tags") or [],
    }


def load_nexus_listing_lookup(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        "SELECT platform_mod_id, listing_id FROM platform_listings WHERE platform = 'nexus'"
    ).fetchall()
    return {platform_mod_id: listing_id for platform_mod_id, listing_id in rows}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest app/catalog_pipeline/claude_phase5/tests/test_load_nexus_tags.py -v`
Expected: PASS (3 tests).

- [ ] **Step 7: Commit**

```bash
git add app/catalog_pipeline/claude_phase5/
git commit -m "Add claude_phase5 scaffolding: tag-line parsing and Nexus listing lookup"
```

---

### Task 4: Insert logic — mapped, unmapped, and duplicate tags (TDD)

**Files:**
- Modify: `app/catalog_pipeline/claude_phase5/load_nexus_tags.py`
- Test: `app/catalog_pipeline/claude_phase5/tests/test_load_nexus_tags.py`

**Interfaces:**
- Consumes: `parse_tags_line`, `load_nexus_listing_lookup` from Task 3.
- Produces: `insert_nexus_tags(conn, filepath, listing_lookup) -> dict` with keys `mods_seen`, `tags_inserted`, `skipped_unmapped_mods`, `skipped_duplicate_tags`. Task 5 consumes this function and its return-dict shape directly.

- [ ] **Step 1: Write the failing tests**

Append to `app/catalog_pipeline/claude_phase5/tests/test_load_nexus_tags.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest app/catalog_pipeline/claude_phase5/tests/test_load_nexus_tags.py -v -k insert_nexus_tags`
Expected: FAIL with `ImportError` — `insert_nexus_tags` not defined yet.

- [ ] **Step 3: Implement `insert_nexus_tags`**

Append to `app/catalog_pipeline/claude_phase5/load_nexus_tags.py`:

```python
def insert_nexus_tags(conn: sqlite3.Connection, filepath: Path, listing_lookup: dict) -> dict:
    mods_seen = 0
    tags_inserted = 0
    skipped_unmapped_mods = 0
    skipped_duplicate_tags = 0
    seen_pairs = set()

    with open(filepath, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            parsed = parse_tags_line(line)
            mods_seen += 1
            listing_id = listing_lookup.get(parsed["nexus_mod_id"])
            if listing_id is None:
                skipped_unmapped_mods += 1
                continue
            for tag in parsed["tags"]:
                key = (listing_id, tag)
                if key in seen_pairs:
                    skipped_duplicate_tags += 1
                    continue
                seen_pairs.add(key)
                conn.execute(
                    "INSERT INTO platform_tags (listing_id, tag) VALUES (?, ?)",
                    (listing_id, tag),
                )
                tags_inserted += 1

    return {
        "mods_seen": mods_seen,
        "tags_inserted": tags_inserted,
        "skipped_unmapped_mods": skipped_unmapped_mods,
        "skipped_duplicate_tags": skipped_duplicate_tags,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest app/catalog_pipeline/claude_phase5/tests/test_load_nexus_tags.py -v`
Expected: PASS (7 tests total).

- [ ] **Step 5: Commit**

```bash
git add app/catalog_pipeline/claude_phase5/load_nexus_tags.py app/catalog_pipeline/claude_phase5/tests/test_load_nexus_tags.py
git commit -m "Add insert_nexus_tags with unmapped/duplicate-tag guards"
```

---

### Task 5: Migration orchestration — `run_migration` (TDD)

**Files:**
- Modify: `app/catalog_pipeline/claude_phase5/load_nexus_tags.py`
- Test: `app/catalog_pipeline/claude_phase5/tests/test_load_nexus_tags.py`

**Interfaces:**
- Consumes: `sha256_file`, `verify_db_hash`, `backup_database` (from `claude_phase3.promote_comment_evidence`), `load_nexus_listing_lookup`, `insert_nexus_tags` (from Task 3/4).
- Produces: `run_migration(db_path: Path, expected_sha256: str, tags_path: Path) -> dict` (the receipt dict), and a `main()` CLI entrypoint. Task 6 invokes this via the CLI directly against the real candidate DB.

- [ ] **Step 1: Write the failing tests**

Append to `app/catalog_pipeline/claude_phase5/tests/test_load_nexus_tags.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest app/catalog_pipeline/claude_phase5/tests/test_load_nexus_tags.py -v -k run_migration`
Expected: FAIL with `ImportError` — `run_migration` not defined yet.

- [ ] **Step 3: Implement `run_migration` and the CLI entrypoint**

Append to `app/catalog_pipeline/claude_phase5/load_nexus_tags.py`:

```python
import argparse
from datetime import datetime, timezone


def run_migration(db_path: Path, expected_sha256: str, tags_path: Path) -> dict:
    verify_db_hash(db_path, expected_sha256)
    backup_path = backup_database(db_path, suffix=".pre-phase5-nexus-tags-backup")
    tags_sha256 = sha256_file(tags_path)

    conn = sqlite3.connect(str(db_path))
    try:
        # Foreign keys are connection-local and off by default in SQLite --
        # matches the pattern claude_phase3/promote_comment_evidence.py
        # already establishes for this project's migrations.
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN")
        try:
            before = conn.execute("SELECT COUNT(*) FROM platform_tags").fetchone()[0]

            # Claim the migration slot first: migration_history.migration_name
            # is UNIQUE, so a rerun raises IntegrityError right here, before
            # any tag row is touched -- the clean, deterministic failure this
            # project's migrations require (matches claude_phase4's pattern).
            conn.execute(
                """INSERT INTO migration_history
                   (migration_name, schema_version, applied_at, actor_session,
                    source_db_sha256, row_count_before, row_count_after, notes)
                   VALUES (?, 'phase5', ?, 'claude-code-phase5', ?, ?, ?, 'pending')""",
                (
                    "b26-phase5-nexus-tags",
                    datetime.now(timezone.utc).isoformat(),
                    expected_sha256,
                    str(before),
                    str(before),
                ),
            )

            listing_lookup = load_nexus_listing_lookup(conn)
            counts = insert_nexus_tags(conn, tags_path, listing_lookup)
            after = before + counts["tags_inserted"]

            conn.execute(
                """UPDATE migration_history SET row_count_after = ?, notes = ?
                   WHERE migration_name = ?""",
                (
                    str(after),
                    f"+{counts['tags_inserted']} nexus tags "
                    f"(skipped {counts['skipped_unmapped_mods']} unmapped mods, "
                    f"{counts['skipped_duplicate_tags']} duplicate tags), "
                    f"{counts['mods_seen']} mods seen",
                    "b26-phase5-nexus-tags",
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()

    post_sha256 = sha256_file(db_path)
    return {
        "migration_name": "b26-phase5-nexus-tags",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "pre_migration_sha256": expected_sha256,
        "backup_path": str(backup_path),
        "tags_source_sha256": tags_sha256,
        "platform_tags_rows_before": before,
        "platform_tags_rows_after": after,
        **counts,
        "post_migration_sha256": post_sha256,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--candidate-sha256", required=True)
    parser.add_argument("--tags", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()

    receipt = run_migration(args.db, args.candidate_sha256, args.tags)
    args.receipt.write_text(json.dumps(receipt, indent=2))
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest app/catalog_pipeline/claude_phase5/tests/test_load_nexus_tags.py -v`
Expected: PASS (12 tests total).

- [ ] **Step 5: Commit**

```bash
git add app/catalog_pipeline/claude_phase5/load_nexus_tags.py app/catalog_pipeline/claude_phase5/tests/test_load_nexus_tags.py
git commit -m "Add run_migration + CLI for Nexus tags migration, with hash-gate/backup/rollback tests"
```

---

### Task 6: Execute the real migration and verify

**Files:** none (execution + a CLAUDE.md documentation update)

**Interfaces:**
- Consumes: `app/catalog_pipeline/claude_phase5/load_nexus_tags.py`'s CLI (Task 5), `data/nexus/nexus_tags.jsonl` (Task 2).

- [ ] **Step 1: Locate the candidate DB and confirm its current hash**

```bash
py -c "
import hashlib
p = 'catalog/B26/BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db'
print(hashlib.sha256(open(p,'rb').read()).hexdigest())
"
```
Cross-check the printed hash against the most recent hash recorded in CLAUDE.md's B26 Phase 4 section (`3f925145...`, from the `migration_history` backfill). **If it doesn't match, stop and investigate before proceeding** — do not force the migration forward past an unexplained mismatch (standing project rule).

- [ ] **Step 2: Run the migration**

```bash
py -m app.catalog_pipeline.claude_phase5.load_nexus_tags \
  --db catalog/B26/BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db \
  --candidate-sha256 <hash from Step 1> \
  --tags data/nexus/nexus_tags.jsonl \
  --receipt catalog/B26/phase5_nexus_tags_receipt.json
```
Expected: prints the receipt JSON, no exceptions. Note `tags_inserted`, `skipped_unmapped_mods` (expect roughly a third of mods seen, per the known `platform_listings` coverage gap — not a bug), `skipped_duplicate_tags`.

- [ ] **Step 3: Independently verify — do not trust only the script's own receipt**

```bash
py -c "
import sqlite3
con = sqlite3.connect('catalog/B26/BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db')
cur = con.cursor()
print('platform_tags by platform:')
for row in cur.execute('''
    SELECT pl.platform, COUNT(*) FROM platform_tags pt
    JOIN platform_listings pl ON pt.listing_id = pl.listing_id
    GROUP BY pl.platform
'''):
    print(' ', row)
print('Patch 8 Compatible (nexus):', cur.execute('''
    SELECT COUNT(*) FROM platform_tags pt
    JOIN platform_listings pl ON pt.listing_id = pl.listing_id
    WHERE pl.platform='nexus' AND pt.tag='Patch 8 Compatible'
''').fetchone()[0])
print('integrity_check:', cur.execute('PRAGMA integrity_check').fetchone())
print('fk violations:', cur.execute('PRAGMA foreign_key_check').fetchall())
print()
print('spot-check 3 rows:')
for row in cur.execute('''
    SELECT pl.platform_mod_id, pt.tag FROM platform_tags pt
    JOIN platform_listings pl ON pt.listing_id = pl.listing_id
    WHERE pl.platform='nexus' LIMIT 3
'''):
    print(' ', row)
"
```
Expected: `nexus` row count in `platform_tags` matches the receipt's `tags_inserted`; `Patch 8 Compatible (nexus)` count is in the same order of magnitude as the ~2,300-2,400 estimated in the design doc (scaled down from the full ~3,793 by `platform_listings`' ~62.6% Nexus coverage); `integrity_check` returns `ok`; `fk violations` is empty; the 3 spot-checked rows look like real tag names, not garbage.

- [ ] **Step 4: Update CLAUDE.md**

Add a dated entry to CLAUDE.md documenting: what was found (mod.io already covered, Nexus needed a new GraphQL fetch — the correction to the original research doc), the real counts from Step 3, the receipt path, and the final DB hash — matching this project's established documentation convention for every completed migration (see the B26 Phase 3/4 sections as the template).

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "Record Phase 3 patch-8 tag capture migration results in CLAUDE.md"
```

Note: `catalog/B26/phase5_nexus_tags_receipt.json` and the backup DB file stay gitignored (same as every prior phase's receipts), so only CLAUDE.md is committed here.
