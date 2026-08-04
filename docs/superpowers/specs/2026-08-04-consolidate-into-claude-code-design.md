# BG3 Project Consolidation into Claude Code — Design

**Date:** 2026-08-04
**Status:** Approved, ready for implementation planning

## Context

This project moved to GitHub Codespaces because of work-network IT restrictions
(Mimecast blocking `nexusmods.com` at the device level — see `CLAUDE.md`'s
"Running from work: GitHub Codespaces" section). That move exposed how much of
the project's existing structure assumed a different working model than the
one that now actually exists.

### Current state (as of 2026-08-04)

**Raw data collection (Nexus + mod.io scraping): complete.** Every documented
sweep — metadata/files/changelogs/dependencies, deep comments, Collections,
for both platforms — is done and verified. All 28 source dataset files are
byte-identical across this Codespace, GitHub, and Google Drive
(`BG3/SOURCES/{NEXUS,MODIO,COLLECTIONS}`), confirmed live today via the Drive
API. `nexus_comments_merged.jsonl`'s 2026-07-25→07-31 regression (documented
in `CLAUDE.md`) is resolved: both the local copy and the Drive copy are the
correct 451,885-row version.

**The B26 Reference Catalog (the actual end deliverable): incomplete, and
owned by a separate party.** A SQLite database (`BG3_Reference_Catalog_v1_1_
Working_B26_Phase1_Coverage_candidate.db`, 19,967 listings, 930 Collections,
49,907 membership rows) is built from the scraper's raw output by a separate
AI collaborator ("Codex"/ChatGPT), working in its own environment, with
Google Drive as the only shared channel between the two. Per the 2026-07-30
gap audit (`app/manifests/DB_PROJECT_GAP_REPORT_2026-07-30.md`), still open
as of today:

- The B26 database has **zero Nexus comments** and a **stale, superseded
  slice of mod.io comments** (56,233 old-capped rows instead of the
  corrected 76,043), despite both corpora being fully captured.
- Codex separately built a correct, complete **527,928-row "Comment Evidence
  Index"** (both platforms, deterministically linked to B26 listings) that
  fixes this — but it exists only in Drive, split into `.tar.gz` parts, in
  an **orphaned pre-reorg folder** (`00_AUTHORITATIVE_CHECKPOINTS/...`, not
  the current `BG3/CATALOG` structure), never promoted into the active
  baseline, never materialized locally anywhere.
- B26's `platform_listings` count (11,809 Nexus + 8,158 mod.io = 19,967)
  doesn't cleanly match documented sweep sizes (16,191 Nexus full sweep,
  3,662-mod curated Tier1+Tier2 target list) — flagged as an open question
  for Codex, not confirmed as a defect.

**This Codespace's local environment is missing pieces the project's own
docs assume exist**, because they're gitignored and never survived the
machine move: `catalog/B26/` (local DB copy), `Downloads/` (immutable
intake), `archive/` (local reconciliation history). An untracked Windows
PowerShell script (`New-Bg3ParityReconciliation.ps1`) sits at repo root,
built for a three-way manual reconciliation workflow that can't even run in
this Linux Codespace.

**The Claude/Codex working relationship has become the actual bottleneck.**
The existing process — Drive as the only channel, an 876MB database that
can only be uploaded as 10 split zip parts because of Drive's ~100MB
connector ceiling, no in-place file editing (Drive's connector only
supports create/copy, never update), a formal multi-step "conference
packet" ceremony (`C1`–`C7` gates, versioned status docs kept in lockstep
pairs) — has caused two real data-loss/regression incidents already (the
2026-07-25→31 `nexus_comments_merged.jsonl` regression, and the earlier
2026-07-23 accidental full-dataset wipe from a `--resume`-less rerun) and
has gotten difficult to keep up with. The back-and-forth itself is valuable
(a second opinion, independent error-checking) — the mechanism around it is
what needs to change.

### Target state for this spec

Bring the project's active work fully into Claude Code: Claude gets direct,
local, editable access to everything currently gated behind Drive
(including the B26 database and Codex's build pipeline), Drive is
demoted from "mandatory shared record" to "backup + optional second-opinion
drop," and the local environment is cleaned up to match a single-Codespace
reality instead of a multi-machine one.

This spec explicitly **stops at a decision gate** (Phase 3 below) rather
than designing the full catalog-build pipeline blind. Whether Claude
continues Codex's existing schema/scripts or redesigns them can only be
decided after actually reading that pipeline — which this spec produces the
access to do, but does not itself resolve.

## Gap analysis → what this spec closes

| Gap | Resolution in this spec |
|---|---|
| B26 `.db` only exists in Drive, split/whole, never local | Phase 1: materialize + verify locally in `catalog/B26/` |
| Codex's build/migration scripts only exist in Drive, not runnable by Claude | Phase 1: materialize into new `app/catalog/` |
| Phase 2A/2B evidence index only in Drive, orphaned pre-reorg location | Phase 1: materialize + verify locally |
| No informed adopt-vs-redesign decision possible yet | Phase 2: review Codex's actual schema/pipeline; Phase 3: decision checkpoint with Jason |
| Local Codespace missing `catalog/B26/`, stray Windows script | Phase 1 (materialize) + Phase 4 (delete the `.ps1` script) |
| `Downloads/`/`archive/` assumed but absent | Phase 4: explicitly not recreated (both are non-authoritative per existing `CLAUDE.md` language; Drive remains the backup) |
| Drive's `CLAUDE.md`/`README.md` mirror 2 commits stale | Phase 4: one-time resync |
| Heavyweight, hard-to-maintain conference-packet ceremony | Phase 4: relax `CLAUDE.md`'s standing Drive-update directive; retire mandatory `C1`–`C7` gate language |

**Explicitly out of scope / deferred to a follow-up spec:** actually closing
the B26 content gaps (ingesting correct comments, promoting/reconciling the
evidence index, resolving the `platform_listings` question). That work
depends on the Phase 3 decision and gets its own design once that decision
is made.

## Architecture

**Materialize locally, into this repo's working tree:**
- `catalog/B26/BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db`
  — downloaded from Drive `BG3/CATALOG/B26/` (single-file copy, not the
  split-parts copy in `B26_DATABASE_BASELINE/`), byte-verified against
  SHA-256 `cb37e0392b7bdb0b06f8095c44b8352363610999498ff4803e07411df3187775`.
- Codex's build pipeline, into a new `app/catalog/` directory (git-tracked):
  `register_phase1_coverage.py`, `taxonomy_rules_phase0_reconciled_2026-07-27.py`
  (from Drive `CATALOG/B26_DATABASE_BASELINE/`), and
  `build_phase2_comment_evidence_index.py`,
  `finalize_phase2_comment_evidence_index.py`,
  `report_phase2_comment_evidence_index.py` (from Drive's orphaned
  `00_AUTHORITATIVE_CHECKPOINTS/PHASE2A_.../PHASE2B_.../` folders — found
  via Drive search, not the current `BG3/CATALOG` tree).
- The Phase 2A/2B Comment Evidence Index databases themselves, reassembled
  from their `.tar.gz` parts and byte-verified against their documented
  SHA-256 values (Phase 2A: `c7a6367489592c534ae0eefc65937194f36f2fad1d52
  e883e775f75e9ecd493c`; Phase 2B: `a7d20f9586a7413f8d1a82ed2965de4cdcb19f9
  42d59400be5896b3e3e72bfaa`).

**Drive's role changes** from "authoritative shared record + mandatory
handoff mechanism" to **backup + optional second-opinion drop**:
- Drive keeps receiving the large artifacts as an off-Codespace backup —
  unchanged.
- The formal conference-packet ceremony (versioned status docs, `C1`–`C7`
  gate numbering, paired docs kept in lockstep) is replaced by: when a
  second opinion is wanted, drop one current-state doc in Drive — no
  mandatory format, no blocking gate, no obligation to keep parallel docs
  in sync after every change.
- `CLAUDE.md`'s standing directive ("keep Google Drive updated... whenever
  there's a meaningful update") is relaxed to "update Drive when it's
  useful for backup or a second opinion," not after every commit.

## Local repo/structure changes

- **`catalog/B26/`** — stops being a read-only, someone-else's-immutable
  checkpoint. Becomes Claude's real working copy. Still gitignored (876MB,
  same reasoning as `data/`).
- **`app/catalog/`** (new) — home for the materialized catalog-build
  pipeline, tracked in git, separate from `app/scripts/` (scraper-only).
  Also where the Phase 3 decision's outcome lives (continued Codex pipeline,
  or its replacement).
- **`Downloads/`** — not recreated. Per `CLAUDE.md`'s own description this
  is inert immutable intake; nothing pending depends on it.
- **`archive/`** — not recreated. Per `CLAUDE.md` and the 2026-07-30 gap
  report, this is non-authoritative historical debris on both the local and
  Drive side ("inert by design"). Google Drive remains the backup if
  anything in it is ever needed.
- **`New-Bg3ParityReconciliation.ps1`** — deleted, not ported. It was
  built for the exact three-way manual reconciliation workflow this spec
  retires; its job is replaced by the materialize-and-checksum-verify
  pattern already proven today.
- **Drive's stale `BG3/SCRAPER/CLAUDE.md` / `README.md` mirror** (2 commits
  behind local git as of today) — one-time resync, then covered going
  forward by the relaxed update cadence above.

## Phases

**Phase 1 — Materialize.** Pull down and SHA-256-verify the B26 `.db`, the
Phase 1 migration/taxonomy scripts, and the Phase 2A/2B evidence index
(reassembled from `.tar.gz` parts) into `catalog/B26/` and `app/catalog/`.
Run `PRAGMA integrity_check` and `PRAGMA foreign_key_check` on both
databases after materializing — nothing is treated as authoritative without
both checks passing, matching the standard the 2026-07-30 audit already
used.

**Phase 2 — Review.** Read Codex's actual schema and migration logic
end to end (table structure, taxonomy rules, how the Phase 1 and Phase 2
scripts work) — not just receipts describing them. Produce a short findings
writeup covering whether the pipeline is sound and worth continuing, or has
structural issues that argue for a redesign.

**Phase 3 — Decision gate.** Present the Phase 2 findings directly to
Jason: adopt Codex's pipeline as-is (continue it from `app/catalog/`) vs.
redesign it. This is a checkpoint requiring an explicit human decision, not
something resolved autonomously. This spec's implementation ends here.

**Phase 4 — Housekeeping.** Independent of the Phase 3 decision, so can
happen anytime in the sequence: delete the `.ps1` script; resync Drive's
stale `CLAUDE.md`/`README.md` copies; relax `CLAUDE.md`'s standing
Drive-update directive and retire the `C1`–`C7` conference-gate language;
document the `Downloads/`/`archive/` non-recreation decision in `CLAUDE.md`.

## Validation approach

Consistent with the project's existing discipline (every prior audit in
`CLAUDE.md` follows this pattern): SHA-256-verify everything that moves
between Drive and local disk; run SQLite integrity/foreign-key checks on
any database before treating it as current; never assume a copy is
current without an explicit check, since that assumption is exactly what
caused both prior incidents.

## Explicitly deferred (follow-up spec, post-Phase-3)

Actually closing the B26 content gaps: ingesting the correct
(76,043-row mod.io / 451,885-row Nexus) comment corpora into the active
B26 baseline, promoting/reconciling the Phase 2A/2B evidence index into it,
and investigating the `platform_listings` count discrepancy. This depends
entirely on the Phase 3 decision and will be designed once that decision is
made.
