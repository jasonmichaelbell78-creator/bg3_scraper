# VOLO Masterlist Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest VOLO's public, CC0-licensed BG3 load-order/deployment-type masterlist into the B26 candidate DB — a load-order divider/group signal, explicit dependency pairs, and a Script-Extender/deployment-type signal — closing part of two gaps from the Gap Report (load-order positioning, deployment type).

**Architecture:** A standalone fetch script (`volo_masterlist_fetch.py`) downloads the masterlist JSON in one unauthenticated GET and writes it plus a provenance manifest to `data/volo/`. A separate migration script (`load_volo_masterlist.py`), following this project's established `claude_phase3`/`claude_phase4`/`claude_phase5` hash-gate/backup/transaction/receipt discipline, name+author fuzzy-matches each VOLO plugin against `mods`/`platform_listings` and writes into two new tables (`catalog_volo_divider_signals`, `catalog_volo_deployment_signals`) plus the existing `load_order_hints` table.

**Tech Stack:** Python 3.14 (`py` launcher), `requests`, `sqlite3` (stdlib), `difflib` (stdlib, fuzzy matching — no new dependency), `pytest`.

## Global Constraints

- Every DB write hash-gates against a known-good pre-migration SHA-256 first and refuses to proceed on an unexplained mismatch (standing project rule — see CLAUDE.md).
- Every DB write backs up the database first, using its own distinct backup-file suffix (`.pre-phase6-volo-backup` — the Phase 4 postmortem found shared suffixes silently clobber each other).
- Every DB write happens inside a single transaction; any failure rolls back cleanly, leaving the DB untouched.
- Every migration writes a JSON receipt (gitignored, under `catalog/B26/`) and is independently re-verified after running (row counts re-queried directly, `PRAGMA integrity_check`, zero FK violations) — never trust only the script's own printed summary.
- Matching never silently guesses: exact normalized name + overlapping author → `matched`; fuzzy name match or an exact name match with no corroborating author → `needs_review`; everything else → `unmatched`. All three statuses are stored, never dropped.
- `load_order_hints` rows are only written from a VOLO dependency pair when the *source* plugin resolves at `matched` tier — a `needs_review`/`unmatched` source never produces a `confidence='high'` structural row it can't back up.
- Ingest all divider-assigned rows regardless of VOLO's own `evidence.source` trust tier — the tier travels with the row (`evidence_source`/`evidence_installs`/etc. columns) for a future consumer to filter on, not pre-filtered here.
- Out of scope, per the approved design doc (`docs/superpowers/specs/2026-08-10-volo-masterlist-ingestion-design.md`): scheduled/automated refresh, a dedicated `groups`-ordering table, ingesting the `incompatible` array (empty in the live file), ingesting the BG3 Load Order Optimizer masterlist (separate, restrictive license), any loadout-advisor consumer code.

---

### Task 1: Build and run `volo_masterlist_fetch.py`

**Files:**
- Create: `app/scripts/volo_masterlist_fetch.py`

**Interfaces:**
- Produces: `data/volo/bg3-masterlist_<YYYY-MM-DD>.json` (raw masterlist, verbatim) and `data/volo/bg3-masterlist_<YYYY-MM-DD>.manifest.json` (`source_url`, `fetched_at`, `file_sha256`, `masterlist_version`, `masterlist_generated`, `masterlist_gameBuild`, `masterlist_gamePatch`, `plugin_count`). Task 7 consumes the raw JSON file directly as the migration's `--masterlist` argument.

This is a single unauthenticated GET (no pagination, no auth, no Cloudflare) — matching this project's convention of not unit-testing `app/scripts/` fetch scripts (see `nexus_tags_scraper.py`, `nexus_collections_scraper.py`, neither of which has a `tests/` directory); correctness is checked by running it live and inspecting the output.

- [ ] **Step 1: Write the fetch script**

```python
#!/usr/bin/env python3
"""
volo_masterlist_fetch.py  v1.0  (2026-08-10)
================================================================================
Downloads VOLO's public, CC0-licensed BG3 load-order/deployment-type
masterlist in one shot -- see
docs/superpowers/specs/2026-08-10-volo-masterlist-ingestion-design.md.

Source (verbatim CC0 1.0 Universal, confirmed via masterlist/LICENSE in the
VOLO repo): https://raw.githubusercontent.com/Moonie8t7/VOLO/main/masterlist/bg3-masterlist.json

No pagination, no auth, no Cloudflare -- a plain GitHub raw-content GET.

USAGE:
  py app/scripts/volo_masterlist_fetch.py
================================================================================
"""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parents[2]
MASTERLIST_URL = "https://raw.githubusercontent.com/Moonie8t7/VOLO/main/masterlist/bg3-masterlist.json"

DATA_DIR = BASE_DIR / "data" / "volo"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def fetch_masterlist() -> bytes:
    resp = requests.get(MASTERLIST_URL, timeout=30)
    resp.raise_for_status()
    return resp.content


def build_manifest(raw_bytes: bytes, masterlist: dict, fetched_at: str) -> dict:
    return {
        "source_url": MASTERLIST_URL,
        "fetched_at": fetched_at,
        "file_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "masterlist_version": masterlist.get("version"),
        "masterlist_generated": masterlist.get("generated"),
        "masterlist_gameBuild": masterlist.get("gameBuild"),
        "masterlist_gamePatch": masterlist.get("gamePatch"),
        "plugin_count": len(masterlist.get("plugins") or []),
    }


def main():
    fetched_at = datetime.now(timezone.utc).isoformat()
    date_stamp = fetched_at[:10]

    raw_bytes = fetch_masterlist()
    masterlist = json.loads(raw_bytes)

    out_path = DATA_DIR / f"bg3-masterlist_{date_stamp}.json"
    out_path.write_bytes(raw_bytes)

    manifest = build_manifest(raw_bytes, masterlist, fetched_at)
    manifest_path = DATA_DIR / f"bg3-masterlist_{date_stamp}.manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"Downloaded {manifest['plugin_count']} plugins (masterlist version {manifest['masterlist_version']})")
    print(f"  -> {out_path}")
    print(f"  -> {manifest_path}")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it for real**

Run: `py app/scripts/volo_masterlist_fetch.py`
Expected: prints `Downloaded 7xxx plugins (masterlist version 2.x.x)` (exact plugin count will differ from the 7,671 seen during design — VOLO is actively growing, that's expected, not a bug) followed by the manifest JSON. Two files appear under `data/volo/`.

- [ ] **Step 3: Sanity-check the output**

```bash
py -c "
import json
p = list(__import__('pathlib').Path('data/volo').glob('bg3-masterlist_*.json'))
p = [f for f in p if not f.name.endswith('.manifest.json')][0]
data = json.load(open(p, encoding='utf-8'))
print('plugins:', len(data['plugins']))
print('has divider:', sum(1 for x in data['plugins'] if 'divider' in x))
print('has usesScriptExtender:', sum(1 for x in data['plugins'] if 'usesScriptExtender' in x))
print('sample:', json.dumps(data['plugins'][0], indent=2))
"
```
Expected: `plugins` in the thousands, `has divider` roughly 85-95% of that, `has usesScriptExtender` a small single-digit percentage (per the corrected 3.9% figure found during design — do not expect anywhere near 31.5%), sample plugin has `name`/`uuid` at minimum.

- [ ] **Step 4: Commit the script**

```bash
git add app/scripts/volo_masterlist_fetch.py
git commit -m "Add volo_masterlist_fetch.py to download VOLO's CC0 load-order masterlist"
```

`data/volo/` itself is gitignored (covered by the blanket `data/` pattern) — only the script is committed here.

---

### Task 2: Migration scaffolding — schema, normalization, and matching (TDD)

**Files:**
- Create: `app/catalog_pipeline/claude_phase6/__init__.py` (empty)
- Create: `app/catalog_pipeline/claude_phase6/tests/__init__.py` (empty)
- Create: `app/catalog_pipeline/claude_phase6/load_volo_masterlist.py`
- Create: `app/catalog_pipeline/claude_phase6/tests/fixtures.py`
- Test: `app/catalog_pipeline/claude_phase6/tests/test_load_volo_masterlist.py`

**Interfaces:**
- Consumes: `sha256_file`, `verify_db_hash`, `backup_database` from `app.catalog_pipeline.claude_phase3.promote_comment_evidence` (same import every prior phase uses).
- Produces: `normalize_text(s: str | None) -> str`, `author_tokens(s: str | None) -> set[str]`, `classify_match(volo_name, volo_author, candidate_name, candidate_author) -> tuple[str, float]` (status is one of `"matched"`/`"needs_review"`/`"unmatched"`), `build_candidate_index(conn) -> list[tuple[int, str, str]]` (`mod_uid, canonical_name, author`), `find_best_match(volo_name, volo_author, candidates) -> tuple[int | None, str, float]` (`mod_uid, status, score`). `CREATE_DIVIDER_TABLE_SQL`, `CREATE_DEPLOYMENT_TABLE_SQL` module constants. Tasks 3-6 all consume these exact names.

- [ ] **Step 1: Create the package files**

```bash
touch "app/catalog_pipeline/claude_phase6/__init__.py"
touch "app/catalog_pipeline/claude_phase6/tests/__init__.py"
```

- [ ] **Step 2: Write `load_volo_masterlist.py`'s schema constants and matching functions directly**

(These are pure functions with no DB side effects except the two schema constants — the design already fixes their shape from the approved spec, so writing them first, then the fixtures that depend on them, then the tests, avoids a circular fixture/module import ordering problem.)

```python
# app/catalog_pipeline/claude_phase6/load_volo_masterlist.py
"""
load_volo_masterlist.py v1.0
==============================
B26 Phase 3, workstream 2: ingests VOLO's public CC0-licensed masterlist
(load-order divider/group signal, explicit dependency pairs, and
Script-Extender/deployment-type signal) into catalog_volo_divider_signals,
catalog_volo_deployment_signals (both new), and load_order_hints (existing
table, source='volo'). See
docs/superpowers/specs/2026-08-10-volo-masterlist-ingestion-design.md for
the full design, including the corrections found there to the prior
research docs' VOLO coverage figures.
"""
import argparse
import difflib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.catalog_pipeline.claude_phase3.promote_comment_evidence import (
    sha256_file,
    verify_db_hash,
    backup_database,
)

FUZZY_MATCH_THRESHOLD = 0.85

CREATE_DIVIDER_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS catalog_volo_divider_signals (
    signal_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mod_uid INTEGER,
    volo_uuid TEXT NOT NULL,
    volo_name TEXT NOT NULL,
    volo_author TEXT,
    group_name TEXT,
    divider_position INTEGER,
    evidence_source TEXT,
    evidence_installs INTEGER,
    evidence_working_installs INTEGER,
    evidence_broken_installs INTEGER,
    match_status TEXT NOT NULL,
    match_score REAL,
    source_version TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    FOREIGN KEY (mod_uid) REFERENCES mods(mod_uid)
)
"""

CREATE_DEPLOYMENT_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS catalog_volo_deployment_signals (
    signal_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mod_uid INTEGER,
    volo_uuid TEXT NOT NULL,
    volo_name TEXT NOT NULL,
    volo_author TEXT,
    uses_script_extender INTEGER NOT NULL DEFAULT 0,
    feature_flags TEXT,
    match_status TEXT NOT NULL,
    match_score REAL,
    source_version TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    FOREIGN KEY (mod_uid) REFERENCES mods(mod_uid)
)
"""


def normalize_text(s: str | None) -> str:
    if not s:
        return ""
    s = re.sub(r"\([^)]*\)", " ", s)  # strip parenthetical aliases, e.g. "(prev. Djmr)"
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return s.strip()


def author_tokens(s: str | None) -> set[str]:
    return set(normalize_text(s).split())


def classify_match(
    volo_name: str, volo_author: str | None,
    candidate_name: str, candidate_author: str | None,
) -> tuple[str, float]:
    norm_volo_name = normalize_text(volo_name)
    norm_candidate_name = normalize_text(candidate_name)
    name_ratio = difflib.SequenceMatcher(None, norm_volo_name, norm_candidate_name).ratio()

    if norm_volo_name == norm_candidate_name:
        volo_tok = author_tokens(volo_author)
        candidate_tok = author_tokens(candidate_author)
        # Only auto-accept when BOTH sides carry a corroborating author --
        # VOLO's author field is missing on ~88% of its plugins (confirmed
        # during design), so an exact name match with no author on either
        # side is not enough to auto-trust; it's flagged for review instead.
        if volo_tok and candidate_tok and (volo_tok & candidate_tok):
            return "matched", 1.0

    if name_ratio >= FUZZY_MATCH_THRESHOLD:
        return "needs_review", name_ratio

    return "unmatched", name_ratio


def build_candidate_index(conn: sqlite3.Connection) -> list[tuple[int, str, str]]:
    rows = conn.execute(
        """SELECT m.mod_uid, m.canonical_name, pl.author
           FROM mods m JOIN platform_listings pl ON pl.mod_uid = m.mod_uid
           WHERE m.canonical_name IS NOT NULL"""
    ).fetchall()
    return [(mod_uid, name, author) for mod_uid, name, author in rows]


def find_best_match(
    volo_name: str, volo_author: str | None,
    candidates: list[tuple[int, str, str]],
) -> tuple[int | None, str, float]:
    norm_volo_name = normalize_text(volo_name)
    volo_first_token = norm_volo_name.split(" ")[0] if norm_volo_name else ""

    best_mod_uid = None
    best_status = "unmatched"
    best_score = 0.0

    for mod_uid, candidate_name, candidate_author in candidates:
        norm_candidate_name = normalize_text(candidate_name)
        candidate_first_token = norm_candidate_name.split(" ")[0] if norm_candidate_name else ""
        # Cheap prefilter: skip candidates sharing no leading normalized word
        # with the VOLO name -- keeps a full-corpus fuzzy scan tractable
        # (~20k candidates x ~7-8k VOLO plugins). A genuine match with a
        # different leading word is missed (falls to "unmatched" rather than
        # a wrong match) -- the safer failure direction per the design's
        # "don't guess" matching rule.
        if norm_volo_name != norm_candidate_name and volo_first_token != candidate_first_token:
            continue

        status, score = classify_match(volo_name, volo_author, candidate_name, candidate_author)
        if status == "matched":
            return mod_uid, "matched", score
        if status == "needs_review" and score > best_score:
            best_mod_uid, best_status, best_score = mod_uid, "needs_review", score

    return best_mod_uid, best_status, best_score
```

- [ ] **Step 3: Write the fixture module**

```python
# app/catalog_pipeline/claude_phase6/tests/fixtures.py
"""Shared SQLite fixture schema for B26 Phase 6 (VOLO masterlist ingestion) tests."""
import sqlite3

from app.catalog_pipeline.claude_phase6.load_volo_masterlist import (
    CREATE_DIVIDER_TABLE_SQL,
    CREATE_DEPLOYMENT_TABLE_SQL,
)


def create_fixture_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE mods (
            mod_uid INTEGER PRIMARY KEY,
            canonical_name TEXT
        );

        CREATE TABLE platform_listings (
            listing_id INTEGER PRIMARY KEY AUTOINCREMENT,
            mod_uid INTEGER REFERENCES mods(mod_uid),
            platform TEXT,
            platform_mod_id TEXT,
            author TEXT
        );

        CREATE TABLE load_order_hints (
            hint_id INTEGER PRIMARY KEY AUTOINCREMENT,
            mod_uid INTEGER,
            relation_type TEXT,
            relative_to_mod_uid INTEGER,
            relative_to_text TEXT,
            source TEXT,
            source_platform TEXT,
            confidence TEXT,
            supporting_text TEXT
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
    conn.execute(CREATE_DIVIDER_TABLE_SQL)
    conn.execute(CREATE_DEPLOYMENT_TABLE_SQL)


def insert_mod(conn: sqlite3.Connection, mod_uid: int, canonical_name: str) -> None:
    conn.execute("INSERT INTO mods (mod_uid, canonical_name) VALUES (?, ?)", (mod_uid, canonical_name))


def insert_listing(conn: sqlite3.Connection, mod_uid: int, platform: str, platform_mod_id: str, author: str | None) -> None:
    conn.execute(
        "INSERT INTO platform_listings (mod_uid, platform, platform_mod_id, author) VALUES (?, ?, ?, ?)",
        (mod_uid, platform, platform_mod_id, author),
    )
```

- [ ] **Step 4: Write the failing tests**

```python
# app/catalog_pipeline/claude_phase6/tests/test_load_volo_masterlist.py
import json
import sqlite3

import pytest

from app.catalog_pipeline.claude_phase6.load_volo_masterlist import (
    normalize_text,
    author_tokens,
    classify_match,
    build_candidate_index,
    find_best_match,
)
from app.catalog_pipeline.claude_phase6.tests.fixtures import (
    create_fixture_db,
    insert_mod,
    insert_listing,
)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    create_fixture_db(c)
    yield c
    c.close()


def test_normalize_text_strips_parens_punctuation_and_case():
    assert normalize_text("bibsan (prev. Djmr / AlanaSP)") == "bibsan"
    assert normalize_text(None) == ""


def test_normalize_text_collapses_punctuation_to_single_spaces():
    assert normalize_text("Mod: Configuration, Menu!!") == "mod configuration menu"


def test_author_tokens_splits_on_whitespace():
    assert author_tokens("Astra & Sai") == {"astra", "sai"}
    assert author_tokens(None) == set()


def test_classify_match_exact_name_and_overlapping_author_is_matched():
    status, score = classify_match("ImpUI", "bibsan", "ImpUI", "bibsan (prev. Djmr)")
    assert status == "matched"
    assert score == 1.0


def test_classify_match_exact_name_missing_author_is_needs_review_not_matched():
    status, score = classify_match("ImpUI", None, "ImpUI", "bibsan")
    assert status == "needs_review"
    assert score == 1.0


def test_classify_match_exact_name_non_overlapping_author_is_needs_review():
    status, score = classify_match("Cool Mod", "Alice", "Cool Mod", "Bob")
    assert status == "needs_review"
    assert score == 1.0


def test_classify_match_fuzzy_name_above_threshold_is_needs_review():
    status, score = classify_match(
        "Mod Configuration Menu", "Volitio", "Mod Configuration Menus", "Volitio"
    )
    assert status == "needs_review"
    assert score >= 0.85


def test_classify_match_dissimilar_name_is_unmatched():
    status, score = classify_match(
        "Completely Different Thing", "X", "Totally Unrelated Mod", "Y"
    )
    assert status == "unmatched"
    assert score < 0.85


def test_build_candidate_index_returns_mod_uid_name_author(conn):
    insert_mod(conn, 1, "ImpUI")
    insert_listing(conn, 1, "nexus", "366", "bibsan")
    conn.commit()
    candidates = build_candidate_index(conn)
    assert candidates == [(1, "ImpUI", "bibsan")]


def test_find_best_match_returns_matched_on_exact_hit(conn):
    insert_mod(conn, 1, "ImpUI")
    insert_listing(conn, 1, "nexus", "366", "bibsan")
    conn.commit()
    candidates = build_candidate_index(conn)
    mod_uid, status, score = find_best_match("ImpUI", "bibsan (prev. Djmr)", candidates)
    assert (mod_uid, status) == (1, "matched")
    assert score == 1.0


def test_find_best_match_returns_unmatched_when_no_shared_first_token(conn):
    insert_mod(conn, 1, "Something Else Entirely")
    insert_listing(conn, 1, "nexus", "1", "Someone")
    conn.commit()
    candidates = build_candidate_index(conn)
    mod_uid, status, score = find_best_match("ImpUI", "bibsan", candidates)
    assert (mod_uid, status) == (None, "unmatched")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest app/catalog_pipeline/claude_phase6/tests/test_load_volo_masterlist.py -v`
Expected: PASS (11 tests). (Use `python -m pytest`, not bare `pytest` — this project has no root `pytest.ini`/`app/__init__.py`-free layout that bare `pytest` resolves correctly; `python -m pytest` is the confirmed-working invocation, per the Phase 5 session notes in CLAUDE.md.)

- [ ] **Step 6: Commit**

```bash
git add app/catalog_pipeline/claude_phase6/
git commit -m "Add claude_phase6 scaffolding: schema constants, normalization, and name+author matching"
```

---

### Task 3: Divider signal extraction and insertion (TDD)

**Files:**
- Modify: `app/catalog_pipeline/claude_phase6/load_volo_masterlist.py`
- Test: `app/catalog_pipeline/claude_phase6/tests/test_load_volo_masterlist.py`

**Interfaces:**
- Consumes: `find_best_match`, `build_candidate_index` from Task 2.
- Produces: `build_divider_signal_row(plugin, mod_uid, match_status, match_score, source_version, captured_at) -> tuple` (14-field tuple matching `catalog_volo_divider_signals`' column order), `insert_divider_signals(conn, plugins, candidates, source_version, captured_at) -> dict` with keys `divider_rows_inserted`, `divider_matched`, `divider_needs_review`, `divider_unmatched`. Task 6 consumes `insert_divider_signals` and this exact return-dict shape.

- [ ] **Step 1: Write the failing tests**

Append to `app/catalog_pipeline/claude_phase6/tests/test_load_volo_masterlist.py`:

```python
from app.catalog_pipeline.claude_phase6.load_volo_masterlist import (
    build_divider_signal_row,
    insert_divider_signals,
)


def test_build_divider_signal_row_extracts_all_fields():
    plugin = {
        "name": "ImpUI (ImprovedUI)",
        "uuid": "26922ba9-6018-5252-075d-7ff2ba6ed879",
        "group": "User Interface",
        "author": "bibsan",
        "divider": 1,
        "evidence": {"source": "curated", "installs": 53, "workingInstalls": 45, "brokenInstalls": 5},
    }
    row = build_divider_signal_row(plugin, 1, "matched", 1.0, "2.0.0", "2026-08-10T23:56:45.072Z")
    assert row == (
        1, "26922ba9-6018-5252-075d-7ff2ba6ed879", "ImpUI (ImprovedUI)", "bibsan",
        "User Interface", 1, "curated", 53, 45, 5, "matched", 1.0,
        "2.0.0", "2026-08-10T23:56:45.072Z",
    )


def test_build_divider_signal_row_handles_missing_evidence_and_author():
    plugin = {"name": "X", "uuid": "u-1", "group": "Misc", "divider": 5}
    row = build_divider_signal_row(plugin, None, "unmatched", 0.2, "2.0.0", "t")
    assert row == (None, "u-1", "X", None, "Misc", 5, None, None, None, None, "unmatched", 0.2, "2.0.0", "t")


def test_insert_divider_signals_only_includes_plugins_with_divider(conn):
    plugins = [
        {"name": "HasDivider", "uuid": "u-1", "group": "Weapons", "divider": 3, "evidence": {}},
        {"name": "NoDivider", "uuid": "u-2", "group": "unsorted"},  # no 'divider' key
    ]
    counts = insert_divider_signals(conn, plugins, [], "2.0.0", "t")
    conn.commit()
    assert counts["divider_rows_inserted"] == 1
    rows = conn.execute("SELECT volo_name FROM catalog_volo_divider_signals").fetchall()
    assert rows == [("HasDivider",)]


def test_insert_divider_signals_classifies_match_status(conn):
    insert_mod(conn, 1, "HasDivider")
    insert_listing(conn, 1, "nexus", "1", "Author")
    conn.commit()
    candidates = build_candidate_index(conn)
    plugins = [
        {
            "name": "HasDivider", "uuid": "u-1", "group": "Weapons", "author": "Author",
            "divider": 3, "evidence": {},
        },
    ]
    counts = insert_divider_signals(conn, plugins, candidates, "2.0.0", "t")
    conn.commit()
    assert counts == {
        "divider_rows_inserted": 1, "divider_matched": 1, "divider_needs_review": 0, "divider_unmatched": 0,
    }
    row = conn.execute("SELECT mod_uid, match_status FROM catalog_volo_divider_signals").fetchone()
    assert row == (1, "matched")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest app/catalog_pipeline/claude_phase6/tests/test_load_volo_masterlist.py -v -k divider_signal`
Expected: FAIL with `ImportError` — `build_divider_signal_row`/`insert_divider_signals` not defined yet.

- [ ] **Step 3: Implement**

Append to `app/catalog_pipeline/claude_phase6/load_volo_masterlist.py`:

```python
def build_divider_signal_row(
    plugin: dict, mod_uid: int | None, match_status: str, match_score: float,
    source_version: str, captured_at: str,
) -> tuple:
    evidence = plugin.get("evidence") or {}
    return (
        mod_uid,
        plugin["uuid"],
        plugin["name"],
        plugin.get("author"),
        plugin.get("group"),
        plugin.get("divider"),
        evidence.get("source"),
        evidence.get("installs"),
        evidence.get("workingInstalls"),
        evidence.get("brokenInstalls"),
        match_status,
        match_score,
        source_version,
        captured_at,
    )


def insert_divider_signals(
    conn: sqlite3.Connection, plugins: list[dict], candidates: list[tuple[int, str, str]],
    source_version: str, captured_at: str,
) -> dict:
    counts = {"divider_rows_inserted": 0, "divider_matched": 0, "divider_needs_review": 0, "divider_unmatched": 0}
    for plugin in plugins:
        if "divider" not in plugin:
            continue
        mod_uid, status, score = find_best_match(plugin["name"], plugin.get("author"), candidates)
        row = build_divider_signal_row(plugin, mod_uid, status, score, source_version, captured_at)
        conn.execute(
            """INSERT INTO catalog_volo_divider_signals
               (mod_uid, volo_uuid, volo_name, volo_author, group_name, divider_position,
                evidence_source, evidence_installs, evidence_working_installs,
                evidence_broken_installs, match_status, match_score, source_version, captured_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            row,
        )
        counts["divider_rows_inserted"] += 1
        counts[f"divider_{status}"] += 1
    return counts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest app/catalog_pipeline/claude_phase6/tests/test_load_volo_masterlist.py -v`
Expected: PASS (15 tests total).

- [ ] **Step 5: Commit**

```bash
git add app/catalog_pipeline/claude_phase6/
git commit -m "Add divider-signal row builder and insertion with match-status tallies"
```

---

### Task 4: Deployment signal extraction and insertion (TDD)

**Files:**
- Modify: `app/catalog_pipeline/claude_phase6/load_volo_masterlist.py`
- Test: `app/catalog_pipeline/claude_phase6/tests/test_load_volo_masterlist.py`

**Interfaces:**
- Consumes: `find_best_match` from Task 2.
- Produces: `build_deployment_signal_row(plugin, mod_uid, match_status, match_score, source_version, captured_at) -> tuple` (10-field tuple matching `catalog_volo_deployment_signals`' column order), `insert_deployment_signals(conn, plugins, candidates, source_version, captured_at) -> dict` with keys `deployment_rows_inserted`, `deployment_matched`, `deployment_needs_review`, `deployment_unmatched`. Task 6 consumes this exact return-dict shape.

- [ ] **Step 1: Write the failing tests**

Append to `app/catalog_pipeline/claude_phase6/tests/test_load_volo_masterlist.py`:

```python
from app.catalog_pipeline.claude_phase6.load_volo_masterlist import (
    build_deployment_signal_row,
    insert_deployment_signals,
)


def test_build_deployment_signal_row_extracts_fields():
    plugin = {
        "name": "Mod Configuration Menu", "uuid": "u-mcm", "author": "Volitio",
        "usesScriptExtender": True, "featureFlags": ["Lua"],
    }
    row = build_deployment_signal_row(plugin, 1, "matched", 1.0, "2.0.0", "t")
    assert row == (1, "u-mcm", "Mod Configuration Menu", "Volitio", 1, '["Lua"]', "matched", 1.0, "2.0.0", "t")


def test_build_deployment_signal_row_defaults_uses_script_extender_to_zero():
    plugin = {"name": "X", "uuid": "u-2", "featureFlags": ["Osiris"]}
    row = build_deployment_signal_row(plugin, None, "unmatched", 0.1, "2.0.0", "t")
    assert row[4] == 0
    assert row[5] == '["Osiris"]'


def test_insert_deployment_signals_only_includes_plugins_with_a_signal(conn):
    plugins = [
        {"name": "HasSE", "uuid": "u-1", "usesScriptExtender": True},
        {"name": "HasFlags", "uuid": "u-2", "featureFlags": ["Lua"]},
        {"name": "NoSignal", "uuid": "u-3", "group": "Misc", "divider": 1},
    ]
    counts = insert_deployment_signals(conn, plugins, [], "2.0.0", "t")
    conn.commit()
    assert counts["deployment_rows_inserted"] == 2
    names = {r[0] for r in conn.execute("SELECT volo_name FROM catalog_volo_deployment_signals")}
    assert names == {"HasSE", "HasFlags"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest app/catalog_pipeline/claude_phase6/tests/test_load_volo_masterlist.py -v -k deployment_signal`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement**

Append to `app/catalog_pipeline/claude_phase6/load_volo_masterlist.py`:

```python
def build_deployment_signal_row(
    plugin: dict, mod_uid: int | None, match_status: str, match_score: float,
    source_version: str, captured_at: str,
) -> tuple:
    return (
        mod_uid,
        plugin["uuid"],
        plugin["name"],
        plugin.get("author"),
        1 if plugin.get("usesScriptExtender") else 0,
        json.dumps(plugin.get("featureFlags") or []),
        match_status,
        match_score,
        source_version,
        captured_at,
    )


def insert_deployment_signals(
    conn: sqlite3.Connection, plugins: list[dict], candidates: list[tuple[int, str, str]],
    source_version: str, captured_at: str,
) -> dict:
    counts = {"deployment_rows_inserted": 0, "deployment_matched": 0, "deployment_needs_review": 0, "deployment_unmatched": 0}
    for plugin in plugins:
        if not plugin.get("usesScriptExtender") and not plugin.get("featureFlags"):
            continue
        mod_uid, status, score = find_best_match(plugin["name"], plugin.get("author"), candidates)
        row = build_deployment_signal_row(plugin, mod_uid, status, score, source_version, captured_at)
        conn.execute(
            """INSERT INTO catalog_volo_deployment_signals
               (mod_uid, volo_uuid, volo_name, volo_author, uses_script_extender, feature_flags,
                match_status, match_score, source_version, captured_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            row,
        )
        counts["deployment_rows_inserted"] += 1
        counts[f"deployment_{status}"] += 1
    return counts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest app/catalog_pipeline/claude_phase6/tests/test_load_volo_masterlist.py -v`
Expected: PASS (18 tests total).

- [ ] **Step 5: Commit**

```bash
git add app/catalog_pipeline/claude_phase6/
git commit -m "Add deployment-signal row builder and insertion for usesScriptExtender/featureFlags"
```

---

### Task 5: Dependency-pair resolution into `load_order_hints` (TDD)

**Files:**
- Modify: `app/catalog_pipeline/claude_phase6/load_volo_masterlist.py`
- Test: `app/catalog_pipeline/claude_phase6/tests/test_load_volo_masterlist.py`

**Interfaces:**
- Consumes: `find_best_match` from Task 2.
- Produces: `resolve_dependency_target(dep, plugin_by_uuid, candidates) -> tuple[int | None, str]` (`mod_uid` or `None`, plus the text to use — either way the caller decides which DB column it lands in), `insert_load_order_hints_from_dependencies(conn, plugins, candidates) -> dict` with keys `load_order_hints_inserted`, `load_order_hints_skipped_source_unmatched`. Task 6 consumes this exact return-dict shape.

- [ ] **Step 1: Write the failing tests**

Append to `app/catalog_pipeline/claude_phase6/tests/test_load_volo_masterlist.py`:

```python
from app.catalog_pipeline.claude_phase6.load_volo_masterlist import (
    resolve_dependency_target,
    insert_load_order_hints_from_dependencies,
)


def test_resolve_dependency_target_resolves_via_uuid_and_match(conn):
    insert_mod(conn, 2, "CommunityLibrary")
    insert_listing(conn, 2, "nexus", "100", "BG3 Community")
    conn.commit()
    candidates = build_candidate_index(conn)
    plugin_by_uuid = {
        "dep-uuid": {"name": "CommunityLibrary", "uuid": "dep-uuid", "author": "BG3 Community"},
    }
    dep = {"uuid": "dep-uuid", "name": "CommunityLibrary"}
    mod_uid, text = resolve_dependency_target(dep, plugin_by_uuid, candidates)
    assert mod_uid == 2
    assert text == "CommunityLibrary"


def test_resolve_dependency_target_falls_back_to_raw_name_when_unresolvable(conn):
    dep = {"uuid": "unknown-uuid", "name": "SomeExternalMod"}
    mod_uid, text = resolve_dependency_target(dep, {}, [])
    assert mod_uid is None
    assert text == "SomeExternalMod"


def test_insert_load_order_hints_skips_plugin_whose_source_does_not_match(conn):
    plugins = [
        {"name": "Unmatched", "uuid": "u-1", "dependencies": [{"uuid": "u-2", "name": "Other"}]},
    ]
    counts = insert_load_order_hints_from_dependencies(conn, plugins, [])
    conn.commit()
    assert counts == {"load_order_hints_inserted": 0, "load_order_hints_skipped_source_unmatched": 1}
    assert conn.execute("SELECT COUNT(*) FROM load_order_hints").fetchone()[0] == 0


def test_insert_load_order_hints_inserts_resolved_pair(conn):
    insert_mod(conn, 1, "SubclassCompatibilityFramework")
    insert_listing(conn, 1, "nexus", "1", "BG3 Community")
    insert_mod(conn, 2, "CommunityLibrary")
    insert_listing(conn, 2, "nexus", "2", "BG3 Community")
    conn.commit()
    candidates = build_candidate_index(conn)
    plugins = [
        {
            "name": "SubclassCompatibilityFramework", "uuid": "u-1", "author": "BG3 Community",
            "dependencies": [{"uuid": "u-2", "name": "CommunityLibrary"}],
        },
        {"name": "CommunityLibrary", "uuid": "u-2", "author": "BG3 Community"},
    ]
    counts = insert_load_order_hints_from_dependencies(conn, plugins, candidates)
    conn.commit()
    assert counts == {"load_order_hints_inserted": 1, "load_order_hints_skipped_source_unmatched": 0}
    row = conn.execute(
        "SELECT mod_uid, relation_type, relative_to_mod_uid, relative_to_text, source, confidence "
        "FROM load_order_hints"
    ).fetchone()
    assert row == (1, "after", 2, None, "volo", "high")


def test_insert_load_order_hints_uses_relative_to_text_when_target_unresolvable(conn):
    insert_mod(conn, 1, "SoloMod")
    insert_listing(conn, 1, "nexus", "1", "Author")
    conn.commit()
    candidates = build_candidate_index(conn)
    plugins = [
        {
            "name": "SoloMod", "uuid": "u-1", "author": "Author",
            "dependencies": [{"uuid": "unknown", "name": "ExternalRequirement"}],
        },
    ]
    counts = insert_load_order_hints_from_dependencies(conn, plugins, candidates)
    conn.commit()
    assert counts == {"load_order_hints_inserted": 1, "load_order_hints_skipped_source_unmatched": 0}
    row = conn.execute("SELECT relative_to_mod_uid, relative_to_text FROM load_order_hints").fetchone()
    assert row == (None, "ExternalRequirement")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest app/catalog_pipeline/claude_phase6/tests/test_load_volo_masterlist.py -v -k "dependency or load_order_hints"`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement**

Append to `app/catalog_pipeline/claude_phase6/load_volo_masterlist.py`:

```python
def resolve_dependency_target(
    dep: dict, plugin_by_uuid: dict[str, dict], candidates: list[tuple[int, str, str]],
) -> tuple[int | None, str]:
    target_plugin = plugin_by_uuid.get(dep.get("uuid"))
    if target_plugin is not None:
        mod_uid, status, _ = find_best_match(
            target_plugin["name"], target_plugin.get("author"), candidates
        )
        if mod_uid is not None and status == "matched":
            return mod_uid, dep.get("name", target_plugin["name"])
    return None, dep.get("name", "")


def insert_load_order_hints_from_dependencies(
    conn: sqlite3.Connection, plugins: list[dict], candidates: list[tuple[int, str, str]],
) -> dict:
    plugin_by_uuid = {p["uuid"]: p for p in plugins}
    inserted = 0
    skipped_source_unmatched = 0
    for plugin in plugins:
        deps = plugin.get("dependencies") or []
        if not deps:
            continue
        # Only a MATCHED source may produce a confidence='high' structural
        # hint -- a needs_review/unmatched source has no way to be flagged
        # as uncertain within load_order_hints' existing columns, so it's
        # excluded entirely rather than silently overstating confidence.
        source_mod_uid, source_status, _ = find_best_match(
            plugin["name"], plugin.get("author"), candidates
        )
        if source_mod_uid is None or source_status != "matched":
            skipped_source_unmatched += 1
            continue
        for dep in deps:
            target_mod_uid, target_text = resolve_dependency_target(dep, plugin_by_uuid, candidates)
            conn.execute(
                """INSERT INTO load_order_hints
                   (mod_uid, relation_type, relative_to_mod_uid, relative_to_text,
                    source, source_platform, confidence, supporting_text)
                   VALUES (?, 'after', ?, ?, 'volo', NULL, 'high', ?)""",
                (
                    source_mod_uid,
                    target_mod_uid,
                    None if target_mod_uid is not None else target_text,
                    plugin["name"],
                ),
            )
            inserted += 1
    return {
        "load_order_hints_inserted": inserted,
        "load_order_hints_skipped_source_unmatched": skipped_source_unmatched,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest app/catalog_pipeline/claude_phase6/tests/test_load_volo_masterlist.py -v`
Expected: PASS (23 tests total).

- [ ] **Step 5: Commit**

```bash
git add app/catalog_pipeline/claude_phase6/
git commit -m "Add dependency-pair resolution into load_order_hints (source='volo')"
```

---

### Task 6: Migration orchestration — `run_migration` (TDD)

**Files:**
- Modify: `app/catalog_pipeline/claude_phase6/load_volo_masterlist.py`
- Test: `app/catalog_pipeline/claude_phase6/tests/test_load_volo_masterlist.py`

**Interfaces:**
- Consumes: `sha256_file`, `verify_db_hash`, `backup_database` (from `claude_phase3.promote_comment_evidence`), `CREATE_DIVIDER_TABLE_SQL`, `CREATE_DEPLOYMENT_TABLE_SQL`, `build_candidate_index`, `insert_divider_signals`, `insert_deployment_signals`, `insert_load_order_hints_from_dependencies` (Tasks 2-5).
- Produces: `load_masterlist(path: Path) -> dict`, `run_migration(db_path: Path, expected_sha256: str, masterlist_path: Path) -> dict` (the receipt dict), and a `main()` CLI entrypoint. Task 7 invokes this via the CLI directly against the real candidate DB.

- [ ] **Step 1: Write the failing tests**

Append to `app/catalog_pipeline/claude_phase6/tests/test_load_volo_masterlist.py`:

```python
import hashlib

from app.catalog_pipeline.claude_phase6.load_volo_masterlist import run_migration


def _sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        digest.update(fh.read())
    return digest.hexdigest()


def _create_base_schema_only(conn):
    # Deliberately does NOT create catalog_volo_divider_signals /
    # catalog_volo_deployment_signals -- run_migration itself must create
    # them (CREATE TABLE IF NOT EXISTS), same as a real fresh candidate DB.
    conn.executescript(
        """
        CREATE TABLE mods (mod_uid INTEGER PRIMARY KEY, canonical_name TEXT);
        CREATE TABLE platform_listings (
            listing_id INTEGER PRIMARY KEY AUTOINCREMENT,
            mod_uid INTEGER REFERENCES mods(mod_uid),
            platform TEXT, platform_mod_id TEXT, author TEXT
        );
        CREATE TABLE load_order_hints (
            hint_id INTEGER PRIMARY KEY AUTOINCREMENT,
            mod_uid INTEGER, relation_type TEXT, relative_to_mod_uid INTEGER,
            relative_to_text TEXT, source TEXT, source_platform TEXT,
            confidence TEXT, supporting_text TEXT
        );
        CREATE TABLE migration_history (
            migration_id INTEGER PRIMARY KEY AUTOINCREMENT,
            migration_name TEXT UNIQUE NOT NULL, schema_version TEXT NOT NULL,
            applied_at TEXT NOT NULL, actor_session TEXT NOT NULL,
            source_db_sha256 TEXT NOT NULL, row_count_before TEXT NOT NULL,
            row_count_after TEXT NOT NULL, notes TEXT
        );
        """
    )


@pytest.fixture
def db_and_source(tmp_path):
    db_path = tmp_path / "candidate.db"
    conn = sqlite3.connect(str(db_path))
    _create_base_schema_only(conn)
    insert_mod(conn, 1, "ImpUI")
    insert_listing(conn, 1, "nexus", "366", "bibsan")
    conn.commit()
    conn.close()

    masterlist = {
        "version": "2.0.0",
        "generated": "2026-08-10T23:56:45.072Z",
        "plugins": [
            {
                "name": "ImpUI", "uuid": "u-1", "author": "bibsan", "group": "User Interface",
                "divider": 1, "evidence": {"source": "curated", "installs": 53},
                "usesScriptExtender": True, "featureFlags": ["Lua"],
            },
        ],
    }
    masterlist_path = tmp_path / "masterlist.json"
    masterlist_path.write_text(json.dumps(masterlist))
    return db_path, masterlist_path


def test_run_migration_creates_tables_and_inserts_rows(db_and_source):
    db_path, masterlist_path = db_and_source
    sha256 = _sha256_of(db_path)
    receipt = run_migration(db_path, sha256, masterlist_path)

    assert receipt["divider_rows_inserted"] == 1
    assert receipt["divider_matched"] == 1
    assert receipt["deployment_rows_inserted"] == 1
    assert receipt["load_order_hints_inserted"] == 0  # fixture plugin has no dependencies

    conn = sqlite3.connect(str(db_path))
    divider_row = conn.execute("SELECT mod_uid, group_name FROM catalog_volo_divider_signals").fetchone()
    deployment_row = conn.execute("SELECT mod_uid, uses_script_extender FROM catalog_volo_deployment_signals").fetchone()
    conn.close()
    assert divider_row == (1, "User Interface")
    assert deployment_row == (1, 1)


def test_run_migration_hash_mismatch_raises(db_and_source):
    db_path, masterlist_path = db_and_source
    with pytest.raises(ValueError):
        run_migration(db_path, "wrong-hash-deadbeef", masterlist_path)


def test_run_migration_second_run_raises_integrity_error(db_and_source):
    db_path, masterlist_path = db_and_source
    first_sha256 = _sha256_of(db_path)
    run_migration(db_path, first_sha256, masterlist_path)

    second_sha256 = _sha256_of(db_path)
    with pytest.raises(sqlite3.IntegrityError):
        run_migration(db_path, second_sha256, masterlist_path)


def test_run_migration_writes_migration_history_row(db_and_source):
    db_path, masterlist_path = db_and_source
    sha256 = _sha256_of(db_path)
    run_migration(db_path, sha256, masterlist_path)

    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT migration_name, schema_version FROM migration_history "
        "WHERE migration_name = 'b26-phase6-volo-masterlist'"
    ).fetchone()
    conn.close()
    assert row == ("b26-phase6-volo-masterlist", "phase6")


def test_run_migration_rolls_back_on_malformed_masterlist_json(db_and_source):
    db_path, masterlist_path = db_and_source
    masterlist_path.write_text("{not valid json")
    sha256 = _sha256_of(db_path)

    with pytest.raises(json.JSONDecodeError):
        run_migration(db_path, sha256, masterlist_path)

    conn = sqlite3.connect(str(db_path))
    history_count = conn.execute(
        "SELECT COUNT(*) FROM migration_history WHERE migration_name = 'b26-phase6-volo-masterlist'"
    ).fetchone()[0]
    conn.close()
    assert history_count == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest app/catalog_pipeline/claude_phase6/tests/test_load_volo_masterlist.py -v -k run_migration`
Expected: FAIL with `ImportError` — `run_migration` not defined yet.

- [ ] **Step 3: Implement `run_migration` and the CLI entrypoint**

Append to `app/catalog_pipeline/claude_phase6/load_volo_masterlist.py`:

```python
def load_masterlist(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def run_migration(db_path: Path, expected_sha256: str, masterlist_path: Path) -> dict:
    verify_db_hash(db_path, expected_sha256)
    backup_path = backup_database(db_path, suffix=".pre-phase6-volo-backup")
    masterlist_sha256 = sha256_file(masterlist_path)
    masterlist = load_masterlist(masterlist_path)
    plugins = masterlist["plugins"]
    source_version = masterlist["version"]
    captured_at = masterlist["generated"]

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN")
        try:
            conn.execute(CREATE_DIVIDER_TABLE_SQL)
            conn.execute(CREATE_DEPLOYMENT_TABLE_SQL)

            divider_before = conn.execute("SELECT COUNT(*) FROM catalog_volo_divider_signals").fetchone()[0]
            deployment_before = conn.execute("SELECT COUNT(*) FROM catalog_volo_deployment_signals").fetchone()[0]
            hints_before = conn.execute("SELECT COUNT(*) FROM load_order_hints").fetchone()[0]

            # Claim the migration slot first: migration_history.migration_name
            # is UNIQUE, so a rerun raises IntegrityError right here, before
            # any signal row is touched -- matches every prior phase's pattern.
            conn.execute(
                """INSERT INTO migration_history
                   (migration_name, schema_version, applied_at, actor_session,
                    source_db_sha256, row_count_before, row_count_after, notes)
                   VALUES (?, 'phase6', ?, 'claude-code-phase6', ?, ?, ?, 'pending')""",
                (
                    "b26-phase6-volo-masterlist",
                    datetime.now(timezone.utc).isoformat(),
                    expected_sha256,
                    str(divider_before + deployment_before + hints_before),
                    str(divider_before + deployment_before + hints_before),
                ),
            )

            candidates = build_candidate_index(conn)
            divider_counts = insert_divider_signals(conn, plugins, candidates, source_version, captured_at)
            deployment_counts = insert_deployment_signals(conn, plugins, candidates, source_version, captured_at)
            hints_counts = insert_load_order_hints_from_dependencies(conn, plugins, candidates)

            divider_after = divider_before + divider_counts["divider_rows_inserted"]
            deployment_after = deployment_before + deployment_counts["deployment_rows_inserted"]
            hints_after = hints_before + hints_counts["load_order_hints_inserted"]

            conn.execute(
                """UPDATE migration_history SET row_count_after = ?, notes = ?
                   WHERE migration_name = ?""",
                (
                    str(divider_after + deployment_after + hints_after),
                    f"+{divider_counts['divider_rows_inserted']} divider signals "
                    f"({divider_counts['divider_matched']} matched/"
                    f"{divider_counts['divider_needs_review']} needs_review/"
                    f"{divider_counts['divider_unmatched']} unmatched), "
                    f"+{deployment_counts['deployment_rows_inserted']} deployment signals, "
                    f"+{hints_counts['load_order_hints_inserted']} load_order_hints "
                    f"({hints_counts['load_order_hints_skipped_source_unmatched']} plugins "
                    f"skipped: source not matched)",
                    "b26-phase6-volo-masterlist",
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
        "migration_name": "b26-phase6-volo-masterlist",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "pre_migration_sha256": expected_sha256,
        "backup_path": str(backup_path),
        "masterlist_sha256": masterlist_sha256,
        "masterlist_version": source_version,
        "masterlist_generated": captured_at,
        "divider_signals_before": divider_before,
        "divider_signals_after": divider_after,
        "deployment_signals_before": deployment_before,
        "deployment_signals_after": deployment_after,
        "load_order_hints_before": hints_before,
        "load_order_hints_after": hints_after,
        **divider_counts,
        **deployment_counts,
        **hints_counts,
        "post_migration_sha256": post_sha256,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--candidate-sha256", required=True)
    parser.add_argument("--masterlist", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()

    receipt = run_migration(args.db, args.candidate_sha256, args.masterlist)
    args.receipt.write_text(json.dumps(receipt, indent=2))
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest app/catalog_pipeline/claude_phase6/tests/test_load_volo_masterlist.py -v`
Expected: PASS (28 tests total).

- [ ] **Step 5: Commit**

```bash
git add app/catalog_pipeline/claude_phase6/
git commit -m "Add run_migration + CLI for VOLO masterlist migration, with hash-gate/backup/rollback tests"
```

---

### Task 7: Execute the real migration and verify

**Files:** none (execution + a CLAUDE.md documentation update)

**Interfaces:**
- Consumes: `app/catalog_pipeline/claude_phase6/load_volo_masterlist.py`'s CLI (Task 6), the real masterlist file downloaded in Task 1.

- [ ] **Step 1: Confirm the candidate DB's current hash matches the last known-good value**

```bash
py -c "
import hashlib, json
p = 'catalog/B26/BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db'
actual = hashlib.sha256(open(p, 'rb').read()).hexdigest()
last_known_good = json.load(open('catalog/B26/phase5_nexus_tags_receipt.json'))['post_migration_sha256']
print('actual  :', actual)
print('expected:', last_known_good)
print('MATCH' if actual == last_known_good else 'MISMATCH -- STOP AND INVESTIGATE BEFORE PROCEEDING')
"
```
This derives the expected hash from Phase 5's own real receipt (the most recent completed migration) rather than a value hardcoded into this plan, since the plan may be executed some time after being written. **If it prints MISMATCH, stop and investigate — do not proceed past an unexplained hash mismatch** (standing project rule).

- [ ] **Step 2: Locate the fetched masterlist file from Task 1**

```bash
ls data/volo/*.json | grep -v manifest
```

- [ ] **Step 3: Run the migration**

```bash
py -m app.catalog_pipeline.claude_phase6.load_volo_masterlist \
  --db catalog/B26/BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db \
  --candidate-sha256 <hash from Step 1> \
  --masterlist <path from Step 2> \
  --receipt catalog/B26/phase6_volo_masterlist_receipt.json
```
Expected: prints the receipt JSON, no exceptions. This may take a while (the fuzzy-match scan compares each VOLO plugin against the full `mods`/`platform_listings` candidate index) — let it run to completion rather than interrupting.

- [ ] **Step 4: Independently verify — do not trust only the script's own receipt**

```bash
py -c "
import sqlite3
con = sqlite3.connect('catalog/B26/BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db')
cur = con.cursor()

print('catalog_volo_divider_signals:', cur.execute('SELECT COUNT(*) FROM catalog_volo_divider_signals').fetchone()[0])
print('  by match_status:')
for row in cur.execute('SELECT match_status, COUNT(*) FROM catalog_volo_divider_signals GROUP BY match_status'):
    print('   ', row)

print('catalog_volo_deployment_signals:', cur.execute('SELECT COUNT(*) FROM catalog_volo_deployment_signals').fetchone()[0])
print('  by match_status:')
for row in cur.execute('SELECT match_status, COUNT(*) FROM catalog_volo_deployment_signals GROUP BY match_status'):
    print('   ', row)

print('load_order_hints (source=volo):', cur.execute(\"SELECT COUNT(*) FROM load_order_hints WHERE source='volo'\").fetchone()[0])

print('integrity_check:', cur.execute('PRAGMA integrity_check').fetchone())
print('fk violations:', cur.execute('PRAGMA foreign_key_check').fetchall())

print()
print('spot-check 3 matched divider rows:')
for row in cur.execute('''
    SELECT volo_name, group_name, evidence_source, match_status
    FROM catalog_volo_divider_signals WHERE match_status='matched' LIMIT 3
'''):
    print(' ', row)

print('spot-check 3 volo load_order_hints rows:')
for row in cur.execute('''
    SELECT mod_uid, relative_to_mod_uid, relative_to_text, confidence
    FROM load_order_hints WHERE source='volo' LIMIT 3
'''):
    print(' ', row)
"
```
Expected: table row counts match the receipt's `divider_rows_inserted`/`deployment_rows_inserted`/`load_order_hints_inserted` exactly; `integrity_check` returns `ok`; `fk violations` is empty; `match_status` breakdown shows a mix of matched/needs_review/unmatched (given only ~12% of VOLO plugins carry an author field, expect `needs_review` to be a large share — this is the correct, honest result per the design, not a bug); spot-checked rows contain real mod names and group/evidence data, not garbage.

- [ ] **Step 5: Update CLAUDE.md**

Add a dated entry documenting: the real plugin/row counts from Step 4 (which will differ from the 7,671/6,926/367/299/163 seen during design, since VOLO is actively growing — record the actual numbers, not the design-time ones), the match-status breakdown, the receipt path, and the final DB hash — matching this project's established documentation convention (see the B26 Phase 3/4/5 sections as the template).

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md
git commit -m "Record VOLO masterlist ingestion migration results in CLAUDE.md"
```

Note: `catalog/B26/phase6_volo_masterlist_receipt.json` and the backup DB file stay gitignored (same as every prior phase's receipts), so only CLAUDE.md is committed here.
