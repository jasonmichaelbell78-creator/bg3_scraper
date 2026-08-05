# B26 pipeline review findings (2026-08-04)

Input to the Task 7 adopt-vs-redesign decision gate. This is a review of
Codex/ChatGPT's schema and pipeline work, based on direct inspection of the three
materialized candidate databases and the five materialized pipeline scripts — not
on receipt JSON or Drive status docs.

**Artifacts reviewed**

| Artifact | Path |
|---|---|
| B26 reference catalog | `/workspaces/bg3_scraper/catalog/B26/BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db` |
| Phase 2A evidence index | `/workspaces/bg3_scraper/catalog/B26/BG3_Comment_Evidence_Index_Phase2A_candidate.db` |
| Phase 2B evidence index | `/workspaces/bg3_scraper/catalog/B26/BG3_Comment_Evidence_Index_Phase2B_B26ExactLinks_candidate.db` |
| Phase 1 scripts | `app/catalog_pipeline/codex_phase1/{register_phase1_coverage.py, taxonomy_rules_phase0_reconciled_2026-07-27.py}` |
| Phase 2 scripts | `app/catalog_pipeline/codex_phase2/{build,finalize,report}_phase2_comment_evidence_index.py` |

B26 holds 40 tables and 3 views. Headline counts: `mods` 19,967 · `platform_listings`
19,967 (11,809 Nexus / 8,158 mod.io) · `evidence_source_records` 331,571 ·
`platform_file_records` 106,910 · `mod_classifications` 8,249 ·
`catalog_browse_labels` 19,967 · `catalog_collections` 930 ·
`catalog_collection_memberships` 49,907 · `mod_comments` 56,233 ·
`migration_history` 2.

---

## 1. Schema soundness

### What is done well

**Cross-field CHECK constraints make invalid states unrepresentable, not merely
discouraged.** This is the strongest single property of the schema. Examples:

- `catalog_collection_memberships` — `CHECK((mapping_state = 'resolved' AND mapped_listing_uuid IS NOT NULL AND mapping_method = 'exact_platform_id') OR (mapping_state = 'unmapped' AND mapped_listing_uuid IS NULL AND mapping_method = 'none'))`. A row cannot claim to be resolved while carrying no target, or claim exact-ID matching while being unmapped.
- `claim_review_decisions` — `CHECK(decision <> 'promote' OR promoted_target_ref IS NOT NULL)`. A promotion decision cannot exist without a promotion target.
- `evidence_claim_links` — `CHECK(source_record_uuid IS NOT NULL OR artifact_uuid IS NOT NULL)`. A link must point at something.
- `mod_uuid_redirects` — `CHECK(retired_mod_uuid <> survivor_mod_uuid)`. No self-redirect loops.

**Enumerated states are constrained everywhere they matter**, rather than being
free-text conventions: `evidence_corpora.coverage_state` (7 values, including the
important `not_collected` vs `zero` vs `analyzed_no_match` distinction),
`evidence_claims.evidence_state` / `claim_state`, `relationship_unresolved_targets.resolution_state`,
`target_resolution_attempts.resolution_state`, `identity_observations.identity_state`,
`ingestion_stage_receipts.status`, `classification_reviews.review_state`,
`catalog_browse_labels.browse_group` (all 14 groups enumerated in the CHECK) and
`label_basis`.

**Soft-retire modelling is correct.** `uq_mod_classifications_active ON
mod_classifications(mod_uuid, term) WHERE retired_at IS NULL` — a partial unique
index, so a term can be retired and later re-applied without violating uniqueness,
and history is preserved rather than deleted.

**Normalizing expression index.** `uq_platform_listings_platform_id ON
platform_listings(lower(trim(platform)), trim(platform_mod_id))` defends against
whitespace/case-variant duplicate listings at the index level rather than relying
on every writer to normalize.

**Deterministic identity.** UUIDv5 over a documented seed string, with the method
and seed retained per row in `mod_identity_anchors(generation_method, seed_value)`.
Identity is reproducible from source rather than being an opaque allocation.

**Verified clean.** Re-run during this review: `PRAGMA quick_check` = `ok` and
`PRAGMA foreign_key_check` returns zero rows on all three databases. (Full
`integrity_check` plus checksum verification was independently run in Tasks 2/4/5.)

### Design issues that will make future work harder

**1. Two parallel identity systems coexist, and nothing forces them to agree.**
The pre-v1.1 tables key on integer surrogates — `dependencies`, `dependency_closure`,
`risk_flags`, `item_injection`, `load_order_hints`, `mod_rank`, `mod_relationships`,
`mod_comments` all reference `mods(mod_uid)`; `platform_tags` references
`platform_listings(listing_id)`. Everything added from v1.1 onward keys on TEXT
UUIDs — `mod_classifications`, `classification_*`, all nine `evidence_*` tables,
`catalog_browse_labels`, `catalog_collection_memberships`, `platform_file_records`.

The bridge is `mods.mod_uuid` and `platform_listings.listing_uuid`, both of which
were added by `ALTER TABLE` and are **nullable TEXT with a plain UNIQUE index**.
SQLite permits unlimited NULLs in a UNIQUE index, so the UUID layer is structurally
optional even though half the schema depends on it. A row inserted into `mods`
without a `mod_uuid` is fully visible to the legacy tables and completely invisible
to every UUID-keyed table. Currently benign (all 19,967 rows have UUIDs), but it is
an unenforced invariant carrying the entire newer half of the schema.

**2. `mod_comments` cannot represent both platforms.** Its primary key is a bare
`comment_id INTEGER PRIMARY KEY` and it has no `platform` column — mod.io and Nexus
comment IDs are independent integer spaces, so inserting Nexus comments would
collide. It also links only via `mod_uid`, never `listing_uuid`, so a comment can
be attributed to a merged mod identity but not to the platform listing it was
actually posted on. The Phase 2 index takes the opposite approach (keys on
`(platform, platform_mod_id)` → `listing_uuid`). The two comment models are not
directly reconcilable. See §5(a).

**3. `dependency_closure` declares no foreign keys at all** — `mod_uid` and
`transitive_dependency_uid` are bare INTEGERs while the neighbouring `dependencies`
table does declare `REFERENCES mods(mod_uid)` on both sides. Inconsistent, and it
means the derived closure can silently outlive the edges it was derived from.

**4. FK enforcement is opt-in and per-connection.** SQLite defaults
`PRAGMA foreign_keys = OFF`. Codex's scripts set it correctly every time
(`register_phase1_coverage.py:110`, `build_phase2_comment_evidence_index.py:275`,
`finalize_phase2_comment_evidence_index.py:29`), but the constraints are
declarative-only for any client that forgets. Worth a documented convention, not a
schema change.

**5. `evidence_corpora.record_count_raw` / `record_count_unique` are NULL for the two
largest corpora** (`modio_fullsweep_structured_2026-07-10`,
`nexus_structured_2026-06-28`), so the table cannot self-report coverage for exactly
the corpora where it would matter most.

**6. Phase 2B's `build_metadata` contains a directly false statement.** It carries
`b26_reference_db = "not materialized in this run; no B26 listing links were written"`
alongside `phase2b_linkage_status = "All comment rows linked to B26 by exact
same-platform native mod ID only."` — and all 527,928 rows *are* linked.
`build_metadata` is a flat key/value table with no supersession concept; `finalize`
uses `INSERT OR REPLACE` but the 2B linker only added new keys and left the stale
2A one in place. Minor, but a reader trusting `build_metadata` at face value is
misled.

**Verdict on §1:** the schema is well above average — the constraint discipline is
genuinely good and the newer tables are carefully designed. Issue 1 (dual identity)
and issue 2 (`mod_comments`) are the two that will actually cost something later,
and both are legacy inheritance rather than defects in Codex's own additions.

---

## 2. Migration approach

`register_phase1_coverage.py` implements a hash-gated, idempotent, receipt-producing
migration. Concretely:

| Property | Implementation |
|---|---|
| Input DB pinned | `:81-85` — SHA-256 of the target DB must equal `BASE_DB_SHA256`; otherwise `SystemExit`, before any connection is opened |
| Input *sources* pinned | `:96-104` — all four Collections JSONL files hashed, compared to pinned expected values, refuses on any mismatch |
| Missing-input guard | `:93-95` — explicit existence check with the missing paths named |
| Idempotence | `:112-116` — refuses if `migration_history` already contains `MIGRATION_NAME` (which is `UNIQUE NOT NULL`) |
| Atomicity | `:118` `BEGIN IMMEDIATE`; `:306-308` rollback on any exception |
| In-transaction post-conditions | `:211-212` label count must be 19,967; `:276-277` all four post-migration counts must match `expected_after`; `:281-282` mapping-state split must be exactly `{resolved: 48898, unmapped: 1009}` — any failure raises *inside* the transaction and rolls back |
| Validation of the committed artifact | `:313-319` — reopens the DB on a **separate read-only/immutable handle** and runs `integrity_check` + `foreign_key_check` there, not on the writing connection |
| Receipt | `:320-336` — records input DB SHA, output DB SHA, taxonomy rule SHA, every source input SHA, validation results, row counts, mapping states, per-platform label distribution, and an explicit `unmapped_policy` statement |

**This pattern is worth keeping regardless of the adopt/redesign call.** Two
specific reasons grounded in this project's own history: the 2026-07-23 incident
where a `mode="w"` open silently truncated a 3,657-mod dataset, and the 2026-07-30
regression where a stale local copy overwrote the canonical 451,885-row corpus
because nothing verified what was being pushed. Both are exactly the failure class
that an input-hash gate plus a recorded output hash prevents. The `unmapped_policy`
field — recording that no fuzzy/title/alias matching was applied — is also a good
habit: it documents what the migration deliberately *didn't* do, which is usually
the thing a later reader needs.

**Weaknesses (all minor, none structural):**

- Every constant is module-level and hardcoded (`BASE_DB_SHA256`, `MIGRATION_NAME`, `expected_shas`, `expected_after`, the literal `19967`/`48898`/`1009`). The script is genuinely single-use; the *pattern* is reusable but the file is not. Extracting a small `hash_gated_migration` helper would let the next migration inherit the discipline without copy-paste drift.
- No `--dry-run`. Given the post-conditions run inside the transaction, a dry-run mode that always rolls back would be nearly free and would let the assertions be checked before committing to a real run.
- The receipt is written after `con.commit()` (`:305` then `:335`). A crash in between leaves an applied migration with no receipt file. Recoverable — `migration_history` still records it — but the receipt is the artifact everything downstream cites.
- `args.receipt` writability is never checked before the transaction begins.

---

## 3. Taxonomy rule quality

The 14-group taxonomy assigns exactly one `browse_group` per listing
(`catalog_browse_labels.listing_uuid` is the PRIMARY KEY), covers 19,967/19,967
listings, and falls back to `Other / Source Detail Limited` for only 446 (2.23%).

**Real strength: every label carries auditable provenance.** Each row records
`label_basis` (one of four constrained values), a free-text `basis_detail` naming
the specific signal that fired, the SHA-256 of the rule file, the taxonomy version,
and the assignment timestamp. Distribution:

| Label basis | Count | Share |
|---|---:|---:|
| Listing-derived | 11,008 | 55.13% |
| Native platform | 6,520 | 32.65% |
| Curated / checked | 1,993 | 9.98% |
| Broad fallback | 446 | 2.23% |

That means any future relabelling can be scoped precisely — e.g. "re-examine only
the 11,008 heuristic labels, leave the 6,520 native-category ones alone."

**Real problem: two groups are starved by rule precedence, and they are the two
most relevant to this project's downstream purpose.**

| Browse group | Listings | Share |
|---|---:|---:|
| Equipment, Items, Loot & Vendors | 4,389 | 21.98% |
| Character Creation & Appearance | 2,908 | 14.56% |
| Gameplay, Rules & Quality of Life | 2,863 | 14.34% |
| Classes, Subclasses & Progression | 2,555 | 12.80% |
| Spells, Abilities & Feats | 1,838 | 9.21% |
| Patches, Compatibility & Translation | 1,581 | 7.92% |
| Companions, NPCs & Followers | 985 | 4.93% |
| Visuals, Audio & Animation | 751 | 3.76% |
| Races, Backgrounds & Deities | 641 | 3.21% |
| Interface & Accessibility | 530 | 2.65% |
| Other / Source Detail Limited | 446 | 2.23% |
| Frameworks & Utilities | 376 | 1.88% |
| **World, Quests & Exploration** | **66** | **0.33%** |
| **Difficulty, Encounters & AI** | **38** | **0.19%** |

38 difficulty/encounter mods out of 19,967 is not credible for BG3, and the cause is
demonstrable in the rule ordering. In `choose_group`, the native-category override
at `taxonomy_rules_phase0_reconciled_2026-07-27.py:244-245` fires for
`category in {maps, quests, gameplay, races, photo mode}` **before** the curated-term
passes at `:235-237` and `:253-258`. So a mod that a human reviewer explicitly
tagged `encounter-content` or `combat-system-overhaul`, but which Nexus categorises
as "gameplay", is routed to the broad Gameplay bucket and never reaches its own
curated term. Measured directly against the data:

- Of 24 listings carrying the active curated term `combat-system-overhaul`: **19** landed in `Gameplay, Rules & Quality of Life` via `Native platform`, 2 more via `Listing-derived`, and only **1** in `Difficulty, Encounters & AI`.
- Of 29 listings carrying `encounter-content`: 15 landed in `Gameplay, Rules & Quality of Life` (Native platform), 7 in `World, Quests & Exploration`, 5 in `Patches, Compatibility & Translation`, and **0** in `Difficulty, Encounters & AI`.

The code comment at `:241-243` shows this was deliberate ("a campaign can include an
encounter term without becoming an encounter mod"), so it is a judgement call rather
than an oversight — but the judgement is over-broad. `gameplay` is Nexus's largest
catch-all category; treating it as an authoritative primary content type outranks
the only human-checked evidence in the system. Note also the internal contradiction:
`GROUP_PRIORITY` ranks `Difficulty, Encounters & AI` **4th of 13** (i.e. as a strong,
specific role that should outrank generic buckets), yet the precedence order means
that tie-breaker is almost never consulted for it.

**Other findings:**

- **Single-label forcing is questionable for a browse taxonomy.** A "PT-BR translation of a subclass mod" is genuinely both `Patches, Compatibility & Translation` and `Classes, Subclasses & Progression`. Because `listing_uuid` is the PRIMARY KEY of `catalog_browse_labels`, multi-label would require a schema change, not just a rule change. Worth deciding deliberately rather than inheriting.
- **Latent crash in `priority_pick` (`:183-185`).** It does `next(group for group in GROUP_PRIORITY if group in available)` with no default. `GROUP_PRIORITY` lists 13 of the 14 groups — `Other / Source Detail Limited` is absent. Safe today only because no `TERM_GROUPS` or `TAG_GROUPS` value maps to `Other`; adding one would raise `StopIteration` mid-migration. A one-word fix (`next(..., "Other / Source Detail Limited")`).
- **Provenance-hash coupling flaw.** `taxonomy_rule_sha256` (recorded on all 19,967 label rows) is the SHA of the *whole file*, which also contains an unrelated Phase-0 profiling `main()` pointed at a hardcoded B25 path that does not exist locally (`:16`). Editing the reporting half changes the recorded rule hash even though no rule changed — and conversely the hash cannot be re-derived from a rules-only extraction. The rules should live in their own module.
- The rule set is English-only (`KEYWORDS`, the appearance/NPC regexes). Consistent with B26's English-only listing scope (see §5(c)), so not currently a defect — but it locks in that scope.

---

## 4. Comment evidence-index triage approach

### The approach is sound, and the reason is structural, not stylistic

Regex over user-generated text is inherently low-precision. Codex's design does not
pretend otherwise — it encodes the limitation in constraints rather than in
documentation:

- `triage_hits.disposition_state` — `CHECK(disposition_state = 'triage_only_context_required')`. Exactly one legal value.
- `triage_hits.full_comment_required` — `CHECK(full_comment_required = 1)`.
- `triage_rule_catalog.author_tier_elevating` — `CHECK(author_tier_elevating = 0)`.

Those three CHECKs make "a regex hit was promoted into a fact" or "a regex hit
elevated an author's trust tier" *unrepresentable in the schema*. That is the right
way to ship a heuristic: the hit is a pointer into evidence, and the schema refuses
to let it become the evidence. The full comment body is retained on every row plus
an FTS5 index, so a reviewer always lands on the original text.

There is also a real precision layer, not just raw pattern matching: `should_record`
(`build_phase2_comment_evidence_index.py:165-172`) suppresses `file_variant_advice`,
`named_patch_addon` and `acquisition_content` hits when the comment is a question or
request, and suppresses `incompatibility` hits on hedged wording ("I suspect",
"maybe", "might"). Crude, but it targets the dominant false-positive mode for
user-generated text.

Yield is 16,996 hits over 527,928 comments (3.2%), which reads as a triage funnel
rather than a keyword dragnet:

| Rule | Hits |
|---|---:|
| `author_context` | 6,063 |
| `incompatibility` | 3,166 |
| `relative_load_order` | 2,520 |
| `named_patch_addon` | 1,843 |
| `file_variant_advice` | 1,746 |
| `required_dependency` | 920 |
| `acquisition_content` | 738 |

Data handling is careful in ways that are easy to get wrong: threading is modelled
per-platform (`modio_dotted_reply` vs `nexus_parent_pointer`) rather than forced
into one shape, and `comment_thread_link_audit` explicitly distinguishes `root`
(227,164) from `retained_parent` (300,719) from `parent_not_retained` (45) — so the
45 replies whose parent is missing from the corpus are never silently recast as
top-level comments. Coverage state distinguishes `complete_capture` (523,343) from
`partial_capture` (4,585 — mods 279 and 22659), preserving the "absence is not
zero-signal" distinction.

**This is worth extending, not a dead end.** But four things need fixing first.

### Concerns

**1. Recall is entirely unmeasured, and one rule looks badly under-triggered.**
Nothing in the build receipt, the finalize receipt, or the report estimates
precision or recall against a labelled sample. The specific worry is
`required_dependency` — the single most operationally important rule for load-order
guidance — at only 920 hits across 527,928 comments. Its pattern
(`build_phase2_comment_evidence_index.py:40`) is
`\b(?:requires?|needs?|won'?t\s+work|does(?:\s+not|n't)\s+work)\s+(?:without|with)\b`,
which requires `requires`/`needs` to be *immediately followed by* `with` or
`without`. That matches "won't work without X" but misses the far more common
"requires Script Extender" and "you need ImpUI". 920 is much more likely to be a
pattern-narrowness artefact than a true measure of how often dependencies are
discussed.

**2. No rule versioning.** `triage_rule_catalog` has no version column and
`triage_hits` does not record which rule revision produced it. Re-running the build
with edited patterns silently changes the meaning of stored hits, with no way to
tell old hits from new. This matters as soon as the rules are iterated — which
concern 1 says they should be.

**3. Coverage state is hardcoded rather than derived.**
`build_phase2_comment_evidence_index.py:197` — `partial = mod_id in {"279", "22659"}`.
Correct today (4,585 partial rows = 4,511 + 74, matching the documented captures),
but the source corpora carry their own `_status` sentinels and those were not used.
A future sweep that resolves 279 or introduces a new partial would be silently
mislabelled.

**4. Asymmetric field population.** `thread_depth` is computed for mod.io from the
dotted `thread_position` (`:187`) but is always `NULL` for Nexus (`:201`), even
though Nexus depth is derivable from the parent-pointer chain. Any depth-based query
silently returns mod.io-only results.

**Two smaller code-quality notes:**

- `report_phase2_comment_evidence_index.py:54` hardcodes *"227,164 roots, 300,719 replies with retained parents, and 45 replies whose parent is not retained"* as literal prose, while every other figure in the same report is interpolated from the receipt. The numbers are correct against the current data — I verified all three — but the report will silently state falsehoods if re-run on changed data.
- `comment_fts` is a standalone FTS5 table duplicating every comment body (`comment_fts_content` holds all 527,928 rows). That is the main reason the index is 761 MB. An external-content FTS (`content='comments'`) would roughly halve it. Not wrong, just costly.

---

## 5. The three still-open gaps from the 2026-07-30 audit

### (a) Ingest the correct comment corpora into B26 itself

**Current state, measured.** B26's `mod_comments` holds 56,233 rows across 4,361
mods — mod.io only, zero Nexus. That count matches the `evidence_corpora` row
`modio_fullsweep_comments_2026-07-10` (`record_count_unique` = 56,233,
`coverage_state` = `partial`, limitation note: *"One unpaginated API page per
listing; partial where comment count reaches the page cap"*). So `mod_comments` is
the **superseded pre-pagination-fix capture**.

Importantly, the *correct* mod.io data is already inside B26 — just in the evidence
layer, not in `mod_comments`. `evidence_source_records` holds 44,777 rows from
`modio_comments_base_under_page_limit_2026-07-21` plus 31,266 from
`modio_comments_deep_refresh_2026-07-21` = 76,043, all with `source_listing_uuid`
populated, and there is a committed `ingestion_stage_receipts` row
(`C3B_modio_comment_corpus_registration`, 76,043 seen / 76,043 written / 0 skipped,
`listing_unresolved: 0`). The Nexus side is a registered placeholder:
`nexus_comments_2026-06-28` with `coverage_state = 'not_collected'`,
`record_count_raw = 0` and the note *"Raw comments file retained empty; absence is
not a no-signal finding."*

**What it takes:**

1. **Nexus into the evidence layer** — insert a new `evidence_corpora` row for the 451,885-row `nexus_comments_merged.jsonl` (SHA `3e931c96…`) and point its `supersedes_corpus_uuid` at `cc2ea89e-3980-552e-aeb3-4c7e6056a3a1`; the supersession mechanism already exists in the schema. Then insert 451,885 `evidence_source_records` rows. Every required column exists and every value is available from the corpus. `source_listing_uuid` will resolve for all 3,396 Nexus mods — proven, because Phase 2B already resolved exactly those and all links check out (see (b)). Roughly a 2.4× growth of `evidence_source_records` (331,571 → ~783,000).
2. **`mod_comments` is the actual blocker, and it is a schema decision, not a data one.** As noted in §1, it cannot hold both platforms: `comment_id INTEGER PRIMARY KEY` with no `platform` column, over two independent ID spaces. **Recommendation: retire `mod_comments` rather than migrate it** — replace it with a view over `evidence_source_records WHERE provider_object_type='comment'`, which already carries platform (via `corpus_uuid` → `evidence_corpora.provider`), listing linkage, content hash, raw locator, and the full payload. Migrating `mod_comments` forward means adding a platform column, rebuilding the primary key, and maintaining a second comment store indefinitely.

This gap is **real work but fully specified** — no unknowns remain.

### (b) Promote/reconcile the Phase 2A/2B evidence index into the active baseline

**This is the cheapest of the three and is essentially ready to execute.**

Verified directly: the Phase 2A and Phase 2B schemas are **byte-identical** —
`diff` of the two `.schema` outputs is empty. `b26_listing_uuid` and
`b26_listing_link_state` were present in the 2A schema from the start, defaulted to
`'deferred_b26_materialization'`; 2B is a pure data update that populated them.
That is good forward planning and it means promotion carries no schema surprise.

Link integrity, checked against the live B26: all **7,757** distinct
`b26_listing_uuid` values in Phase 2B resolve against
`B26.platform_listings.listing_uuid`. **Zero dangling.** All 527,928 comment rows
are linked (`b26_listing_link_state = 'linked_exact_platform_id'`, 527,928/527,928).
Resulting coverage of B26:

| Platform | Listings with comment coverage | Total B26 listings | Coverage |
|---|---:|---:|---:|
| mod.io | 4,361 | 8,158 | 53.5% |
| Nexus | 3,396 | 11,809 | 28.8% |

**What it takes:** a migration in exactly the `register_phase1_coverage.py` shape —
hash-gate on the current B26 SHA and on the Phase 2B index SHA, create the
`evidence_corpora` rows, bulk-insert `evidence_source_records` from `comments`
(which is the same work as (a) — the two gaps should be closed in one migration),
and land `triage_hits` either as a new table or as `evidence_claims` rows with
`evidence_state = 'triage_only'`. Note that value **already exists** in the
`evidence_claims.evidence_state` CHECK constraint — the schema anticipated this
promotion path.

Codex's declared `phase2b_authority_boundary` (*"Companion index only; no B26
mutation and no claim/evidence/review/promotion/author-tier action"*) is a **policy
statement recorded in `build_metadata`, not a schema constraint**. It does not block
promotion; it records that promotion is a deliberate decision to be taken explicitly.

**One thing to check before promoting:** Phase 2B's `build_metadata` records
`phase2b_b26_database_sha256 = cb37e0392b7bdb0b06f8095c44b8352363610999498ff4803e07411df3187775`
as the B26 it was linked against. That is **not** the same value as the Phase 1
migration's `source_db_sha256` (`27783c96…`, the pre-migration B25 input) — as
expected, since Phase 2B linked against the post-Phase-1 output. Confirm it matches
the SHA of the local `..._Phase1_Coverage_candidate.db` before promoting, so the
links are known to have been computed against this exact artifact.

### (c) The `platform_listings` count discrepancy

**Answerable now, locally, from data already on this machine. It does not require
asking Codex.**

The raw Nexus corpus Codex ingested is recoverable and identifiable: every
`evidence_source_records.raw_locator` for a Nexus listing points at
`bg3_nexus_data.zip:bg3_nexus_data/mods_metadata.jsonl#L<n>`, and the maximum line
reference is exactly **29,106** — which is exactly the line count of
`/workspaces/bg3_scraper/data/nexus/legacy_full_sweep/nexus_mods_metadata.jsonl`.
Same artifact. Full reconciliation:

| Step | Count |
|---|---:|
| Lines in `nexus_mods_metadata.jsonl` | 29,106 |
| Distinct `mod_id` (10,536 duplicate lines from resumed/overlapping discovery passes) | 18,570 |
| — of which `status='published'` AND `available=true` | 13,864 |
| — of which stub records (`removed` 2,329 · `hidden` 1,039 · `not_published` 975 · `wastebinned` 332 · `under_moderation` 31) | 4,706 |
| `evidence_source_records` Nexus listing rows (matches distinct IDs exactly) | 18,570 |
| — promoted to `platform_listings` | 11,771 |
| — retained as evidence only | 6,799 |
| B26 `platform_listings` Nexus total (11,771 + 38 `not_in_metadata`) | **11,809** |

The 13,864 published+available records are **exactly** the set carrying a
`description` field — i.e. the ones that received a full metadata fetch; the other
4,706 are ID-only stubs. So the usable universe was 13,864, not 18,570.

**Why ~2,160 published+available mods did not become listings: an English-only
filter.** Of the 2,154 unlinked published+available corpus records, **1,053 (48.9%)
carry an explicit translation marker in the title alone** (`PT-BR`, `Traduzione ITA`,
`Traduzido`, `Turkish`, `Greek Language`, …) — and that is a title-only regex, so it
is a floor, not a ceiling. Sampled titles are unambiguous: *"Book of Wizards - 5e
Wizard Subclasses PT-BR"*, *"Astarion Confession Edit 2 Traduzione ITA"*, *"Early
Access Scenes Restored for Turkish"*, *"Baldur's Gate 3 Greek Language"*.
Corroborating from the other direction: B26's own `mods.language_detected` is `en`
for **11,697 of 11,809** Nexus rows (99.05%), with the remainder `unknown` (99) plus
single-digit counts of es/de/ca/ro/pt/pl/it/fr/da. And the scraper's own
`nexus_run_summary.json` records the policy explicitly: `skipped_language: 4063`.

**The "16,191" figure is itself the error, and should be corrected in CLAUDE.md.**
It comes from `nexus_run_summary.json`'s `"mods_written": 16191`, recorded alongside
`"unavailable": 2943`, `"skipped_language": 4063`, and a progress file showing
`done_ids: 26000` (the sweep walked mod IDs 1–26,000 across resumed runs). It does
not correspond to any distinct-mod count in the retained corpus — not 18,570, not
13,864, not 11,809. It is a **per-run write-event counter across a resumed sweep**,
not a corpus size, which is also why the metadata file has 29,106 lines for 18,570
distinct IDs. CLAUDE.md's "fully scraped … for 16,191 mods" should read *"18,570
distinct Nexus mod IDs captured, 13,864 of them with full published metadata."*

**Residual judgement calls — for Jason, not for Codex:**
1. Is English-only the intended catalog scope? It is defensible for a load-order guidance corpus (a PT-BR translation of a subclass mod carries no independent load-order semantics), but it is currently an undocumented implicit policy rather than a recorded decision. It should be written down either way.
2. The 38 Nexus listings with `status='not_in_metadata'` appear in `platform_listings` but in **no** listing source record. Their origin is undocumented — most likely inferred from dependency or relationship references. Low-stakes, but it is the one number in the reconciliation with no provenance.

---

## 6. Recommendation: **adopt Codex's pipeline, with three bounded corrections**

### Why adopt

**1. The expensive part is already built and demonstrably working.** Provenance
discipline — hash-gated migrations, `migration_history` idempotence, receipts with
input *and* output hashes, integrity/FK validation on a re-opened read-only handle,
per-row source attribution (`taxonomy_rule_sha256`, `source_corpus_sha256`,
`source_line_number`, `raw_locator` down to the source line) — is the part that
teams skip and later regret. This project has already been burned twice by exactly
the failure it prevents (the 2026-07-23 truncation, the 2026-07-30 stale-corpus
regression). A redesign would have to rebuild all of it before reaching parity.

**2. The schema anticipates the remaining work instead of blocking it.**
`evidence_state = 'triage_only'` already exists for Phase 2 promotion.
`supersedes_corpus_uuid` already exists for corpus replacement.
`b26_listing_uuid` / `b26_listing_link_state` existed in the 2A schema before 2B
needed them — which is why the 2A→2B schema diff is empty and 2B was a pure data
update. That is a pattern of someone designing one step ahead, and it is worth
inheriting.

**3. Every problem found is data-level or rule-level, not architectural.** Nothing
in this review requires a table structure to change in order to make progress — with
the single exception of `mod_comments`, which is *pre-existing legacy*, not Codex's
design, and whose recommended fix is retirement rather than migration.

**4. The artifacts verify clean.** All three databases pass `quick_check` and
`foreign_key_check`. All 7,757 cross-database links between Phase 2B and B26
resolve, zero dangling. The Phase 1 migration's post-conditions are recorded and
reproducible. Counts reconcile end-to-end (76,043 + 451,885 = 527,928 exactly;
4,511 + 74 = 4,585 partial rows exactly).

**5. The cost of redesign is concrete and the benefit is not.** Redesigning means
re-deriving 19,967 listings, 8,249 classifications, 19,967 browse labels, 331,571
evidence records, 930 collections with 49,907 memberships, and a 527,928-row indexed
comment corpus — against no identified structural defect that forces it.

### Conditions of adoption

**1. Fix the taxonomy precedence before browse labels are used for anything
user-facing.** Move the curated-term pass ahead of the `gameplay` native-category
override, or add an explicit exception so `encounter-content` and
`combat-system-overhaul` survive it. As it stands, the two groups most relevant to
load-order and difficulty guidance — the project's actual downstream purpose — hold
0.19% and 0.33% of the catalog, and 19 of 24 human-tagged combat-overhaul mods are
absorbed into a generic bucket. While in there: split the rules out of the Phase-0
profiling file so `taxonomy_rule_sha256` hashes rules only, and give `priority_pick`
a default to close the `StopIteration` path.

**2. Establish a measured precision/recall baseline for the triage rules, and
version them, before any triage count is cited as evidence.** Start with
`required_dependency` — 920 hits across 527,928 comments, with a pattern that
requires `requires`/`needs` to be immediately followed by `with`/`without` and
therefore misses the dominant "requires X" form. Add a version column to
`triage_rule_catalog` and a rule-version reference on `triage_hits` so iterating the
patterns does not silently rewrite the meaning of stored hits.

**3. Decide `mod_comments`' fate explicitly, as part of the (a)+(b) combined
migration.** It currently holds the superseded 56,233-row mod.io capture and cannot
structurally hold both platforms. Recommend retiring it behind a view over
`evidence_source_records` rather than migrating it forward.

### Also worth doing (cheap, not conditions)

- Correct CLAUDE.md's "16,191 mods" to "18,570 distinct mod IDs, 13,864 with full published metadata" (§5(c)).
- Record the English-only listing scope as an explicit, documented policy decision.
- Remove or supersede the contradictory `b26_reference_db` key in Phase 2B's `build_metadata`.
- Replace the hardcoded thread-link figures in `report_phase2_comment_evidence_index.py:54` with interpolated values.
- Close the (a) and (b) gaps in a **single** migration — they insert into the same table from the same corpora, and splitting them doubles the validation work.

## Decision (2026-08-05)

**Decision: ADOPT Codex's B26 pipeline**, with the three conditions above (taxonomy
precedence fix, triage precision/recall baseline, explicit `mod_comments` retirement
decision) queued as follow-up work rather than blockers to adoption itself. Jason
accepted this session's recommendation as presented, delegating the call
("proceed with your suggestions") rather than overriding it. Per this plan's scope
boundary, no B26 content-migration work (comment ingestion, evidence-index
promotion) proceeds under this plan — the three conditions and the "also worth
doing" items above become their own follow-up spec.
