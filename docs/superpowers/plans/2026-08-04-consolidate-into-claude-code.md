# Consolidate BG3 Project into Claude Code — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Materialize the B26 reference-catalog database and Codex's build pipeline locally (out of Drive-only storage), review that pipeline, and reach an explicit adopt-vs-redesign decision with Jason — while cleaning up local structure and Drive's role to match a single-Codespace working model.

**Architecture:** Pull large artifacts down from Google Drive via the `mcp__claude_ai_Google_Drive__*` tools (this repo has no Drive service-account credentials — all Drive access happens through Claude Code's own connected-account tools), reassemble split archives with plain shell (`cat`, `unzip`/`tar`), and verify every artifact with SHA-256 + SQLite integrity checks before treating it as real. No new runtime dependencies — everything here is Python stdlib (`hashlib`, `sqlite3`) plus coreutils.

**Tech Stack:** Python 3.12 stdlib (`hashlib`, `sqlite3`, `unittest`), `sqlite3` CLI, `unzip`/`tar`, Google Drive MCP tools.

## Global Constraints

- Every artifact pulled from Drive must be SHA-256-verified against a known-good hash before being treated as authoritative (spec: "Validation approach").
- Every SQLite database must pass `PRAGMA integrity_check` (expect `ok`) and `PRAGMA foreign_key_check` (expect zero rows) before being treated as authoritative (spec: "Phase 1 — Materialize").
- Large binaries (databases, zip/tar archives) are never committed to git — `catalog/` is already gitignored; new tracked pipeline scripts must live somewhere `.gitignore`'s `catalog/` rule does not match (see Task 3 for the resulting path correction).
- `Downloads/` and `archive/` are not recreated locally (spec: "Local repo/structure changes").
- Drive is backup/second-opinion only going forward, not a required sync target after every change (spec: "Architecture").
- Phase 3 (the adopt-vs-redesign decision) requires an explicit response from Jason — it must never be resolved autonomously (spec: "Phase 3 — Decision gate").

---

### Task 1: Reusable SHA-256 verification script

**Files:**
- Create: `app/catalog_pipeline/verify_checksum.py`
- Test: `app/catalog_pipeline/tests/test_verify_checksum.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: CLI `python3 app/catalog_pipeline/verify_checksum.py <path> <expected_sha256>` — exits `0` and prints `OK <path>` on match, exits `1` and prints `MISMATCH <path>: expected <expected>, got <actual>` on mismatch. Also exposes `verify_checksum(path: str, expected_sha256: str) -> bool` importable from the module for reuse in later tasks' shell one-liners (`python3 -c "from app.catalog_pipeline.verify_checksum import verify_checksum; ..."`).

Every later materialization task (2, 4, 5) calls this script instead of hand-rolling `sha256sum | grep` — one place to get the comparison right.

- [ ] **Step 1: Write the failing test**

```python
# app/catalog_pipeline/tests/test_verify_checksum.py
import hashlib
import tempfile
import unittest
from pathlib import Path

from app.catalog_pipeline.verify_checksum import verify_checksum


class TestVerifyChecksum(unittest.TestCase):
    def test_matching_hash_returns_true(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"hello world")
            path = Path(f.name)
        try:
            expected = hashlib.sha256(b"hello world").hexdigest()
            self.assertTrue(verify_checksum(str(path), expected))
        finally:
            path.unlink()

    def test_mismatched_hash_returns_false(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"hello world")
            path = Path(f.name)
        try:
            self.assertFalse(verify_checksum(str(path), "0" * 64))
        finally:
            path.unlink()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /workspaces/bg3_scraper && python3 -m unittest app.catalog_pipeline.tests.test_verify_checksum -v`
Expected: `ModuleNotFoundError: No module named 'app.catalog_pipeline'` (or `verify_checksum` not found) — fails because the module doesn't exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
# app/catalog_pipeline/__init__.py
```
(empty file, makes `app.catalog_pipeline` importable)

```python
# app/catalog_pipeline/tests/__init__.py
```
(empty file, same reason)

```python
# app/catalog_pipeline/verify_checksum.py
"""Verify a file's SHA-256 against an expected value.

Used by every materialization task in the 2026-08-04 consolidation plan
to confirm an artifact pulled from Drive matches its recorded hash before
it's treated as authoritative.
"""
import hashlib
import sys


def verify_checksum(path: str, expected_sha256: str) -> bool:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest() == expected_sha256.lower()


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: verify_checksum.py <path> <expected_sha256>", file=sys.stderr)
        return 2
    path, expected = sys.argv[1], sys.argv[2]
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual == expected.lower():
        print(f"OK {path}")
        return 0
    print(f"MISMATCH {path}: expected {expected}, got {actual}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /workspaces/bg3_scraper && python3 -m unittest app.catalog_pipeline.tests.test_verify_checksum -v`
Expected: both tests `ok`, `OK` summary line, exit code 0.

- [ ] **Step 5: Manual CLI smoke check**

Run: `echo -n "hello world" > /tmp/smoke.txt && python3 app/catalog_pipeline/verify_checksum.py /tmp/smoke.txt b94d27b9934d3e08a52e52d7da7dacefb63b1a5c9e69ba3d3f6d1d3ee7b6f3d1; echo "exit: $?"`
Expected: `MISMATCH ...` and `exit: 1` (that hash is arbitrary/wrong on purpose — confirms failure path works from the CLI, not just the test).
Then run: `python3 -c "import hashlib; print(hashlib.sha256(b'hello world').hexdigest())"` to get the real hash, and re-run `verify_checksum.py` with it.
Expected: `OK /tmp/smoke.txt` and `exit: 0`.

- [ ] **Step 6: Commit**

```bash
git add app/catalog_pipeline/__init__.py app/catalog_pipeline/verify_checksum.py app/catalog_pipeline/tests/__init__.py app/catalog_pipeline/tests/test_verify_checksum.py
git commit -m "Add reusable SHA-256 verification script for catalog materialization"
```

---

### Task 2: Materialize the B26 database

**Files:**
- Create (gitignored, not committed): `catalog/B26/BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db`
- Create (gitignored scratch, deleted at end of task): `catalog/B26/.materialize_tmp/*`

**Interfaces:**
- Consumes: `app/catalog_pipeline/verify_checksum.py` from Task 1.
- Produces: a verified, local `catalog/B26/BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db` (SHA-256 `cb37e0392b7bdb0b06f8095c44b8352363610999498ff4803e07411df3187775`) that Task 6 (review) reads directly.

The single 876MB file is too large to pull through the Drive MCP tool's base64 response in one call. Instead, reassemble it from the 10 already-uploaded ~20MB zip parts in Drive folder `BG3/CATALOG/B26_DATABASE_BASELINE/` (folder ID `1Chf6bFhRjbMxAW6I0USg8NINMk_hiKDM`) — this is the exact same content, just chunked for transfer, and is the same recovery procedure documented in that folder's own `C4_Semantic_B26_Phase1_Coverage_Full_Snapshot_MANIFEST.md`.

- [ ] **Step 1: Create scratch directory**

Run: `mkdir -p /workspaces/bg3_scraper/catalog/B26/.materialize_tmp`

- [ ] **Step 2: Download all 10 zip parts from Drive**

For each of the following (`fileId`, `filename`) pairs, call the `mcp__claude_ai_Google_Drive__download_file_content` tool with that `fileId`, decode the returned base64 content, and write it to `catalog/B26/.materialize_tmp/<filename>`:

| Part | fileId |
|---|---|
| `C4_Semantic_B26_Phase1_Coverage_Full_Snapshot.zip.part-000` | `1xym9OD3x8mZ6ImPygIYF2gEEhldOzdFi` |
| `C4_Semantic_B26_Phase1_Coverage_Full_Snapshot.zip.part-001` | `1YZlmDVwP9cUSNSM1lUeiZLyAKJU8IagT` |
| `C4_Semantic_B26_Phase1_Coverage_Full_Snapshot.zip.part-002` | `1YcejvVt87IoYmZ44JA96gwSrZr-cddwR` |
| `C4_Semantic_B26_Phase1_Coverage_Full_Snapshot.zip.part-003` | `1hLR-FbfYxOugsAGH-jC_BCaySuQocyud` |
| `C4_Semantic_B26_Phase1_Coverage_Full_Snapshot.zip.part-004` | `1PuHgQsn5_pfCMGOu5B01cUotO80E5Tzt` |
| `C4_Semantic_B26_Phase1_Coverage_Full_Snapshot.zip.part-005` | `1TnpuBNXt-uQEE87GMaBTOCDjrLu3FiDj` |
| `C4_Semantic_B26_Phase1_Coverage_Full_Snapshot.zip.part-006` | `1snMpVmA0upLPsES-VrjHdOplIr25q2aD` |
| `C4_Semantic_B26_Phase1_Coverage_Full_Snapshot.zip.part-007` | `1NyKI_543ugUGwXLy75rAM843K4pEapRX` |
| `C4_Semantic_B26_Phase1_Coverage_Full_Snapshot.zip.part-008` | `1eEEfYaKORSrZLPCtBunekdaETIcbz9vx` |
| `C4_Semantic_B26_Phase1_Coverage_Full_Snapshot.zip.part-009` | `1awoDRf1pEhsYO7PTEHpvHaaJaaXMqHtG` |

**Fallback:** if any single download fails or times out (base64 payload too large for one tool response), ask Jason to download that specific part from `https://drive.google.com/file/d/<fileId>/view` manually and place it at the path above, then continue.

Verify all 10 parts landed:
Run: `ls -la /workspaces/bg3_scraper/catalog/B26/.materialize_tmp/`
Expected: 10 files named `C4_Semantic_B26_Phase1_Coverage_Full_Snapshot.zip.part-000` through `part-009`, with `part-000` through `part-008` each `20971520` bytes and `part-009` at `11978630` bytes.

- [ ] **Step 3: Concatenate parts and verify the reassembled zip**

Run:
```bash
cd /workspaces/bg3_scraper/catalog/B26/.materialize_tmp
cat C4_Semantic_B26_Phase1_Coverage_Full_Snapshot.zip.part-0* > C4_Semantic_B26_Phase1_Coverage_Full_Snapshot.zip
python3 /workspaces/bg3_scraper/app/catalog_pipeline/verify_checksum.py C4_Semantic_B26_Phase1_Coverage_Full_Snapshot.zip 50772e0059e78bc3f9f21e7ccdf80156b1c92ce436baa27b95554ff156ae7ef0
```
Expected: `OK C4_Semantic_B26_Phase1_Coverage_Full_Snapshot.zip`, exit code 0. If it mismatches, do not proceed — re-download the parts (a part likely got truncated) rather than trusting a partially-correct reassembly.

- [ ] **Step 4: Extract and place the database**

Run:
```bash
cd /workspaces/bg3_scraper/catalog/B26/.materialize_tmp
unzip -o C4_Semantic_B26_Phase1_Coverage_Full_Snapshot.zip -d extracted
mv extracted/BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db /workspaces/bg3_scraper/catalog/B26/
python3 /workspaces/bg3_scraper/app/catalog_pipeline/verify_checksum.py /workspaces/bg3_scraper/catalog/B26/BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db cb37e0392b7bdb0b06f8095c44b8352363610999498ff4803e07411df3187775
```
Expected: `OK /workspaces/bg3_scraper/catalog/B26/BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db`, exit code 0.

- [ ] **Step 5: Run SQLite integrity checks**

Run:
```bash
sqlite3 /workspaces/bg3_scraper/catalog/B26/BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db "PRAGMA integrity_check;"
sqlite3 /workspaces/bg3_scraper/catalog/B26/BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db "PRAGMA foreign_key_check;"
```
Expected: first command prints `ok`; second command prints nothing (zero rows = zero violations).

- [ ] **Step 6: Clean up scratch space**

Run: `rm -rf /workspaces/bg3_scraper/catalog/B26/.materialize_tmp`

- [ ] **Step 7: Commit**

No git commit needed — `catalog/` is gitignored and nothing tracked changed in this task. Confirm this explicitly:
Run: `git status --short`
Expected: no output (or only unrelated pre-existing changes) — `catalog/B26/*.db` must not appear, confirming `.gitignore` is doing its job.

---

### Task 3: Materialize Codex's pipeline scripts

**Files:**
- Create: `app/catalog_pipeline/codex_phase1/register_phase1_coverage.py`
- Create: `app/catalog_pipeline/codex_phase1/taxonomy_rules_phase0_reconciled_2026-07-27.py`
- Create: `app/catalog_pipeline/codex_phase2/build_phase2_comment_evidence_index.py`
- Create: `app/catalog_pipeline/codex_phase2/finalize_phase2_comment_evidence_index.py`
- Create: `app/catalog_pipeline/codex_phase2/report_phase2_comment_evidence_index.py`
- Create: `app/catalog_pipeline/codex_phase1/PROVENANCE.md`
- Create: `app/catalog_pipeline/codex_phase2/PROVENANCE.md`

**Interfaces:**
- Consumes: `app/catalog_pipeline/verify_checksum.py` from Task 1.
- Produces: the five scripts, readable by Task 6's review. `PROVENANCE.md` in each subfolder records where each script came from (Drive file ID, original folder) and its SHA-256, so a future reader isn't left wondering whether these are the real Codex scripts or something rewritten.

This is a straight materialization task — these files are small (under 25KB each), so no reassembly is needed, just direct download.

- [ ] **Step 1: Create destination directories**

Run: `mkdir -p /workspaces/bg3_scraper/app/catalog_pipeline/codex_phase1 /workspaces/bg3_scraper/app/catalog_pipeline/codex_phase2`

- [ ] **Step 2: Download the five scripts**

For each (`fileId`, destination path) pair, call `mcp__claude_ai_Google_Drive__download_file_content` and write the (non-base64, since these are text files — use `read_file_content` if `download_file_content` returns garbled text; either tool's raw content is acceptable here) content to disk:

| fileId | Destination |
|---|---|
| `16JtasD22HawXBP17FbItWYcD88c0qxCe` | `app/catalog_pipeline/codex_phase1/register_phase1_coverage.py` |
| `1MPIINtM9HzitKoFOsQoKNZCB48g0N-rd` | `app/catalog_pipeline/codex_phase1/taxonomy_rules_phase0_reconciled_2026-07-27.py` |
| `1XpYpINg3BK6Q3RXzVpKjteBsI_ohtmrq` | `app/catalog_pipeline/codex_phase2/build_phase2_comment_evidence_index.py` |
| `1LpH6uB8K2FTcxGtzq921lMeG9Fnai2s-` | `app/catalog_pipeline/codex_phase2/finalize_phase2_comment_evidence_index.py` |
| `1NOo4GeDETMyOydgMv_kWoyC7PjyO24C1` | `app/catalog_pipeline/codex_phase2/report_phase2_comment_evidence_index.py` |

- [ ] **Step 3: Verify the one script with a published hash**

`taxonomy_rules_phase0_reconciled_2026-07-27.py`'s SHA-256 is recorded in Codex's own migration receipt (`taxonomy_rule_sha256` in `PHASE1_B26_COVERAGE_MIGRATION_RECEIPT.json`):

Run: `python3 app/catalog_pipeline/verify_checksum.py app/catalog_pipeline/codex_phase1/taxonomy_rules_phase0_reconciled_2026-07-27.py 9ed382412cb1ead7f50dd1588f08b95a51ea772f42a6bc4de9b02fe8873d602d`
Expected: `OK app/catalog_pipeline/codex_phase1/taxonomy_rules_phase0_reconciled_2026-07-27.py`, exit code 0.

- [ ] **Step 4: Record hashes for the other four scripts (no published value to compare against, so record for provenance instead of pass/fail)**

Run:
```bash
sha256sum app/catalog_pipeline/codex_phase1/register_phase1_coverage.py \
  app/catalog_pipeline/codex_phase2/build_phase2_comment_evidence_index.py \
  app/catalog_pipeline/codex_phase2/finalize_phase2_comment_evidence_index.py \
  app/catalog_pipeline/codex_phase2/report_phase2_comment_evidence_index.py
```
Expected: four hash lines print with no errors. Copy this output into the two `PROVENANCE.md` files in Step 5.

- [ ] **Step 5: Write PROVENANCE.md files**

```markdown
<!-- app/catalog_pipeline/codex_phase1/PROVENANCE.md -->
# Provenance — Phase 1 coverage migration scripts

Materialized 2026-08-04 from Google Drive
`BG3/CATALOG/B26_DATABASE_BASELINE/` (folder ID `1Chf6bFhRjbMxAW6I0USg8NINMk_hiKDM`),
authored by Codex/ChatGPT on 2026-07-27.

| File | Drive file ID | SHA-256 |
|---|---|---|
| `register_phase1_coverage.py` | `16JtasD22HawXBP17FbItWYcD88c0qxCe` | (paste from Task 3 Step 4 output) |
| `taxonomy_rules_phase0_reconciled_2026-07-27.py` | `1MPIINtM9HzitKoFOsQoKNZCB48g0N-rd` | `9ed382412cb1ead7f50dd1588f08b95a51ea772f42a6bc4de9b02fe8873d602d` (verified against Codex's own migration receipt) |

These scripts are reference material for Task 6's pipeline review. They
have not been run from this repo and should not be run against
`catalog/B26/`'s live database without the Phase 3 decision (adopt vs.
redesign) being made first.
```

```markdown
<!-- app/catalog_pipeline/codex_phase2/PROVENANCE.md -->
# Provenance — Phase 2 Comment Evidence Index build scripts

Materialized 2026-08-04 from Google Drive
`00_AUTHORITATIVE_CHECKPOINTS/.../PHASE2A_Comment_Evidence_Index_Unlinked_Full_Snapshot/`
(folder ID `1yKC2PY-C5wYBQfwiWpUkXGIa6ZljwMKP`), authored by Codex/ChatGPT on
2026-07-28.

| File | Drive file ID | SHA-256 |
|---|---|---|
| `build_phase2_comment_evidence_index.py` | `1XpYpINg3BK6Q3RXzVpKjteBsI_ohtmrq` | (paste from Task 3 Step 4 output) |
| `finalize_phase2_comment_evidence_index.py` | `1LpH6uB8K2FTcxGtzq921lMeG9Fnai2s-` | (paste from Task 3 Step 4 output) |
| `report_phase2_comment_evidence_index.py` | `1NOo4GeDETMyOydgMv_kWoyC7PjyO24C1` | (paste from Task 3 Step 4 output) |

These scripts are reference material for Task 6's pipeline review. They
built `BG3_Comment_Evidence_Index_Phase2A_candidate.db` /
`..._Phase2B_B26ExactLinks_candidate.db` (materialized in Tasks 4–5) and
have not been run from this repo.
```

- [ ] **Step 6: Commit**

```bash
git add app/catalog_pipeline/codex_phase1/ app/catalog_pipeline/codex_phase2/
git commit -m "Materialize Codex's B26 pipeline scripts for local review"
```

---

### Task 4: Materialize the Phase 2A Comment Evidence Index database

**Files:**
- Create (gitignored, not committed): `catalog/B26/BG3_Comment_Evidence_Index_Phase2A_candidate.db`
- Create (gitignored scratch, deleted at end of task): `catalog/B26/.materialize_tmp/*`

**Interfaces:**
- Consumes: `app/catalog_pipeline/verify_checksum.py` from Task 1.
- Produces: a verified, local `catalog/B26/BG3_Comment_Evidence_Index_Phase2A_candidate.db` (SHA-256 `c7a6367489592c534ae0eefc65937194f36f2fad1d52e883e775f75e9ecd493c`, 527,928 comment rows) that Task 6 reads directly.

The full part list for this folder wasn't fully enumerated during design (Drive's search paginated past it) — this task re-lists the folder from scratch rather than trusting a possibly-incomplete ID list.

- [ ] **Step 1: List every part file in the Phase 2A folder**

Call `mcp__claude_ai_Google_Drive__search_files` with query `parentId = '1yKC2PY-C5wYBQfwiWpUkXGIa6ZljwMKP'` and `pageSize: 50`. If the result includes a `nextPageToken`, call again with that `pageToken` and merge results, repeating until no `nextPageToken` is returned.

From the merged results, collect every file whose title matches
`PHASE2A_Comment_Evidence_Index_Unlinked_Full_Snapshot.tar.gz.part-*`, and sort them by the numeric suffix.

Run: `mkdir -p /workspaces/bg3_scraper/catalog/B26/.materialize_tmp`

- [ ] **Step 2: Download every part**

For each part found in Step 1, call `mcp__claude_ai_Google_Drive__download_file_content` with its `fileId`, decode the base64 content, and write it to `catalog/B26/.materialize_tmp/<filename>`.

**Fallback:** same as Task 2 Step 2 — if a download fails due to size, ask Jason to fetch that file manually from its Drive URL.

Verify all parts landed in order:
Run: `ls /workspaces/bg3_scraper/catalog/B26/.materialize_tmp/ | sort`
Expected: a contiguous sequence `PHASE2A_Comment_Evidence_Index_Unlinked_Full_Snapshot.tar.gz.part-000` through the highest part number found in Step 1, with no gaps.

- [ ] **Step 3: Concatenate and extract**

Run:
```bash
cd /workspaces/bg3_scraper/catalog/B26/.materialize_tmp
cat PHASE2A_Comment_Evidence_Index_Unlinked_Full_Snapshot.tar.gz.part-* > PHASE2A_Comment_Evidence_Index_Unlinked_Full_Snapshot.tar.gz
mkdir -p extracted
tar -xzf PHASE2A_Comment_Evidence_Index_Unlinked_Full_Snapshot.tar.gz -C extracted
find extracted -name "BG3_Comment_Evidence_Index_Phase2A_candidate.db"
```
Expected: the `find` command prints exactly one path ending in `BG3_Comment_Evidence_Index_Phase2A_candidate.db`.

- [ ] **Step 4: Place and verify the database**

Run (substituting the path `find` printed in Step 3):
```bash
mv /workspaces/bg3_scraper/catalog/B26/.materialize_tmp/extracted/<path-from-step-3>/BG3_Comment_Evidence_Index_Phase2A_candidate.db /workspaces/bg3_scraper/catalog/B26/
python3 /workspaces/bg3_scraper/app/catalog_pipeline/verify_checksum.py /workspaces/bg3_scraper/catalog/B26/BG3_Comment_Evidence_Index_Phase2A_candidate.db c7a6367489592c534ae0eefc65937194f36f2fad1d52e883e775f75e9ecd493c
```
Expected: `OK ...`, exit code 0. If it mismatches, re-download rather than proceeding — the manifest for this archive explicitly documents this as the expected hash.

- [ ] **Step 5: Run SQLite integrity checks and spot-check row counts**

Run:
```bash
sqlite3 /workspaces/bg3_scraper/catalog/B26/BG3_Comment_Evidence_Index_Phase2A_candidate.db "PRAGMA integrity_check;"
sqlite3 /workspaces/bg3_scraper/catalog/B26/BG3_Comment_Evidence_Index_Phase2A_candidate.db "PRAGMA foreign_key_check;"
sqlite3 /workspaces/bg3_scraper/catalog/B26/BG3_Comment_Evidence_Index_Phase2A_candidate.db "SELECT COUNT(*) FROM comments;"
```
Expected: `ok`; no rows; `527928`.

- [ ] **Step 6: Clean up scratch space**

Run: `rm -rf /workspaces/bg3_scraper/catalog/B26/.materialize_tmp`

- [ ] **Step 7: Commit**

No commit needed (same reasoning as Task 2 Step 7 — `catalog/` is gitignored).
Run: `git status --short`
Expected: no `catalog/B26/*.db` entries appear.

---

### Task 5: Materialize the Phase 2B Comment Evidence Index database

**Files:**
- Create (gitignored, not committed): `catalog/B26/BG3_Comment_Evidence_Index_Phase2B_B26ExactLinks_candidate.db`
- Create (gitignored scratch, deleted at end of task): `catalog/B26/.materialize_tmp/*`

**Interfaces:**
- Consumes: `app/catalog_pipeline/verify_checksum.py` from Task 1.
- Produces: a verified, local `catalog/B26/BG3_Comment_Evidence_Index_Phase2B_B26ExactLinks_candidate.db` (SHA-256 `a7d20f9586a7413f8d1a82ed2965de4cdcb19f942d59400be5896b3e3e72bfaa`) that Task 6 reads directly. This is the same comment data as Phase 2A, additionally linked to B26 `listing_uuid`s — Task 6 should compare the two rather than treat this as a fully separate dataset.

Same procedure as Task 4, applied to the Phase 2B folder. All 12 part IDs were fully enumerated during design (unlike Phase 2A, this folder's listing didn't hit a pagination cutoff), so they're given directly — but re-list the folder anyway as a correctness check in case anything changed since design time.

- [ ] **Step 1: Confirm the part list for the Phase 2B folder**

Call `mcp__claude_ai_Google_Drive__search_files` with query `parentId = '1ZtMa2UaAeeR-vkvkisLq5361b95Z3KeG'` and `pageSize: 50`. Confirm the result contains exactly these 12 parts (no `nextPageToken` expected):

| Part | fileId | Bytes |
|---|---|---|
| part-000 | `1Sqhnx961xGX5pkqe5b7V0oS2zwJyyNXU` | 20971520 |
| part-001 | `1s97xd18WsZegDPIgRaQDKv9kVx9k3JZK` | 20971520 |
| part-002 | `1pjtuy3UW2EqmS_DPGzggOyxep6kgv0uv` | 20971520 |
| part-003 | `1s0_U7NpfY2GvcErnl09XE-3f2MDK7q7J` | 20971520 |
| part-004 | `1tp67Jygvosv72Ghasz1lgwI2Xxk41o2Q` | 20971520 |
| part-005 | `16NJsOQTs04KfeyCZikHD2pmHmsNVUeiw` | 20971520 |
| part-006 | `1-MjeuKKaxkwsWE_AVyoI1lwlSH8i-wrp` | 20971520 |
| part-007 | `1ujoHCm7yPoRMkwycdJbL4OhZPVav3W91` | 20971520 |
| part-008 | `1SXOmwFYRHWpP2IZ8p04hnFOQGOfb8U9Z` | 20971520 |
| part-009 | `18yvm9NXz4__m1WV4GDq2ClvkRcuCR1wg` | 20971520 |
| part-010 | `1HEgplsrjpBcpVqF2825Ftijwl8h__swp` | 20971520 |
| part-011 | `1prFPAGf2jp_8cSqeRG9VrIxqouTaHU3R` | 1526486 |

If the live listing disagrees with this table (extra/missing/renamed parts), trust the live listing and adjust the download list accordingly — this table is a design-time snapshot, not the source of truth.

Run: `mkdir -p /workspaces/bg3_scraper/catalog/B26/.materialize_tmp`

- [ ] **Step 2: Download all 12 parts**

For each part, call `mcp__claude_ai_Google_Drive__download_file_content` with its `fileId`, decode the base64 content, and write it to `catalog/B26/.materialize_tmp/PHASE2B_Comment_Evidence_Index_B26ExactLinks_Full_Snapshot.tar.gz.part-0XX`.

**Fallback:** same as Task 2 Step 2.

Verify: `ls /workspaces/bg3_scraper/catalog/B26/.materialize_tmp/ | sort`
Expected: `part-000` through `part-011`, 12 files total.

- [ ] **Step 3: Concatenate and extract**

Run:
```bash
cd /workspaces/bg3_scraper/catalog/B26/.materialize_tmp
cat PHASE2B_Comment_Evidence_Index_B26ExactLinks_Full_Snapshot.tar.gz.part-* > PHASE2B_Comment_Evidence_Index_B26ExactLinks_Full_Snapshot.tar.gz
mkdir -p extracted
tar -xzf PHASE2B_Comment_Evidence_Index_B26ExactLinks_Full_Snapshot.tar.gz -C extracted
find extracted -name "BG3_Comment_Evidence_Index_Phase2B_B26ExactLinks_candidate.db"
```
Expected: exactly one matching path printed.

- [ ] **Step 4: Place and verify the database**

Run (substituting the path from Step 3):
```bash
mv /workspaces/bg3_scraper/catalog/B26/.materialize_tmp/extracted/<path-from-step-3>/BG3_Comment_Evidence_Index_Phase2B_B26ExactLinks_candidate.db /workspaces/bg3_scraper/catalog/B26/
python3 /workspaces/bg3_scraper/app/catalog_pipeline/verify_checksum.py /workspaces/bg3_scraper/catalog/B26/BG3_Comment_Evidence_Index_Phase2B_B26ExactLinks_candidate.db a7d20f9586a7413f8d1a82ed2965de4cdcb19f942d59400be5896b3e3e72bfaa
```
Expected: `OK ...`, exit code 0.

- [ ] **Step 5: Run SQLite integrity checks**

Run:
```bash
sqlite3 /workspaces/bg3_scraper/catalog/B26/BG3_Comment_Evidence_Index_Phase2B_B26ExactLinks_candidate.db "PRAGMA integrity_check;"
sqlite3 /workspaces/bg3_scraper/catalog/B26/BG3_Comment_Evidence_Index_Phase2B_B26ExactLinks_candidate.db "PRAGMA foreign_key_check;"
```
Expected: `ok`; no rows.

- [ ] **Step 6: Clean up scratch space**

Run: `rm -rf /workspaces/bg3_scraper/catalog/B26/.materialize_tmp`

- [ ] **Step 7: Commit**

No commit needed (same reasoning as Task 2 Step 7).
Run: `git status --short`
Expected: no `catalog/B26/*.db` entries appear.

---

### Task 6: Review Codex's schema and pipeline; write findings

**Files:**
- Create: `docs/superpowers/specs/2026-08-04-b26-pipeline-review-findings.md`

**Interfaces:**
- Consumes: `catalog/B26/BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db` (Task 2), the five scripts under `app/catalog_pipeline/codex_phase{1,2}/` (Task 3), `catalog/B26/BG3_Comment_Evidence_Index_Phase2A_candidate.db` and `..._Phase2B_B26ExactLinks_candidate.db` (Tasks 4–5).
- Produces: a findings document that Task 7's decision-gate conversation is based on.

This task is analysis, not code — there's no pass/fail test, but the deliverable has a required checklist so it can't be a vague summary.

- [ ] **Step 1: Inspect the B26 schema**

Run: `sqlite3 /workspaces/bg3_scraper/catalog/B26/BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db ".schema"`

Read the full output. Note table structure, foreign keys, check constraints, and any tables referenced by the migration receipts (`evidence_corpora`, `evidence_source_records`, `mod_comments`, `platform_listings`, `catalog_browse_labels`, `catalog_collections`, `catalog_collection_memberships`, `migration_history`) that weren't previously visible except through receipt JSON.

- [ ] **Step 2: Inspect the Phase 2A/2B evidence-index schema**

Run:
```bash
sqlite3 /workspaces/bg3_scraper/catalog/B26/BG3_Comment_Evidence_Index_Phase2A_candidate.db ".schema"
sqlite3 /workspaces/bg3_scraper/catalog/B26/BG3_Comment_Evidence_Index_Phase2B_B26ExactLinks_candidate.db ".schema"
```
Diff the two schemas mentally (or with `diff <(sqlite3 ...Phase2A... ".schema") <(sqlite3 ...Phase2B... ".schema")`) — the manifest says Phase 2B only adds a `b26_listing_uuid` link on top of Phase 2A's data, so the schema diff should be small and explainable.

- [ ] **Step 3: Read the migration/build scripts**

Read `app/catalog_pipeline/codex_phase1/register_phase1_coverage.py`,
`app/catalog_pipeline/codex_phase1/taxonomy_rules_phase0_reconciled_2026-07-27.py`,
`app/catalog_pipeline/codex_phase2/build_phase2_comment_evidence_index.py`,
`app/catalog_pipeline/codex_phase2/finalize_phase2_comment_evidence_index.py`,
`app/catalog_pipeline/codex_phase2/report_phase2_comment_evidence_index.py`
in full.

- [ ] **Step 4: Write the findings document**

Write `docs/superpowers/specs/2026-08-04-b26-pipeline-review-findings.md`, covering — with specifics, not vague impressions — each of:

1. **Schema soundness**: are foreign keys and check constraints used correctly? Any normalization or design issues that would make continuing to build on this schema harder later?
2. **Migration approach**: `register_phase1_coverage.py` gates on an exact input-hash match and refuses to double-apply (via `migration_history`) — is this pattern (hash-gated, idempotent, receipt-producing) worth keeping for future migrations regardless of the adopt/redesign call?
3. **Taxonomy rule quality**: is the 14-group browse-label taxonomy in `taxonomy_rules_phase0_reconciled_2026-07-27.py` reasonable, or does it have gaps/overlaps worth flagging?
4. **Comment evidence-index approach**: `build_phase2_comment_evidence_index.py` uses regex-based triage rules (dependency/incompatibility/load-order/etc. detection) — assess whether this triage approach is sound and worth extending, or whether it's a design dead-end.
5. **The three still-open gaps from the 2026-07-30 audit**: state plainly, using what you now know from the actual schema, exactly what it would take to (a) ingest the correct comment corpora into B26 itself, (b) promote/reconcile the Phase 2A/2B evidence index into the active baseline, (c) resolve the `platform_listings` count discrepancy (11,809 Nexus + 8,158 mod.io vs. the documented 16,191/3,662 sweep sizes) — is question (c) answerable directly from the schema/data now available, or does it still require asking Codex?
6. **Explicit recommendation**: adopt Codex's pipeline as-is (continue it) vs. redesign, with the concrete reasons driving that call.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-08-04-b26-pipeline-review-findings.md
git commit -m "Add B26 pipeline review findings for the adopt-vs-redesign decision"
```

---

### Task 7: Decision gate — present findings to Jason

**Files:** none created or modified.

**Interfaces:**
- Consumes: `docs/superpowers/specs/2026-08-04-b26-pipeline-review-findings.md` (Task 6).
- Produces: Jason's explicit decision (adopt vs. redesign), which the deferred follow-up spec (see the design doc's "Explicitly deferred" section) will be built around. This plan's own scope ends here — no further catalog-content work happens without that decision.

- [ ] **Step 1: Present the findings and recommendation from Task 6 directly to Jason in conversation.**

- [ ] **Step 2: Record the decision.**

Once Jason responds, capture it as a short addendum at the bottom of `docs/superpowers/specs/2026-08-04-b26-pipeline-review-findings.md` (date, decision, one-line reasoning if given), then commit:
```bash
git add docs/superpowers/specs/2026-08-04-b26-pipeline-review-findings.md
git commit -m "Record Phase 3 decision: adopt vs. redesign the B26 pipeline"
```

**Do not proceed to any B26 content-migration work (comment ingestion, evidence-index promotion) under this plan** — that is out of scope here per the design doc and becomes its own follow-up spec.

---

### Task 8: Local housekeeping — remove Windows-only artifacts

**Files:**
- Delete: `New-Bg3ParityReconciliation.ps1`
- Delete (if present): `catalog_workspace/`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing later depends on this.

- [ ] **Step 1: Confirm what's actually present**

Run: `ls -la /workspaces/bg3_scraper/New-Bg3ParityReconciliation.ps1 /workspaces/bg3_scraper/catalog_workspace 2>&1`
Expected: the `.ps1` file listed; `catalog_workspace` may or may not exist in this Codespace (the 2026-07-30 gap report found it on a different machine) — either result is fine, just note which.

- [ ] **Step 2: Delete them**

Run: `rm -f /workspaces/bg3_scraper/New-Bg3ParityReconciliation.ps1 && rm -rf /workspaces/bg3_scraper/catalog_workspace`

- [ ] **Step 3: Verify removal and check git status**

Run: `ls /workspaces/bg3_scraper/New-Bg3ParityReconciliation.ps1 2>&1; git status --short`
Expected: `No such file or directory`; `git status --short` shows nothing for the `.ps1` file (it was untracked, so its removal doesn't need a commit — `git status` before deletion would have shown it as `??`, confirmed already in the 2026-07-30 gap report).

- [ ] **Step 4: Commit**

No commit needed — both were untracked. If `git status --short` shows anything else unexpected here, stop and investigate before continuing (per this project's standing rule to never silently discard uncommitted work without checking first).

---

### Task 9: Update CLAUDE.md for the new working model

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: nothing.
- Produces: the documented standing directives that future sessions (including this one, next time) will read and follow.

- [ ] **Step 1: Relax the standing Drive-update directive**

Find the line in `CLAUDE.md` reading (under "Environment notes (this machine)"):
> "**Standing project directive (2026-07-24): keep Google Drive updated for ChatGPT/Codex's use whenever there's a meaningful update, moving forward.**"

Replace that paragraph with:
```markdown
- **Standing project directive (revised 2026-08-04): the project now runs
  primarily out of Claude Code, with Drive as backup and an optional
  second-opinion channel rather than a mandatory sync target.** Update
  Drive when it's actually useful — a backup snapshot of a large artifact,
  or a status doc when Codex's independent review is wanted — not
  automatically after every commit. The old multi-step "conference packet"
  ceremony (dated status docs kept in lockstep pairs, `C1`–`C7` gate
  numbering per `00_SHARED_PROJECT_ROADMAP.md`) is retired as a mandatory
  process; a single current-state doc dropped in Drive is sufficient when
  a second opinion is wanted. See
  `docs/superpowers/specs/2026-08-04-consolidate-into-claude-code-design.md`
  for the full reasoning.
```

- [ ] **Step 2: Document the Downloads/archive non-recreation decision**

In the "Current operational layout" section near the top of `CLAUDE.md`, after the existing bullet about `Downloads/`/`archive/`, add:
```markdown
- **Decided 2026-08-04**: `Downloads/` and `archive/` are not recreated on
  new machines/Codespaces going forward — both are non-authoritative by
  this file's own long-standing description, and Drive remains the backup
  if anything in them is ever needed. See
  `docs/superpowers/specs/2026-08-04-consolidate-into-claude-code-design.md`.
```

- [ ] **Step 3: Note the new `app/catalog_pipeline/` location**

In the "Repo layout" section, after the `app/manifests/` bullet, add:
```markdown
- `app/catalog_pipeline/` — the B26 database-build pipeline, materialized
  from Drive into this repo 2026-08-04 (see
  `docs/superpowers/specs/2026-08-04-consolidate-into-claude-code-design.md`).
  Distinct from `app/scripts/` (scraper-only). The actual `.db` files it
  operates on live in `catalog/B26/` (gitignored, same as `data/`).
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "Revise CLAUDE.md standing directives for the Claude-Code-primary working model"
```

---

### Task 10: One-time Drive resync

**Files:** none locally — this task uploads to Drive.

**Interfaces:**
- Consumes: the current (post-Task-9) `CLAUDE.md` and `README.md`.
- Produces: a fresh, dated snapshot in Drive for Codex's benefit, per the relaxed cadence Task 9 just documented. This is the last time this plan touches Drive.

Per this project's own established convention (documented in `CLAUDE.md`'s history: "No Drive file-update/delete tool exists (only create/copy)... use a clearly dated name, note in the new file's own text which older file(s) it supersedes"), this creates a new file rather than trying to edit the stale one in place.

- [ ] **Step 1: Create the dated snapshot file locally**

Run: `cp /workspaces/bg3_scraper/CLAUDE.md /tmp/CLAUDE_2026-08-04_snapshot.md`

Prepend this note to the top of `/tmp/CLAUDE_2026-08-04_snapshot.md`:
```markdown
> Snapshot for Codex, 2026-08-04. Supersedes the 2026-07-30 copy at this
> same Drive location (`BG3/SCRAPER/CLAUDE.md`, file ID
> `1EehgaJnKwDoLqEJSY2e8x_mzC9mBpTvg`), which predates the consolidation
> work described in
> `docs/superpowers/specs/2026-08-04-consolidate-into-claude-code-design.md`.
> That doc and this project's Drive-update cadence going forward are both
> covered in this file's own "Environment notes" section below.

---

```

- [ ] **Step 2: Upload to Drive**

Call `mcp__claude_ai_Google_Drive__create_file` (or the equivalent create/upload tool available) targeting parent folder `1_AThkcnQ12YbwtDlspAXvNuusGSw1Xdy` (`BG3/SCRAPER/`), with title `CLAUDE_2026-08-04.md`, content from `/tmp/CLAUDE_2026-08-04_snapshot.md`.

- [ ] **Step 3: Verify the upload**

Call `mcp__claude_ai_Google_Drive__search_files` with query `parentId = '1_AThkcnQ12YbwtDlspAXvNuusGSw1Xdy' and title contains 'CLAUDE_2026-08-04'`.
Expected: one result, `CLAUDE_2026-08-04.md`, with a non-zero `fileSize`.

- [ ] **Step 4: Clean up the local temp file**

Run: `rm /tmp/CLAUDE_2026-08-04_snapshot.md`

No git commit — this task doesn't touch the local repo.

---

## Self-Review

**Spec coverage:**
- "Phase 1 — Materialize" (B26 db, pipeline scripts, Phase 2A/2B index) → Tasks 2, 3, 4, 5. ✓
- "Phase 2 — Review" → Task 6. ✓
- "Phase 3 — Decision gate" → Task 7. ✓
- "Phase 4 — Housekeeping" (delete `.ps1`, resync Drive docs, relax standing directive, document `Downloads`/`archive` decision) → Tasks 8, 9, 10. ✓
- "Validation approach" (SHA-256 + SQLite integrity everywhere) → Task 1 (shared tool) used throughout Tasks 2, 4, 5; integrity checks in every materialization task. ✓
- Local structure changes (`catalog/B26/` as working copy, new `app/catalog_pipeline/`) → Tasks 2–5 populate `catalog/B26/`; Task 3 creates `app/catalog_pipeline/`. Note: the spec said `app/catalog/`, corrected to `app/catalog_pipeline/` here because `.gitignore`'s `catalog/` rule would have silently ignored anything under `app/catalog/` — same intent, corrected path.
- "Drive's role changes" (backup, not mandatory sync) → reflected in Task 9's CLAUDE.md edit and Task 10's one-time-not-recurring resync.

**Placeholder scan:** no "TBD"/"handle appropriately"/unfilled sections found — every step has a concrete command or file content. The two `mv <path-from-step-3>` steps (Tasks 4–5) reference a value produced by a `find` command earlier in the same task rather than a fixed path, which is a real runtime substitution, not a placeholder.

**Type/name consistency:** `verify_checksum(path: str, expected_sha256: str) -> bool` (Task 1) is called the same way (positional path, then hash) in every later task's Python usage. The CLI form (`verify_checksum.py <path> <hash>`) matches across Tasks 2, 4, 5. File paths for `catalog/B26/*.db` are spelled identically in Tasks 2/4/5 and their consumption in Task 6.
