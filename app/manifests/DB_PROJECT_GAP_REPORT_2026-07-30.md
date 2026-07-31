# BG3 DB Project — Parity & Gap Report — 2026-07-30

Scope: local repo (`C:\Users\jbell\.local\bin\BG3Scraper`), GitHub
(`jasonmichaelbell78-creator/bg3_scraper`, branch `main`), and Google Drive
(`BG3` root, `1RwND0QAcqwjAq7VuypZTCUunptdZ1tpG`). All findings below are from
live verification performed today (git fetch, local SHA-256 recomputation,
SQLite introspection, and live Google Drive API calls) — not just a re-read
of prior session artifacts, though those (`archive/reconciliation/*`,
prior parity-inventory records) were used as a starting point and
cross-checked.

## 1. Parity summary

### 1a. Local ↔ GitHub: clean

`git fetch` + `git rev-list --left-right --count origin/main...HEAD` → `0  0`.
`main` is byte-for-byte in sync with `origin/main`. Only local difference is
two untracked, not-yet-committed items from today's session
(`New-Bg3ParityReconciliation.ps1`, the now-deprecated `catalog_workspace/`).
No action needed unless/until you want those committed or removed.

### 1b. Local `data/` ↔ Drive `BG3/SOURCES/`: fully matched (with one caught regression — see §2.1)

Every one of the 28 files under local `data/{nexus,modio,collections}/` has
an exact filename+byte-size match somewhere under `BG3/SOURCES/` in Drive.
Zero local-only files, zero size mismatches. This directly contradicts the
`copy_local_to_drive` classification a prior reconciliation register run
gave these same files — that register's automated matching produced false
negatives here (likely because it ran against a Drive inventory snapshot
taken mid-reorg, before today's `BG3/SOURCES/*` layout was finished
populating). Do not trust that specific register's `copy_local_to_drive`
rows for `data/*` without re-running the comparison.

### 1c. The `BG3/ARCHIVE` "gap" noise

Of the prior reconciliation register's 11,141 rows, **7,427 (67%)** are
`BG3/ARCHIVE` vs. local `archive/` mismatches (3,858 `verify_existing_pair`,
2,666 `copy_drive_to_local`, 903 `conflict_requires_choice`). Per
`CLAUDE.md`, Drive `ARCHIVE` is explicitly non-authoritative, and local
`archive/` holds non-authoritative historical material including a stale
manual Drive mirror. **None of this bears on the DB project** — it's inert
historical debris on both sides, not a live-data gap. Recommend leaving it
alone rather than spending reconciliation effort on it.

The remaining substantive categories (`BG3/SOURCES`, `BG3/CATALOG`,
`BG3/SCRAPER`) total only ~83 register rows and, per §1b and §1d, check out
as matched once verified directly rather than through that specific register
run.

### 1d. Local `catalog/B26/` ↔ Drive `BG3/CATALOG/B26/`: byte-verified, exact match

Recomputed SHA-256 locally for all four files; all match the recorded
checksums and the live Drive-side hashes referenced in Drive's own receipts:

| File | SHA-256 (local, recomputed today) | Match |
|---|---|---|
| `BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db` | `cb37e039…3187775` | ✅ |
| `C4_Semantic_B26_Phase1_Coverage_Full_Snapshot.zip` | `50772e00…56ae7ef0` | ✅ |
| `BG3 Reference Catalog — B26 — Collection Memberships.csv` | `de279b39…dd60881d…` | ✅ |
| `BG3 Reference Catalog — B26 — Human Reference.xlsx` | `59572be9…2fbc849a6c` | ✅ |

SQLite `PRAGMA integrity_check` = `ok`, `foreign_key_check` = 0 violations.
This part of the DB project is in good, verified shape.

## 2. DB project gap findings (ranked by severity)

### 2.1 CRITICAL — the canonical Nexus comments corpus has regressed; the version Codex actually built its comment index from is no longer present anywhere

This is the headline finding.

`CLAUDE.md` documents that on 2026-07-25, `nexus_merge_comments.py` v1.1 was
re-run to fold in `nsfw_capture.jsonl` (40,078 rows, 205 NSFW-gated mods) and
`rescue_279.jsonl` (mod 279's partial rescue) on top of the 2026-07-24 base
merge, producing a **451,885-row, ~243MB** `nexus_comments_merged.jsonl`,
and that this file was "re-delivered to Drive 2026-07-25."

That is independently, verifiably **no longer the file present today**, in
either location:

- **Local** (`data/nexus/nexus_comments_merged.jsonl`): `407,222` lines
  (verified via `wc -l`), file dated **2026-07-24 13:16** — i.e. it predates
  the 2026-07-25 NSFW/rescue re-merge entirely. `grep` for mod `22659`
  (documented as having 74 comments post-merge) returns **zero** matches;
  mod `279` returns only 577 rows, not the documented 4,511.
- **Drive** (`BG3/SOURCES/NEXUS/nexus_comments_merged.jsonl`, id
  `1NBiw0ln6JTzt8APcM3uUcIHKn289WH9V`, live-checked via the Drive API just
  now): **230,352,898 bytes** — the same 407,222-row file, not the
  documented 243MB/451,885-row one. The only other copy of this filename
  anywhere in Drive (in the stale `BG3/ARCHIVE/LEGACY_DRIVE_STRUCTURE_2026-07-30/…`
  mirror) is byte-identical to this same older version. **No copy of the
  451,885-row file exists anywhere in Drive today.**

This isn't a guess from file sizes — it's confirmed against Codex's own
build receipt. `BG3/CATALOG/B26_DATABASE_BASELINE/…/PHASE2A_COMMENT_EVIDENCE_INDEX_BUILD_RECEIPT.json`
(dated 2026-07-28, read live from Drive today) records that Codex ingested
`nexus_comments_merged.jsonl` at **451,885 source rows**, SHA-256
`3e931c96f6456b044161ef7e7f64cb4b51d9de32d89d1a0c19bd1b89114934e0`, from
this exact Drive file ID. The file currently living at that ID has a
completely different SHA-256 (locally recomputed: `8babc846…daedae177e44b`)
and 44,663 fewer rows. **Sometime between 2026-07-28 and today, the Drive
file at that ID was overwritten with the older, pre-NSFW/rescue version** —
most plausibly during the 2026-07-29/30 repo reorg, when local `data/nexus/`
(which was itself already stale, per its file timestamp) got treated as
source-of-truth and pushed into the new `BG3/SOURCES/NEXUS/` layout.

**User note (2026-07-30): the correct file is believed to still exist on
another machine/location; recovery is being handled separately and is not
blocking on this report.**

**Consequence if not recovered:** the raw, standalone JSONL for the full
451,885-row Nexus comments corpus — including all 205 NSFW-gated mods'
comments and the majority of mod 279's rescued comments — would not be
recoverable from either this machine or Drive as a plain file. Its two raw
inputs (`nsfw_capture.jsonl`, `rescue_279.jsonl`) are also absent everywhere
checked (confirmed via a full repo-wide filename search; also absent from
Drive). **The content itself is not lost regardless** — it survives as
ingested rows inside Codex's `BG3_Comment_Evidence_Index_Phase2A_candidate.db`
/ `..._Phase2B_B26ExactLinks_candidate.db` (527,928 total comment rows,
`integrity_check: ok`, split across `.tar.gz` parts in
`BG3/CATALOG/B26_DATABASE_BASELINE/` and its `PHASE2A_…`/`PHASE2B_…` sibling
folders) — reconstructing a clean raw JSONL from that means exporting and
reformatting from SQLite, not a simple copy, if it ever comes to that.

### 2.2 HIGH — the B26 baseline database itself has ~0% of the Nexus comments corpus ingested, and a stale/wrong slice of the mod.io one

Distinct from §2.1 above (which is about the raw source file), this is about
`catalog/B26/BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db`
specifically — the file `CLAUDE.md` and the Drive `00_READ_ME_FIRST.md` both
call the current, active reference catalog.

Querying it directly:

- `evidence_corpora` has a `nexus / comments` row with
  `coverage_state: 'not_collected'`, `record_count_raw/unique: 0`, and the
  note *"Raw comments file retained empty; absence is not a no-signal
  finding."* Consistent with that, `evidence_source_records` has **zero**
  rows for that corpus. **None of the ~407K–452K Nexus comments — the thing
  CLAUDE.md calls "the actual gap this project closes" — are in this
  database at all**, regardless of which version of the raw file you'd use.
- For mod.io, `mod_comments` has **56,233** rows across 4,361 mods — that's
  exactly the row count of `modio_fullsweep_comments_2026-07-10`, the
  **known-buggy, ~100-comment-per-mod-capped** sweep CLAUDE.md describes as
  superseded. The two corrected corpora that actually fixed this
  (`modio_comments_base_under_page_limit`, 44,777 rows +
  `modio_comments_deep_refresh`, 31,266 rows = 76,043, matching
  `modio_comments_merged.jsonl` exactly) are listed in `evidence_corpora` as
  `complete` but have **zero** rows in `evidence_source_records`. The
  candidate DB is running on the pre-fix mod.io comment data.

This is likely just sequencing (this DB build predates both comment
efforts landing), but it means: **as of today, the "current" B26 database
has effectively no usable comment data from either platform**, despite both
platforms' comment corpora being fully captured and (mostly) delivered.

Separately, and better news: Codex's own **Phase 2A/2B "Comment Evidence
Index"** effort (`BG3/CATALOG/B26_DATABASE_BASELINE/…`,
`PHASE2A_Comment_Evidence_Index_Unlinked_Full_Snapshot/`,
`PHASE2B_Comment_Evidence_Index_B26ExactLinks_Full_Snapshot/`, all dated
2026-07-28) already solved this at the data layer — it ingested **both**
correct, complete corpora (76,043 mod.io + 451,885 Nexus = **527,928**
comment rows, `integrity_check: ok`, `0` FK violations, deterministic
same-platform exact-ID links into all 19,967 B26 listings, `0` unlinked).
**That work is real and already done** — it just isn't the same database
file as `catalog/B26/…candidate.db`, and (per §2.3) isn't materialized
locally at all. The gap is reconciling/promoting it into the baseline, not
redoing it.

### 2.3 MEDIUM — the Phase 2A/2B Comment Evidence Index databases exist only in Drive, split across `.tar.gz` parts; never materialized locally

`catalog/B26/` locally has exactly 4 files (the two receipts plus the two
canonical artifacts in §1d) — no comment-evidence-index database, no
extracted snapshot. The only copies of
`BG3_Comment_Evidence_Index_Phase2A_candidate.db` (527,928 comments, no B26
links) and `BG3_Comment_Evidence_Index_Phase2B_B26ExactLinks_candidate.db`
(same data, deterministically linked to B26 listings) live in Drive as
11–12 part `.tar.gz` chunks each, with their own SHA256SUMS files. If you
want to actually query the comment evidence locally (e.g. to pull the
triage hits — 16,996 context-required candidates on load order,
incompatibility, dependencies, etc. — into anything downstream), it needs
to be reassembled and pulled down the same way the B26 baseline was earlier
today.

### 2.4 LOW / informational — `platform_listings` counts don't cleanly map to documented sweep sizes; flag for Codex, not necessarily a defect

The B26 candidate DB has `nexus` platform_listings = **11,809** and `modio`
= **8,158** (19,967 total, matching every other B26 count checked). CLAUDE.md
documents the Nexus full sweep as **16,191** mods and the Tier1+Tier2 curated
target list as **3,662** (3,661 after excluding mod 141). 11,809 doesn't
match either number cleanly. This may simply be an intentional filter in
Codex's Phase 1 Coverage migration (dedup, identity resolution, stub
exclusion, etc.) rather than a gap — flagging it as an open question for the
next Claude/Codex conference rather than asserting a problem, since the
migration logic itself is Codex-side and wasn't inspected here.

## 3. What's NOT a gap (confirmed fully consistent)

- **Collections**: DB's `catalog_collections` = 930 = 843 (mod.io) + 87
  (Nexus), exactly matching the documented full sweep totals. All six
  Collections output files are present and byte-matched between local and
  Drive.
- **mod.io comments source file**: `modio_comments_merged.jsonl` (76,043
  rows) is byte-identical between local, Drive `BG3/SOURCES/MODIO/`, and
  the hash Codex's Phase 2A build actually used. This platform's comment
  pipeline has no equivalent regression.
- **Nexus/mod.io structured data (metadata/files/deps/changelogs/team/events)**:
  fully ingested into the B26 candidate DB (125,618 + 73,677
  `evidence_source_records`) and byte-matched between local and Drive.
- **`.gitignore`**: matches CLAUDE.md's documented exclusions
  (`data/`, `catalog/`, `archive/`, `Downloads/`, `Google Drive/`) exactly.
- **The merge script itself**: `app/scripts/nexus_merge_comments.py` v1.1
  (2026-07-25, committed in git) correctly handles folding in
  `nsfw_capture.jsonl`/`rescue_279.jsonl` — the tooling is fine; §2.1 is a
  missing-input/overwritten-output problem, not a code defect.

## 4. Suggested next actions

1. Recover the true 451,885-row `nexus_comments_merged.jsonl` (§2.1) — user
   reports it likely still exists elsewhere and is handling this separately.
2. Once recovered, re-deliver it to `BG3/SOURCES/NEXUS/` in Drive (replacing
   the current regressed copy) and note the incident in `CLAUDE.md` so it
   isn't silently re-lost in a future reorg.
3. Decide whether/when to promote Codex's Phase 2A/2B Comment Evidence Index
   work into (or alongside) the active B26 baseline, since it already
   contains the full, correct, cross-platform comment corpus that the
   baseline candidate DB currently lacks.
4. Materialize the Phase 2A/2B database locally if you want to work with it
   directly (same reassemble-and-verify process used for the B26 baseline
   earlier today).
5. Raise §2.4's `platform_listings` count question at the next Claude/Codex
   conference point rather than guessing at it unilaterally.
6. The `BG3/ARCHIVE` noise (§1c) needs no action — it's inert by design.
