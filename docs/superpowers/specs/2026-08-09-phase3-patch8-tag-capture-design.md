# Phase 3, Workstream 1: Patch-8 Tag Capture — Design

## Goal

Close the "patch-8 compatibility" gap identified in the Gap Report
(`docs/superpowers/specs/2026-08-07-catalog-gap-report.md`, domain "Patch-8
compatibility / maintenance status", Significant severity) and researched in
`docs/superpowers/specs/2026-08-08-patch8-known-broken-status-research.md`
(domain 5). This is one of five independent workstreams under Phase 3
(Deep Mining Execution) of the total project plan
(`docs/superpowers/specs/2026-08-07-total-project-plan-to-loadout-advisor.md`),
chosen to go first for being the cheapest and highest-leverage.

## What changed since the research doc

The research doc concluded both platforms already have this signal sitting
in already-fetched-but-discarded API responses, "zero extra scraping cost."
Checking the actual code and DB directly during this design session found
a real correction to that:

- **mod.io: already done, not just cheap.** The candidate DB
  (`catalog/B26/BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db`)
  already has a `platform_tags` table (`tag_id`, `listing_id` → `platform_listings`,
  `tag`), populated for 7,921/8,158 mod.io listings (a B25-era capture) —
  including `Patch 8 Tested` on 3,044 mods already. No new scraping or
  migration needed for mod.io.
- **Nexus: the research doc was wrong that this is already fetched.**
  `nexus_bg3_scraper.py` calls the v1 REST API
  (`api.nexusmods.com/v1/games/baldursgate3/mods/{id}.json`), confirmed live
  to have **no `tags` field at all** — the existing
  `has_non_english_tag(mod.get("tags") or [])` filter code has always
  silently operated on an empty list. The `Patch 8 Compatible` tag only
  exists via the GraphQL API (`LegacyTag` type), which this project has
  never called for tags. `platform_tags` has **zero Nexus rows**.
- A single unauthenticated, unfiltered GraphQL query
  (`mods(filter:{gameId}, count, offset)` requesting `{modId, tags{name}}`)
  returns every Nexus mod's full tag list in ~189 pages at `count=100` —
  confirmed live, no auth needed, no per-mod calls required.

So the real, narrower scope of this workstream is: **fetch Nexus tags in
bulk and load them into the existing `platform_tags` table.** mod.io needs
no action.

## Scope decisions (confirmed with user)

- **Full tag capture for Nexus**, not narrowed to just `Patch 8 Compatible`.
  Matches the existing table's shape (it already stores all mod.io tags, not
  a curated subset) and costs the same order of magnitude in requests either
  way (~189 pages full vs. ~38 pages filtered-only), with no auth cost
  difference. Avoids a second sourcing pass if another tag-based signal
  becomes useful later (e.g. if a "broken"/"outdated" tag is ever added to
  Nexus's taxonomy).
- **mod.io's existing `platform_tags` data is left as-is**, not refreshed.
  It's a B25-era snapshot (97% coverage) and may be missing newer mods/tags,
  but refreshing it is a separate concern from closing the actual gap
  (Nexus has zero rows). Not in scope for this workstream.
- **No `risk_flags` involvement.** `risk_flags` rows today are hand-verified,
  narratively-justified risk assessments (131 rows total, e.g.
  `not_maintained`, `legacy_ModFixer`) — exclusively negative/warning
  signals with a `basis` explaining a specific judgment call. A bulk,
  mechanically-derived, *positive* signal ("this tag is present") is a
  different kind of data and belongs in `platform_tags`, which already
  exists for exactly this shape of data. No schema change, no semantic
  conflation.

## Architecture

Two new scripts, mirroring this project's established scrape → migrate
pattern.

### 1. `app/scripts/nexus_tags_scraper.py`

Standalone fetch script, pure `requests` — no browser, no auth, no
Cloudflare exposure (same low-friction shape as `nexus_collections_scraper.py`,
unlike the comment-scraping scripts which need Playwright/CDP).

- Paginates `POST https://api.nexusmods.com/v2/graphql` with:
  ```graphql
  query($gid: String!, $count: Int!, $offset: Int!) {
    mods(filter: {gameId: {value: $gid}}, count: $count, offset: $offset) {
      totalCount
      nodes { modId tags { name } }
    }
  }
  ```
  `gid = "3474"` (BG3), `count = 100`, incrementing `offset` until it
  reaches `totalCount`.
- Writes one JSON line per mod to `data/nexus/nexus_tags.jsonl`:
  `{"nexus_mod_id": ..., "tags": [...], "_fetched_at": ...}`.
- **Output file always opens in append mode if it already exists** — the
  v1.13 data-loss lesson (CLAUDE.md), applied proactively even though this
  source is unauthenticated and low-risk, matching this project's blanket
  practice for every scraper regardless of a given source's specific risk
  profile.
- `--resume`: a small JSON progress file (`data/nexus/nexus_tags_progress.json`)
  records the last completed offset; `--resume` skips ahead to it. Given
  ~189 pages with no auth/retry complexity, a full run is expected to
  complete in one pass, but the mechanism costs little and matches every
  other scraper in this project.
- No merge step needed afterward (unlike the comments/Collections corpora)
  — there's no prior partial Nexus tag data to reconcile against; this is a
  single clean fetch into an empty slice of `platform_tags`.

### 2. `app/catalog_pipeline/claude_phase5/load_nexus_tags.py`

Migration script, following the `claude_phase3`/`claude_phase4` discipline
exactly (hash-gate, backup, transaction, receipt, independent
post-run verification) — same shape as `promote_comment_evidence.py` /
`fix_mod_comments_view.py`.

- Reads `data/nexus/nexus_tags.jsonl`.
- For each mod: `SELECT listing_id FROM platform_listings WHERE platform='nexus' AND platform_mod_id=?`.
  - **Expected partial linkage, not a bug**: `platform_listings` has only
    11,809 of the ~18,870 live Nexus mods (the still-unresolved B25-lineage
    gap noted in CLAUDE.md's B26 Phase 4 section) — roughly a third of
    fetched mods won't resolve to a `listing_id`. These are logged and
    skipped in the receipt, not treated as errors.
- For each resolved listing, inserts one row per tag into
  `platform_tags(listing_id, tag)` — **guarded against duplicate insert**:
  `platform_tags` has no unique constraint on `(listing_id, tag)`, so the
  migration checks for existing `(listing_id, tag)` pairs before inserting
  (idempotent on rerun, matters since Nexus currently has zero rows but a
  future rerun — e.g. to refresh — must not double up).
- Own distinct backup-file suffix (e.g. `.pre-phase5-nexus-tags-backup`) —
  the Phase 4 postmortem flagged shared-suffix collisions as a recurring
  risk; each migration script gets its own.
- Single transaction; rollback on any failure.
- Writes `catalog/B26/phase5_nexus_tags_receipt.json` (gitignored, same as
  every prior phase's receipt): rows read, rows inserted, rows skipped
  (unresolved listing), before/after `platform_tags` row count, before/after
  DB hash.
- Post-run independent verification (same standard as every prior phase):
  re-query row counts directly, `PRAGMA integrity_check`, zero FK
  violations, a small spot-check of inserted rows against the source JSONL.

## Data flow

```
Nexus GraphQL API
  → nexus_tags_scraper.py
  → data/nexus/nexus_tags.jsonl  (gitignored, one line per mod, full tag list)
  → load_nexus_tags.py           (hash-gate → backup → transaction → receipt)
  → platform_tags rows (platform=nexus, via listing_id)
```

## Error handling / resilience

- Fetch script: standard retry/backoff on transient HTTP errors (matching
  `nexus_collections_scraper.py`'s existing pattern — no Cloudflare
  challenge handling needed here since GraphQL doesn't front with it, per
  the 2026-07-24 Collections research).
- Migration script: hash-gate against the last known-good DB hash before
  writing (refuse to proceed on an unexplained mismatch, same standing
  project rule as every prior phase); full backup before any write;
  single transaction so a mid-run failure leaves the DB untouched rather
  than partially migrated.

## Testing

TDD against an in-memory SQLite fixture DB, matching `claude_phase4`'s
pattern (`tests/fixtures.py` + `test_load_nexus_tags.py`):

- `platform_mod_id` → `listing_id` resolution, including the unresolved
  case (mod not present in `platform_listings`).
- Duplicate-guard: rerunning the migration against a DB that already has
  some `(listing_id, tag)` rows doesn't double-insert.
- Row-count and receipt-field correctness on a small fixture with a mix of
  resolved/unresolved mods and mods with zero/one/many tags.
- Rollback-on-failure: an injected mid-transaction error leaves the fixture
  DB unchanged.

## Execution ownership

Both scripts run directly by Claude in this project, matching how every
prior phase's scrape and migration steps have been executed (confirmed
with user 2026-08-09). The fetch is unauthenticated, low-risk GraphQL
traffic already verified live during this design session; the migration
follows the same hash-gate/backup/receipt/independent-verification
discipline used for every real DB write in this project to date.

## Out of scope (explicitly, per user decisions above)

- Refreshing mod.io's existing `platform_tags` data.
- Any change to `nexus_bg3_scraper.py` itself (this is a standalone script,
  not a modification to the main sweep scraper).
- Loading anything into `risk_flags`.
- Building `conflict_checker.py` or any other loadout-advisor consumer code
  — that's Phase 4 of the total project plan, still paused pending all of
  Phase 3's workstreams.
