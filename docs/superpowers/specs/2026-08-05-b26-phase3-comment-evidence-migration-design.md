# B26 Phase 3: Promote comment evidence into the active baseline — design

**Date:** 2026-08-05
**Status:** design, not yet planned/implemented

## Context

The 2026-08-04 consolidation plan materialized three candidate databases and had
Codex's B26 pipeline reviewed (see
`docs/superpowers/specs/2026-08-04-b26-pipeline-review-findings.md`, decided
2026-08-05: **adopt** Codex's pipeline with three follow-up conditions). That
findings doc identified two still-open content gaps:

- **(a)** B26's `mod_comments` table holds only a superseded, mod.io-only,
  pre-pagination-fix capture (56,233 rows, zero Nexus) — the correct comment
  data exists but isn't queryable from B26.
- **(b)** The Phase 2A/2B comment-evidence-index (527,928 comments, fully
  linked to B26 listings, zero dangling references) exists as a separate
  companion database and has never been promoted into B26 itself.

This spec designs the migration that closes both gaps. It is the first of
several independent follow-up pieces identified by the findings doc (see
"Explicitly out of scope" below for the others) — scoped and brainstormed
separately per `superpowers:brainstorming`'s decomposition guidance, since the
full set of follow-ups is not one project.

## Goal

**Not** a multi-AI community reference system. The actual goal (stated
directly by Jason, 2026-08-05): a single AI-queryable database holding all
available BG3 mod information in one place, so that building a working mod
load order — what works, what works together, what depends on what, what
order to load things in — doesn't require guessing or re-researching each
time. This migration's specific contribution: make the comment-derived
evidence (dependency mentions, incompatibility reports, load-order requests,
bug reports) actually queryable from B26, instead of sitting in a separate
companion database or a stale, mod.io-only table.

## Scope

**In scope:**
- Ingest the **451,885 Nexus comments** from Phase 2B's `comments` table
  into `evidence_source_records`, sourced from Phase 2B rather than
  re-parsing `nexus_comments_merged.jsonl` directly — Phase 2B's table is a
  strict superset (already deduplicated, threaded, and linked to
  `platform_listings`). **Correction (2026-08-05, caught during planning,
  verified against live data): mod.io's 76,043 comments are NOT re-inserted
  — a set-membership check confirmed B26's existing
  `evidence_source_records` (corpora `f12290b9…`/`e88d8457…`) already holds
  the exact same 76,043 mod.io comment IDs Phase 2B has (100% overlap,
  zero difference). Re-inserting them from Phase 2B would have silently
  created 76,043 duplicate rows.** The original design's "527,928 in one
  bulk insert" was wrong; Nexus is genuinely new, mod.io is not.
- Promote all 16,996 `triage_hits` into `evidence_claims` (2,016 mod.io +
  14,980 Nexus — both platforms, unlike the comment insert above), tagged
  `evidence_state='triage_only'` — explicitly unvalidated regex hits, not
  confirmed facts. Nexus-derived claims link to the newly inserted Nexus
  `evidence_source_records` rows; mod.io-derived claims link to the
  *existing* mod.io rows (looked up by comment ID, not re-inserted).
  (Landing them now with an honest "unvalidated" label is different from
  citing them as evidence; the precision/recall measurement that would
  justify treating them as more than that is separate follow-up work, not
  a blocker to storing them queryably.)
- Retire `mod_comments`: drop the table, replace it with a view over
  `evidence_source_records` — confirmed via repo-wide search that nothing
  else in the codebase reads or writes it, so this is low-risk.

**Explicitly out of scope** (separate follow-up pieces, each independent —
not blocked by this migration and don't block it):
- Taxonomy precedence bug fix (`taxonomy_rules_phase0_reconciled_2026-07-27.py`
  silently starving two browse-label groups)
- Triage precision/recall measurement + rule versioning
  (`triage_rule_catalog`/`triage_hits` versioning, starting with the
  under-triggered `required_dependency` rule)
- Small cleanups from the findings doc's "also worth doing" list: the
  contradictory `build_metadata` key in Phase 2B, hardcoded figures in
  `report_phase2_comment_evidence_index.py:54`
- Policy/provenance judgment calls that are Jason's to make, not
  implementation work: whether English-only Nexus scope is intentional, and
  the origin of 38 `not_in_metadata` Nexus listings

## Architecture

New script: `app/catalog_pipeline/claude_phase3/promote_comment_evidence.py`
— in `claude_phase3/` (not `codex_phase1`/`codex_phase2`) because this is
authored by Claude Code, not materialized from Codex's output. Codex's own
`phase2b_authority_boundary` explicitly declares "no B26 mutation" as a
policy boundary, so this migration is necessarily new work, following the
same hash-gated/transactional/receipt-producing pattern
`register_phase1_coverage.py` established (the findings doc recommended
keeping that pattern "unconditionally").

One script, one command, one result — deliberately not split into staged
sub-scripts (Codex's own phase2 build/finalize/report split was considered
and rejected as unnecessary complexity for a single logical migration).

## Data Flow

Mutates `catalog/B26/BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db`
**in place** — consistent with `register_phase1_coverage.py`'s existing
precedent and with `catalog/B26/` now being documented (per the 2026-08-04
consolidation) as Claude's real local working copy, not a read-only
checkpoint.

1. **Backup**: filesystem copy to
   `BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db.pre-phase3-backup`
   before touching anything.
2. **Hash-gate**: verify the candidate DB's SHA-256 matches the known-good
   value (`cb37e0392b7bdb0b06f8095c44b8352363610999498ff4803e07411df3187775`,
   confirmed 2026-08-05) and the Phase 2B DB's SHA-256 matches its known
   value (`a7d20f9586a7413f8d1a82ed2965de4cdcb19f942d59400be5896b3e3e72bfaa`).
   Abort with no changes if either mismatches.
3. **Test batch** (verify *before* scaling up): `BEGIN` a transaction,
   insert a small, deliberately-chosen sample — at least one Nexus mod and
   one mod.io mod with nested reply threads, to exercise threading logic —
   using the exact code path the full migration will use.
4. **Direct verification of the test batch**: field-by-field comparison of
   the inserted rows against Phase 2B's source rows (content, timestamps,
   `source_listing_uuid` resolution, content hash) — not aggregate counts.
   Any mismatch: `ROLLBACK`, fix the script, retry from step 3.
5. Once the test batch checks out: `ROLLBACK` it (clean slate), then run
   the real migration in a fresh transaction:
   - New `evidence_corpora` row recording this ingestion, with
     `supersedes_corpus_uuid` pointing at the `not_collected` Nexus
     placeholder (`cc2ea89e-3980-552e-aeb3-4c7e6056a3a1`) — mod.io's
     corpora (`f12290b9…`/`e88d8457…`) are untouched, not superseded,
     since mod.io data isn't being re-inserted.
   - Bulk-insert **451,885** `evidence_source_records` rows for **Nexus
     only** from Phase 2B's `comments` table WHERE `platform='nexus'`
     (`source_listing_uuid` copied directly from Phase 2B's
     already-verified `b26_listing_uuid` — no re-resolution needed).
     mod.io rows are NOT touched — confirmed via set-membership check that
     B26 already holds the exact same 76,043 mod.io comment IDs Phase 2B
     has.
   - Promote all 16,996 `triage_hits` → `evidence_claims`
     (`evidence_state='triage_only'`) — both platforms. Nexus-derived
     claims (14,980) link via `evidence_claim_links` to the
     newly-inserted Nexus rows above; mod.io-derived claims (2,016) link
     to the pre-existing mod.io rows, found by looking up each
     `comments.source_comment_id` against
     `evidence_source_records.provider_native_id` within the existing
     mod.io corpora — not inserted.
   - `DROP TABLE mod_comments`; `CREATE VIEW mod_comments AS ...` — a
     fresh, sensible shape over `evidence_source_records`, not a shim
     preserving the old (structurally broken) table's columns.
   - Record the migration in `migration_history`; write an
     `ingestion_stage_receipts` row.
   - `COMMIT`.
6. **Post-commit validation**: re-open the DB read-only and validate
   (same pattern as `register_phase1_coverage.py`).
7. **Independent verification of the full committed result** (separate from
   step 6, and from the script's own receipt): aggregate counts
   cross-checked against multiple independent references (Phase 2B's own
   totals, not just this migration's receipt), plus a *second* freshly
   -sampled batch of direct row-level spot-checks — different rows than
   step 4, to catch anything that only shows up at scale.

## Error Handling & Safety

- **Hash-gate failure**: abort immediately, before the backup step, no
  changes made.
- **Test-batch verification failure**: `ROLLBACK`, script exits with a
  clear diagnostic (which field, expected vs. actual value). Nothing
  committed — safe to fix and re-run from scratch.
- **Full-batch failure** (constraint violation or crash mid-transaction):
  SQLite rolls back automatically; the filesystem backup is a second line
  of defense against a crash that corrupts the file rather than just
  aborting a statement.
- **Re-run safety**: hash-gated and keyed by a unique `migration_name` in
  `migration_history` — re-running against an already-migrated DB fails the
  gate rather than double-inserting, same idempotency pattern as Phase 1.

## Acceptance Criteria

All of the following, checked independently — not solely via the script's
own receipt (per this project's standing preference: scripted batch work
needs thorough post-examination via direct analysis, not just a clean exit
code):

1. `evidence_source_records` grew by exactly **451,885** rows (Nexus only —
   mod.io's existing 76,043 rows are untouched, count unchanged), all with
   non-null `content_sha256`/`payload_json`.
2. All 451,885 new rows have non-null `source_listing_uuid` (matches Phase
   2B's own "zero dangling" result for Nexus).
3. `evidence_claims` grew by exactly 16,996 rows (both platforms), all
   `evidence_state='triage_only'`; `evidence_claim_links` grew by exactly
   16,996 rows, each resolving to a real `evidence_source_records` row —
   14,980 to the newly-inserted Nexus rows, 2,016 to the pre-existing
   mod.io rows.
4. `mod_comments` is now a view, not a table; querying it returns data;
   nothing else in the repo that referenced the old table breaks (confirmed
   nothing currently does).
5. `PRAGMA integrity_check` and `PRAGMA foreign_key_check` both clean on
   the final committed DB.
6. A fresh random sample of ≥20 rows spot-checked field-by-field against
   Phase 2B's source data (distinct from the test-batch sample) — including
   at least a few mod.io-linked `evidence_claims` rows, to confirm the
   lookup-not-insert path for mod.io worked correctly.
7. Backup file exists on disk with its checksum recorded, for recovery if
   a problem surfaces later despite the above.

## References

- `docs/superpowers/specs/2026-08-04-b26-pipeline-review-findings.md` —
  the review that identified these gaps and recommended this approach
  (§5(a), §5(b), §6 conditions 3)
- `docs/superpowers/specs/2026-08-04-consolidate-into-claude-code-design.md`
  — established `catalog/B26/` as the local working copy
- `app/catalog_pipeline/codex_phase1/register_phase1_coverage.py` — the
  hash-gated/transactional/receipt pattern this migration follows
