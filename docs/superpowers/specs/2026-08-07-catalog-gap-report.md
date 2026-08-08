# Catalog Gap Report — Phase 1 (Reference Catalog Completeness → Loadout Advisor)

## Scope and method

Executed per `docs/superpowers/specs/2026-08-07-total-project-plan-to-loadout-advisor.md`
Phase 1: pure SQL audit against the local candidate DB, no new data collection.
Query: `catalog/B26/BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db`
(read-only), synced fresh from the `effective-garbanzo` Codespace immediately
before this audit so it reflects the real post-Phase-4 state (all 5
`migration_history` rows present; `mod_comments` correctly at 76,043 modio +
451,885 nexus; `catalog_collection_comments` present with 5,122 rows) — the
local copy on this machine had been stale (stuck at Phase 3) before the sync.

Base counts: **19,967 mods** (`mods` table; 125 are `is_stub=1`, ~0.6%,
immaterial to any percentage below), **19,967 platform listings**
(8,158 mod.io + 11,809 Nexus).

A gap only counts against the loadout advisor if it's load-bearing for one of
its three jobs: **recommend** mods for a described playthrough, **build**
a working load order, **troubleshoot** problems during play. Severity is
blocking / significant / minor / not-a-gap, based on how often the advisor
would plausibly have to guess or live-search without the data.

## Corrections from adversarial review (2026-08-07)

This report was originally produced single-pass, no independent verification
— the same way the item-injection domain's own first-pass research was, before
a contrarian/OTB challenge caught real misses there (see
`docs/superpowers/specs/2026-08-07-item-injection-paratool-research.md`).
Applying that same lesson, this report got its own first adversarial review
(contrarian + OTB challengers, standalone pass against
`.research/phase1-gap-report-review/challenges/`, not a full deep-research
re-run). Two confirmed-real corrections and two flagged-for-decision findings
came out of it; both challenge files are the full record.

**Confirmed and applied below**:
1. **Shared-table/override conflicts was NOT "zero representation"** — the
   original schema-DDL search never swept row *content*. A direct query
   independently re-run twice (contrarian + orchestrator) found 14 real,
   on-topic `evidence_claims.claim_text` rows already describing exactly this
   conflict pattern (e.g. *"Druid 2024 Level 2 Subclasses' author states that
   it and a feats-every-even-level mod both override progressions, with the
   lower-loaded mod winning"*), sitting uncategorized under existing
   `claim_type` values (`compatibility`/`incompatibility`/`load_order`/
   `dependency_requirement`). This is the same "schema search ≠ content
   search" blind spot the item-injection research already caught once,
   reproduced in this document.
2. **Deployment type's proxy search omitted `platform_file_records`** — a
   table already covering 19,854/19,967 mods (99.4%) that the original pass
   never checked or ruled out. The practical signal turns out to be weak
   (only 229/19,967 mods have `.pak` in the *outer* archive filename — most
   stored filenames are opaque hashed zip wrappers, not unpacked contents),
   so this isn't a ready zero-cost win, but the report's "only proxy is
   [a 263-mod classification term]" framing was incomplete, not just modest.

**Flagged for an explicit decision, not silently applied**:
3. **Severity doesn't track code-consumption.** Cross-checking each domain
   against what the loadout-advisor design's two tested functions
   (`dependency_resolver.py`, `conflict_checker.py`) actually query: only 3
   of 7 actionable domains (patch-8 status, known-broken status,
   incompatibility evidence — all via `risk_flags`/`evidence_claims`) are
   genuinely read by tested code. Both Blocking domains (item injection,
   load-order positioning) and 2 of 6 Significant (shared-table conflicts,
   deployment type) are never read by any planned function — exactly the
   category the design's own YAGNI section says should stay live-reasoned.
   This doesn't overturn the original "jobs served" severity definition, but
   it's a materially different axis worth weighing before Phase 2 locks
   priority order.
4. **Shared-table conflicts may not be a separate domain at all** — per
   correction 1 above, a compatibility-patch page describing a table-override
   conflict *is* an incompatibility claim; it doesn't need its own
   table/column, just capture as one more `evidence_claims` row. This domain
   and the incompatibility-evidence-review backlog (domain 7) are plausibly
   the same underlying gap under two names.

Points 3-4 are **not applied to the table/severity labels below** — that's a
priority-sequencing call for the project owner, not a factual correction, and
is being raised separately rather than silently baked in.

## Summary table

| Domain | Jobs served | Coverage found | Severity | Code-consumed today? |
|---|---|---|---|---|
| Item/equipment injection + ParaTool | recommend, build | 2,412/19,967 (12.1%) mods have any signal; of those, 87.3% is unverified auto-parsed description text. **Researched 2026-08-07** — see the promoted research doc; premise was wrong (ParaTool is narrowly AMP-specific, not a general accessibility gate), field name too narrow, no master list exists | **Blocking** | No (confirmed zero consumers in `app/`) |
| Load-order positioning rules | build | 654 hints / 612 mods (3.1%), single-sourced from description text; 2,538 `load_order` evidence claims, 99.6% still `proposed` (unreviewed) | **Blocking** — flagged for reconsideration, see corrections above | No (`load_order_hints` is YAGNI-listed as a live-reasoning input, never read by a tested function) |
| Shared-table/override conflicts (Progressions/ClassDescriptions/SpellLists/CharacterVisuals) | build, troubleshoot | **Corrected 2026-08-07**: not zero — 14 real `evidence_claims.claim_text` rows already describe this conflict pattern, uncategorized under other `claim_type` values. Likely the same underlying gap as "Incompatibilities/conflicts" below, not a separate one — see corrections above | Significant (flagged: may fold into Incompatibilities/conflicts) | No |
| Deployment type (PAK/MOD FIXER/LOOSE FILES/NATIVE/MANUAL/SCRIPT EXTENDER) | build, troubleshoot | Zero dedicated representation; classification term `requires-script-extender` (263 mods, capped by 18.3% classification coverage) plus, **noted 2026-08-07**, `platform_file_records` (99.4% mod coverage) was omitted from the original proxy search — checked now, practical signal is weak (only 229/19,967 mods show `.pak` in the outer archive filename) but the table itself should have been surfaced and ruled out explicitly | Significant | No |
| Patch-8 compatibility / maintenance status | recommend, troubleshoot | `risk_flags` category `not_maintained`: 131/19,967 (0.7%) | Significant | **Yes** — `risk_flags` returned directly by `conflict_checker.py` |
| Known-broken / needs-community-patch status | recommend | `risk_flags` other categories: 311 rows / 302 mods (1.5%), narrow ad hoc category set | Significant | **Yes** — same `risk_flags` table |
| Incompatibilities/conflicts | recommend, troubleshoot | 3,184 `incompatibility` evidence claims, but 99.6% still `proposed` (unreviewed); free-text target, not FK — already designed around (surfaced, not asserted) | Significant | **Yes** — `evidence_claims` returned via `conflict_checker.py`'s `evidence_to_review` |
| **Correction**: `mod_classifications` real coverage | recommend | Distinct mods classified is **3,649/19,967 (18.3%)**, not the "8,249 (~41%)" the loadout-advisor design cites — 8,249 is the *row* count (multi-term mods), not mod count | Significant (doc-fix) | No (thematic search is live-reasoning-only, YAGNI) |
| NSFW/nudity-toggle interaction | recommend | `adult-content`+`adult-content-addon` classification terms: 86 mods flagged (bounded by 18.3% classification ceiling); separately, 205 Nexus mods have `nsfw_gated` comment-capture evidence, not cross-linked structurally | Minor | No |
| Companion/class/race-specific special handling | recommend, troubleshoot | No dedicated flag; thematic classification terms exist (`affects-companions` 278, `affects-classes` 431, `affects-races` 110, `companion-ai-behavior` 7, `companion-interaction` 42), same 18.3% ceiling; `catalog_browse_labels` (100%) already the designed fallback | Minor | No |
| Author-declared framework exceptions | build | Zero structural representation; narrow edge case, likely caught case-by-case in dependency/claim free text when relevant | Minor | No |
| Comment/evidence qualitative color | recommend, troubleshoot | `mod_comments`: 527,928 rows / 7,757 distinct listings (38.9%) — naturally tracks popularity, which correlates with what gets recommended. `catalog_collection_comments`: 5,122 rows / 85 of 930 collections (9.1%), secondary signal | Minor | No |
| Dependencies (required/optional/external-tool) | build, troubleshoot | 10,851 rows / 6,332 distinct mods (31.7%), clean FK-based, typed (`hard_required`/`external_tool`/`conditional`/`optional_recommended`), `dependency_closure` walks transitively (4,789 mods) | Not a gap | Yes |
| Thematic/browse classification (coarse) | recommend | `catalog_browse_labels`: 19,967/19,967 (100%) | Not a gap | No (live-reasoning) |
| Popularity/quality signal | recommend | `mod_rank` 19,842/19,967 (99.4%); `endorsements_or_downloads` populated 19,916/19,967 (99.7%) | Not a gap | No (live-reasoning) |
| Curated bundles as recommendation seeds | recommend | 930 collections (843 modio + 87 nexus), 49,907 memberships, 98% resolved to a `listing_uuid` | Not a gap | No (live-reasoning) |
| Technical log-reading knowledge | troubleshoot | Confirmed zero DB representation (checked schema directly — no log/troubleshoot/diagnostic table). By design: lives in Load Order Guidance doc v14 §1.1, not meant to be DB data | Not a gap (already resolved via doc) | N/A (doc, not DB) |

## Detail per domain

### Blocking

**Item/equipment injection + ParaTool.** Confirms the original triggering
finding exactly. 2,412 mods (12.1% of 19,967) have any `item_injection` row
at all — the other 87.9% have zero signal on whether their added items are
even reachable in-game without a third-party tool. Of the 2,412 that do have
a row, `item_info_source` breaks down: `description_parsed` 2,105 (87.3%,
auto-parsed, unverified), `description_parsed_ambiguous` 204 (8.5%,
explicitly flagged uncertain), and only 27 rows (1.1%) `web_verified*`. So
even the already-thin 12% slice is ~96% unverified. `paratool_required=1`
on 1,986 of those 2,412 rows — meaning for the majority of mods that *do*
add items, the catalog can't yet say with confidence whether ParaTool (or
similar) is actually needed, which is exactly the kind of thing the advisor
would otherwise have to guess or live-search per mod.

**Load-order positioning rules.** Two signals, both thin. `load_order_hints`:
654 rows covering only 612 distinct mods (3.1%), and 100% of them sourced
from parsing the mod's own description text (`source='description'` for all
654 rows) — no cross-validation source. Confidence is self-reported as
`medium` for 651/654 rows. Separately, `evidence_claims` with
`claim_type='load_order'`: 2,538 claims, but 2,529 (99.6%) are still
`proposed` — i.e. captured but not reviewed/promoted. The Load Order
Guidance doc covers *general* mechanics well (override rule, KAVT bucket
rule, divider-mod conventions), but per-mod-pair positioning data in the DB
itself is thin relative to 19,967 mods — the advisor would frequently have
nothing structured to check for a specific candidate pair.

*Flagged 2026-08-07*: `load_order_hints` is never read by either of the
loadout-advisor's tested functions — the design's own YAGNI section lists
load-order construction as explicitly live-reasoning-only, the same
consumption profile as several domains ranked Significant or lower in this
report. Whether "Blocking" is still the right word given that, versus
"Significant," is an open question for the project owner, not resolved
here — 654 hints across 19,967 mods is thin and worth improving regardless
of the label.

### Significant

**Shared-table/override conflicts.** *Corrected 2026-08-07 — see "Corrections
from adversarial review" above.* The original pass searched the full schema
(all table and column definitions) for anything resembling a per-mod flag for
editing shared game tables (`Progressions`, `ClassDescriptions`, `SpellLists`,
`CharacterVisuals`) — zero hits there, confirmed again on re-check. That part
holds: there is genuinely no dedicated table/column. But a schema search only
checks structure, not content, and this project's `evidence_claims` table
already has real, human-legible free-text rows describing exactly this
conflict class — e.g. *"Book of Druids - 5e Druid Subclasses' author states
that it and Feats on Even Levels overwrite the same progressions, with the
load-order result determining [which wins]"* — captured under existing
`claim_type` values (`compatibility`/`incompatibility`/`load_order`/
`dependency_requirement`), just not tagged with a dedicated category. 14 such
rows were found via a direct `LIKE` sweep of `claim_text` for
override/conflict/progression language. The corrected framing: "no dedicated
field, but real evidence already exists uncategorized" — a review/tagging
task against data already captured, not a from-scratch sourcing gap. Whether
this stays its own domain or folds into "Incompatibilities/conflicts" below
(they'd use the same `conflict_checker.py` consumption path and the same
free-text-target-resolution problem) is flagged as an open sequencing
question, not resolved here.

**Deployment type.** No dedicated column or table for PAK / MOD FIXER /
LOOSE FILES / NATIVE / MANUAL / SCRIPT EXTENDER classification. The
classification term `requires-script-extender` (263 mods) is one proxy,
itself bounded by the 18.3% overall classification coverage. *Noted
2026-08-07*: the original pass didn't check `platform_file_records`
(19,854/19,967 mods, 99.4% coverage, includes `file_name`/`size_bytes`/
`version_text`) before writing "only proxy is [the classification term]" —
checked now, and the practical signal is weak: only 229 rows / 79 distinct
mods have `.pak` anywhere in the stored filename, because most stored
filenames are the *outer* distributed archive (`something_hash.zip`), not
the unpacked internal contents. So this isn't a ready zero-cost win the way
item-injection's description scan was — but the table should have been
surfaced and explicitly ruled out rather than omitted, and a real (not
one-line) inspection pass (e.g. sampling whether `size_bytes`/`version_text`
correlate with known PAK-vs-loose-files mods) is worth scoping into Phase 2
before assuming new external scraping/browsing is required. This matters for
both build order (install sequencing differs by deployment type) and
troubleshooting (wrong assumption about how a mod is installed is a common
support question per the Load Order Guidance doc's own triage table).

**Patch-8 compatibility / maintenance status.** `risk_flags` category
`not_maintained` covers only 131 mods (0.7% of 19,967) — implausibly low
given how much a major patch typically breaks across an active mod
ecosystem this size. This is exactly the "is this still safe to use"
question the advisor needs pre-answered to avoid live-searching per
candidate mod.

**Known-broken / needs-community-patch status.** `risk_flags`'s other four
categories (`level_cap_stack` 127, `legacy_ModFixer` 31, `subclass_no_CF`
21, `lockpick_trap_crash_reports` 1 — 311 rows / 302 mods, 1.5%) read as a
narrow, reactively-built set tied to specific known issues rather than a
general "is this mod broken" taxonomy. Real signal where it exists, but far
from comprehensive.

**Incompatibilities/conflicts.** 3,184 `incompatibility`-type evidence
claims exist, which sounds substantial, but 3,171 of them (99.6%) are still
`claim_state='proposed'` — captured from source text, not reviewed or
promoted. Only 11 are `reviewed_supported`. Claims also target a mod by
free-text `target_text`, not a foreign key, so resolving "does this claim
apply to one of my candidate mods" is a fuzzy-matching problem, not a join.
**This is already designed around**: `conflict_checker.py`'s
`evidence_to_review` return value in the loadout-advisor design exists
specifically to surface this kind of unverified signal for a human/Claude
to read rather than assert a false verdict. Flagged here as significant
context, not a new design gap. *Cross-reference, 2026-08-07*: see the
Shared-table/override conflicts entry above — that domain's evidence is
plausibly capturable as more rows here rather than a separate mechanism.

**Documentation correction: `mod_classifications` coverage.** The
loadout-advisor design's own "Known limitation" section states
`mod_classifications` covers "8,249 of 19,967 mods (~41%)". Direct query
shows 8,249 is the **row count** (`SELECT COUNT(*) FROM
mod_classifications`) — mods can carry multiple classification terms. The
actual **distinct-mod** coverage is `SELECT COUNT(DISTINCT mod_uuid) ...` =
**3,649 (18.3%)**, less than half the previously-stated figure. This
doesn't change the design's own conclusion (`catalog_browse_labels` at 100%
was already correctly identified as the more reliable fallback) but the
number itself should be corrected in
`docs/superpowers/specs/2026-08-07-loadout-advisor-design.md` before that
design is resumed, so nobody plans against the wrong figure later.

### Minor

**NSFW/nudity-toggle interaction.** Better covered than the plan's starting
list assumed ("not a structural per-mod flag") — `adult-content` (72) and
`adult-content-addon` (14) classification terms exist, covering 86 mods
directly. Separately, the 205 Nexus mods captured via `nsfw_gated` comment
evidence (documented in CLAUDE.md's NSFW section) are a real but
structurally uncorrelated signal — not joined to the classification terms.
Narrow use case (relevant mainly when a playthrough explicitly wants or
wants to avoid adult content), so minor rather than significant.

**Companion/class/race-specific special handling.** No dedicated
"special handling" flag, but thematic classification terms give partial
recommend-job signal (`affects-companions` 278, `affects-classes` 431,
`affects-races` 110, plus narrower `companion-ai-behavior`/
`companion-interaction` terms), bounded by the same 18.3% ceiling. The
loadout-advisor design already plans to fall back on `catalog_browse_labels`
(100% coverage) when classification data is thin, so this isn't an
undesigned-for gap — flagged minor mainly to confirm the fallback plan is
sound in practice.

**Author-declared framework exceptions.** Zero structural representation
(e.g., "don't declare Compatibility Framework as a dependency" as an
author's stated exception to a general rule). Genuinely rare/narrow edge
case; likely surfaces in dependency or evidence-claim free text on the
individual mods where it applies rather than needing its own table.

**Comment/evidence qualitative color.** `mod_comments` (post-Phase-4 fix)
covers 7,757 of 19,967 listings (38.9%) with real comment text — thin in
absolute mod-count terms, but comments naturally cluster on popular mods,
which are also the ones most likely to be recommended in the first place,
so the coverage gap correlates with lower practical impact.
`catalog_collection_comments` (5,122 rows across 85/930 collections, 9.1%)
is a secondary signal on top of that. Not flagged higher because this is an
inherent long-tail limitation, not a fixable data gap the same way
item-injection or load-order-hints are.

### Not a gap

Dependencies, coarse thematic/browse classification, popularity/quality
signal, and curated bundles are all well covered (see summary table) and
need no further work. Technical log-reading knowledge has zero DB
representation, confirmed directly, but that's correct **by design** — it's
meant to live in the Load Order Guidance doc (v14 §1.1 covers it), not the
structured catalog.

## What this means for Phase 2

Per the total-project-plan's original ranking rule, **Phase 2 (Source
Research)** was scoped to prioritize the two Blocking domains first (item
injection/ParaTool, load-order positioning rules), then the Significant list.
Item injection is now researched (2026-08-07). The adversarial review above
surfaces three considerations for how the *rest* of Phase 2 should actually
be sequenced, presented here as findings for the project owner's call, not
silently applied:

1. **A consumption-weighted alternative ordering exists.** Only 3 of the 7
   actionable domains (patch-8 status, known-broken status, incompatibility
   evidence) are read by the loadout-advisor's tested functions today; the
   other 4 (item injection, load-order, shared-table conflicts, deployment
   type) are live-reasoning-only per the design's own YAGNI section. If the
   goal is "make the tested code trustworthy first," those 3 domains warrant
   earlier priority than their "Significant" label alone implies. If the
   goal is "make every advisor conversation better, including live
   reasoning," the original ordering (severity-by-advisor-job) still holds.
   Both are legitimate goals — this report doesn't pick one.
2. **Shared-table conflicts and incompatibility-evidence review are plausibly
   the same underlying work.** Folding gap 3 into gap 7 (mine
   compatibility-patch pages into `evidence_claims` rows, review the backlog
   that already exists) would avoid scoping a second table/column that
   duplicates what `evidence_claims` already does.
3. **Item injection, load-order-hints, patch-8-status, and known-broken-status
   all use the identical technique** (keyword/pattern extraction over
   `mods.description` and `mod_comments`, emitting structured claims). The
   Phase 2 source-research plan already independently noticed part of this
   (merging domains 5+6), but stops short of unifying all four. Worth scoping
   Phase 3 as one shared description/comment-mining utility with multiple
   keyword dictionaries, rather than four separately-built scripts.
4. **Patch-8/maintenance-status has a staleness risk the flat list doesn't
   price in** — a new BG3 patch can invalidate "last known good" data the
   moment it ships, and because this domain *is* code-consumed
   (`conflict_checker.py` reads `risk_flags` directly), a stale, wrongly
   populated row is a worse failure mode than an empty one (nothing today
   distinguishes "checked recently" from "checked six patches ago"). Worth
   either sequencing this domain deliberately last, or designing it from the
   start as a refreshable pass with a `checked_as_of` provenance field,
   rather than a one-time completed artifact.

The Minor items and the `mod_classifications` documentation correction still
don't need dedicated sourcing work — the doc-fix has already been applied
directly to the loadout-advisor design doc.

As already flagged in the total-project-plan doc: several of the
higher-value sources for the remaining Blocking/Significant gaps (Nexus
Collections community discussion, Discord servers, mod-author
changelogs/README pages requiring real browsing) plausibly need genuine
browser access (`claude-in-chrome`), which is environment-dependent the same
way the Load Order Guidance research was — worth checkpointing Phase 2's
sourcing plan the same way v12→v13 was handed off between machines if this
session's environment can't reach a given source.
