# Phase 3, Workstream 2: VOLO Masterlist Ingestion — Design

## Goal

Close part of two Blocking/Significant gaps from the Gap Report
(`docs/superpowers/specs/2026-08-07-catalog-gap-report.md`) — load-order
positioning rules (Blocking) and deployment type (Significant) — by
ingesting VOLO's public, CC0-licensed masterlist. Both the load-order
research (`docs/superpowers/specs/2026-08-08-load-order-positioning-research.md`)
and the deployment-type research
(`docs/superpowers/specs/2026-08-09-deployment-type-research.md`)
independently recommended adopting VOLO's data as a next step. This is the
second of five independent Phase 3 workstreams (the first,
patch-8 tag capture, is complete — see
`docs/superpowers/specs/2026-08-09-phase3-patch8-tag-capture-design.md`).

## What changed since the research docs

Both research docs are two days old; VOLO is an actively-developed project,
and re-fetching the live masterlist during this design session
(`https://raw.githubusercontent.com/Moonie8t7/VOLO/main/masterlist/bg3-masterlist.json`)
found real drift worth recording before designing against stale numbers:

- **The masterlist has grown 2.4x**: 7,671 plugins now (schema `version`
  `2.0.0`), up from 3,138 at research time. Divider/group coverage grew
  proportionally: 6,926/7,671 (90.3%, vs. 89.7% then).
- **The deployment-type research's headline number was wrong.** It reported
  VOLO's `usesScriptExtender` field covering "6,296/19,967 mods (31.5%)."
  Direct inspection of the live file finds this field present (and always
  `true` when present — it's omitted rather than set `false`) on only
  **299/7,671 plugins (3.9%)**, plus a related but distinct `featureFlags`
  array (`Lua`/`Osiris` values) on 163 plugins. Where the 31.5% figure came
  from is unclear — possibly a misread of a different field or a stale
  snapshot — but it does not match the real source data and this design
  uses the verified 3.9% figure instead.
- **A signal neither research doc discussed**: 367 plugins carry an
  explicit `dependencies` array (`[{uuid, name}, ...]`) — real, structural
  "must load after X" pairs, distinct from and higher-trust than the
  `divider`/`group` bucket assignment. This maps directly onto the existing
  `load_order_hints` table's shape.
- **The `divider`/`group` field is backed by a real ordered structure**,
  not just a label: the masterlist's top-level `groups` array has 30
  entries, each with a `name`, a `description`, and an `after` pointer to
  the group it follows (e.g. `"User Interface"` comes `after`
  `"Top of Load Order"`). `divider` is a plugin's numeric position, `group`
  its human-readable bucket name (Astra's taxonomy, per the load-order
  research).
- **`evidence.source` is a real trust taxonomy, not just install counts.**
  Distribution across all 7,671 plugins: `section` 3,460, `name-pattern`
  1,424, `section-majority` 1,110, `none` 737, `external-category` 712,
  `inferred` 188, `curated` 24, `author-catalogue` 16. This is the field
  used for the confidence tagging discussed below — richer than the
  research's "only 16 hand-verified" framing, though `curated` is still a
  small minority.
- **No Nexus/mod.io ID field exists anywhere in the plugin objects** — VOLO
  has its own synthetic `uuid`, unrelated to either platform's IDs.
  Confirms the research's conclusion that matching has to go by name +
  author.

## Scope decisions (confirmed with user)

- **Ingest both signal families** (divider/load-order and Script-Extender/
  deployment-type) in one pass — one fetch either way, and splitting into
  two separate workstreams would just duplicate the fetch/match plumbing.
- **Ingest all divider-assigned rows, tagged with their confidence, not
  pre-filtered.** `evidence_source`/`evidence_installs`/`working`/`broken`
  travel with every row so a downstream consumer (e.g. a future
  `evidence_claims` review pass) can apply its own trust cutoff, rather
  than this migration silently discarding rows the research flagged as
  low-trust-but-not-worthless.
- **Matching: auto-accept high-confidence, flag the rest for review, don't
  guess and don't silently drop.** Mirrors the existing `evidence_claims`
  review-state pattern already used elsewhere in this project.
- **One-time ingestion, not scheduled refresh.** The pipeline is built to
  be rerunnable by hand (same fetch → match → migrate shape works again
  later), but no cron/automation is built now. Re-running later is cheap
  once the pipeline exists.
- **Storage: dedicated new tables per signal type, reuse `load_order_hints`
  where it already fits.** See Schema below.

## Schema

Three destinations for three distinct signal types pulled from the same
source file:

### 1. `catalog_volo_divider_signals` (new table)

One row per VOLO plugin that carries a `divider`/`group` assignment
(6,926 rows expected).

```sql
CREATE TABLE catalog_volo_divider_signals (
    signal_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mod_uid INTEGER,                    -- nullable: NULL if unmatched
    volo_uuid TEXT NOT NULL,
    volo_name TEXT NOT NULL,
    volo_author TEXT,
    group_name TEXT,
    divider_position INTEGER,
    evidence_source TEXT,               -- curated/author-catalogue/section/
                                         -- section-majority/name-pattern/
                                         -- external-category/inferred/none
    evidence_installs INTEGER,
    evidence_working_installs INTEGER,
    evidence_broken_installs INTEGER,
    match_status TEXT NOT NULL,         -- matched/needs_review/unmatched
    match_score REAL,
    source_version TEXT NOT NULL,       -- masterlist "version", e.g. "2.0.0"
    captured_at TEXT NOT NULL,          -- masterlist "generated" timestamp
    FOREIGN KEY (mod_uid) REFERENCES mods(mod_uid)
);
```

### 2. `load_order_hints` (existing table, reused as-is)

For each plugin's `dependencies` entries: resolve the *source* plugin to a
`mod_uid` via name+author match, then resolve each dependency target the
same way (first against the VOLO masterlist's own `uuid`→plugin index,
then that plugin's name+author against `mods`/`platform_listings`).

- `relation_type = 'after'`
- `relative_to_mod_uid` = resolved target's `mod_uid` when found
- `relative_to_text` = raw dependency `name` when the target can't be
  resolved to a `mod_uid` (schema already supports this either/or shape)
- `source = 'volo'`
- `source_platform` = NULL (VOLO spans both platforms)
- `confidence = 'high'` — this is a structural field VOLO's own tooling
  derives from explicit mod requirements, not an inferred/algorithmic
  guess like the divider bucket
- `supporting_text` = the source plugin's `name` (for traceability)

No source-side row is inserted if the *source* plugin itself doesn't
resolve to a `mod_uid` (a hint needs a concrete mod to attach to).

### 3. `catalog_volo_deployment_signals` (new table)

One row per VOLO plugin carrying `usesScriptExtender` and/or a non-empty
`featureFlags` (roughly 299 ∪ 163 rows expected, some overlap).

```sql
CREATE TABLE catalog_volo_deployment_signals (
    signal_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mod_uid INTEGER,                    -- nullable: NULL if unmatched
    volo_uuid TEXT NOT NULL,
    volo_name TEXT NOT NULL,
    volo_author TEXT,
    uses_script_extender INTEGER NOT NULL DEFAULT 0,  -- 0/1
    feature_flags TEXT,                 -- JSON array, e.g. ["Lua"]
    match_status TEXT NOT NULL,         -- matched/needs_review/unmatched
    match_score REAL,
    source_version TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    FOREIGN KEY (mod_uid) REFERENCES mods(mod_uid)
);
```

## Matching

VOLO plugins carry `name` + `author` only. Join target is
`mods.canonical_name` (joined out to `platform_listings.author` via
`mod_uid`, since `author` lives on the listing, not the mod record).

1. **Normalize** both sides: lowercase, strip punctuation/whitespace
   variance (matches this project's existing normalization precedent from
   the Collections/comment merge scripts).
2. **Exact match**: normalized name equal AND normalized author equal (or
   one is a token-subset of the other, to handle cases like VOLO's
   `"bibsan (prev. Djmr / AlanaSP / ShinyHobo / Zee)"` author field against
   a platform listing's plain `"bibsan"`) → `match_status = 'matched'`.
3. **Fuzzy fallback**: `difflib.SequenceMatcher` ratio on the normalized
   name above a fixed threshold (0.85, tunable during implementation) →
   `match_status = 'needs_review'`, `mod_uid` still populated with the best
   candidate so the row is queryable, but flagged rather than trusted
   blindly.
4. **No match above threshold** → `mod_uid = NULL`,
   `match_status = 'unmatched'`. Row is still inserted (not dropped) so
   coverage stats stay honest — a future consumer can see exactly how much
   of VOLO's data didn't link, rather than that gap being invisible.

No new dependency: `difflib` is stdlib, consistent with keeping this
project's dependency footprint minimal (`requirements.txt` currently has
just `requests`/`playwright`/`beautifulsoup4`).

A mod can have multiple `platform_listings` rows (one per platform). Match
against all candidates across both platforms; if name+author matches
listings on both Nexus and mod.io for the same VOLO plugin, that's expected
(the mod's `mods.canonical_name` already anchors both listings to the same
`mod_uid` in this project's existing identity-resolution scheme) and only
one signal row is written per VOLO plugin regardless.

## Architecture

Two scripts, mirroring this project's established scrape → migrate
pattern (same shape as Phase 5's `nexus_tags_scraper.py` /
`load_nexus_tags.py`).

### 1. `app/scripts/volo_masterlist_fetch.py`

- Downloads the raw masterlist JSON via a single unauthenticated GET
  (no pagination, no auth, no Cloudflare — plain GitHub raw content).
- Writes it verbatim to `data/volo/bg3-masterlist_<YYYY-MM-DD>.json`
  (gitignored, alongside every other raw corpus this project captures).
- Writes a small sidecar manifest
  `data/volo/bg3-masterlist_<YYYY-MM-DD>.manifest.json` recording the
  masterlist's own `version`/`generated`/`gameBuild`/`gamePatch` fields
  plus the downloaded file's SHA-256 — same provenance discipline as
  `manifest_modio_comments.md`/`.json` and other prior corpora.

### 2. `app/catalog_pipeline/claude_phase6/load_volo_masterlist.py`

Migration script, following the `claude_phase3`/`claude_phase4`/
`claude_phase5` discipline exactly: hash-gate the candidate DB against its
last known-good SHA-256, `backup_database()` with a **distinct** suffix
(`.pre-phase6-volo-backup` — avoiding the Phase 4 suffix-collision lesson
recorded in CLAUDE.md), single transaction, `migration_history` row claims
the slot first (unique constraint blocks accidental reruns), JSON receipt,
independent post-run verification.

- `CREATE TABLE` statements for the two new tables run as part of this
  migration (no separate schema-migration step — matches how prior phases
  have added new tables inline with their first data-loading migration).
- Reads the fetched masterlist JSON, builds the name+author match index
  from `mods`/`platform_listings` once, then for each plugin:
  - Inserts one `catalog_volo_divider_signals` row if the plugin has a
    `divider`/`group`.
  - Inserts one `catalog_volo_deployment_signals` row if the plugin has
    `usesScriptExtender` and/or non-empty `featureFlags`.
  - Inserts `load_order_hints` rows for each resolvable `dependencies`
    entry, per the rules above.
- Writes `catalog/B26/phase6_volo_masterlist_receipt.json` (gitignored):
  rows read, rows inserted per table, match-status breakdown (matched /
  needs_review / unmatched counts), before/after row counts, before/after
  DB hash.

## Data flow

```
VOLO GitHub repo (raw JSON, CC0)
  → volo_masterlist_fetch.py
  → data/volo/bg3-masterlist_<date>.json + .manifest.json  (gitignored)
  → load_volo_masterlist.py   (hash-gate → backup → CREATE TABLE → match → transaction → receipt)
  → catalog_volo_divider_signals rows
  → catalog_volo_deployment_signals rows
  → load_order_hints rows (source='volo')
```

## Error handling / resilience

- Fetch script: standard retry/backoff on transient HTTP errors. No
  Cloudflare or auth handling needed — this is a plain GitHub raw-content
  GET, same low-friction category as the Collections scrapers.
- Migration script: hash-gate against the last known-good DB hash before
  writing (refuse to proceed on an unexplained mismatch, the standing
  project rule since the `nexus_comments_merged.jsonl`/Phase 4 hash
  incidents); full backup before any write; single transaction so a
  mid-run failure leaves the DB untouched.
- Malformed/unexpected plugin entries (missing `name`, missing `uuid`) are
  skipped and counted in the receipt, not fatal to the whole run.

## Testing

TDD against an in-memory SQLite fixture DB, matching the
`claude_phase4`/`claude_phase5` pattern (`tests/fixtures.py` +
`test_load_volo_masterlist.py`):

- Name/author normalization and the three match tiers (exact, fuzzy
  above threshold, below threshold/unmatched).
- Dependency-pair resolution: both sides resolve, only the source
  resolves (target stored as `relative_to_text`), source doesn't resolve
  (no hint row written at all).
- Divider-signal and deployment-signal row construction from representative
  fixture plugin objects (with/without `divider`, with/without
  `usesScriptExtender`/`featureFlags`).
- Hash-gate, rerun-blocked (`migration_history` unique-constraint
  collision), rollback-on-malformed-source-entry.
- `CREATE TABLE IF NOT EXISTS` idempotency (migration doesn't fail if the
  tables already exist from a prior partial run).

## Execution ownership

Fetch and migration both run directly by Claude in this project, matching
every prior phase — the fetch is a single unauthenticated GET already
verified live during this design session; the migration follows the same
hash-gate/backup/receipt/independent-verification discipline used for
every real DB write in this project to date.

## Out of scope (explicitly, per user decisions above)

- Scheduled/automated refresh of the masterlist. The pipeline is built
  rerunnable by hand; no cron or scheduling mechanism is built now.
- A dedicated table for the 30-node `groups` ordering chain itself —
  `group_name`/`divider_position` on `catalog_volo_divider_signals` are
  enough for this workstream; a full group-ordering table can be added
  later if a consumer needs to compute group-to-group sequencing.
- The masterlist's top-level `incompatible` array — currently empty in the
  live file (0 entries), nothing to ingest.
- Ingesting the BG3 Load Order Optimizer masterlist (separate project,
  restrictive data license, explicitly flagged in the research as needing
  its own licensing decision — not part of this workstream).
- Any loadout-advisor consumer code that would read these new tables —
  that's Phase 4 of the total project plan, still paused pending all of
  Phase 3's workstreams.
