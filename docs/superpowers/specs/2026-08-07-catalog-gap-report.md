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

## Summary table

| Domain | Jobs served | Coverage found | Severity |
|---|---|---|---|
| Item/equipment injection + ParaTool | recommend, build | 2,412/19,967 (12.1%) mods have any signal; of those, 87.3% is unverified auto-parsed description text | **Blocking** |
| Load-order positioning rules | build | 654 hints / 612 mods (3.1%), single-sourced from description text; 2,538 `load_order` evidence claims, 99.6% still `proposed` (unreviewed) | **Blocking** |
| Shared-table/override conflicts (Progressions/ClassDescriptions/SpellLists/CharacterVisuals) | build, troubleshoot | Zero structural representation anywhere in the schema | Significant |
| Deployment type (PAK/MOD FIXER/LOOSE FILES/NATIVE/MANUAL/SCRIPT EXTENDER) | build, troubleshoot | Zero dedicated representation; only proxy is classification term `requires-script-extender` (263 mods, itself capped by 18.3% classification coverage) | Significant |
| Patch-8 compatibility / maintenance status | recommend, troubleshoot | `risk_flags` category `not_maintained`: 131/19,967 (0.7%) | Significant |
| Known-broken / needs-community-patch status | recommend | `risk_flags` other categories: 311 rows / 302 mods (1.5%), narrow ad hoc category set | Significant |
| Incompatibilities/conflicts | recommend, troubleshoot | 3,184 `incompatibility` evidence claims, but 99.6% still `proposed` (unreviewed); free-text target, not FK — already designed around (surfaced, not asserted) | Significant |
| **Correction**: `mod_classifications` real coverage | recommend | Distinct mods classified is **3,649/19,967 (18.3%)**, not the "8,249 (~41%)" the loadout-advisor design cites — 8,249 is the *row* count (multi-term mods), not mod count | Significant (doc-fix) |
| NSFW/nudity-toggle interaction | recommend | `adult-content`+`adult-content-addon` classification terms: 86 mods flagged (bounded by 18.3% classification ceiling); separately, 205 Nexus mods have `nsfw_gated` comment-capture evidence, not cross-linked structurally | Minor |
| Companion/class/race-specific special handling | recommend, troubleshoot | No dedicated flag; thematic classification terms exist (`affects-companions` 278, `affects-classes` 431, `affects-races` 110, `companion-ai-behavior` 7, `companion-interaction` 42), same 18.3% ceiling; `catalog_browse_labels` (100%) already the designed fallback | Minor |
| Author-declared framework exceptions | build | Zero structural representation; narrow edge case, likely caught case-by-case in dependency/claim free text when relevant | Minor |
| Comment/evidence qualitative color | recommend, troubleshoot | `mod_comments`: 527,928 rows / 7,757 distinct listings (38.9%) — naturally tracks popularity, which correlates with what gets recommended. `catalog_collection_comments`: 5,122 rows / 85 of 930 collections (9.1%), secondary signal | Minor |
| Dependencies (required/optional/external-tool) | build, troubleshoot | 10,851 rows / 6,332 distinct mods (31.7%), clean FK-based, typed (`hard_required`/`external_tool`/`conditional`/`optional_recommended`), `dependency_closure` walks transitively (4,789 mods) | Not a gap |
| Thematic/browse classification (coarse) | recommend | `catalog_browse_labels`: 19,967/19,967 (100%) | Not a gap |
| Popularity/quality signal | recommend | `mod_rank` 19,842/19,967 (99.4%); `endorsements_or_downloads` populated 19,916/19,967 (99.7%) | Not a gap |
| Curated bundles as recommendation seeds | recommend | 930 collections (843 modio + 87 nexus), 49,907 memberships, 98% resolved to a `listing_uuid` | Not a gap |
| Technical log-reading knowledge | troubleshoot | Confirmed zero DB representation (checked schema directly — no log/troubleshoot/diagnostic table). By design: lives in Load Order Guidance doc v14 §1.1, not meant to be DB data | Not a gap (already resolved via doc) |

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

### Significant

**Shared-table/override conflicts.** Searched the full schema (all table and
column definitions) for anything resembling a per-mod flag for editing
shared game tables (`Progressions`, `ClassDescriptions`, `SpellLists`,
`CharacterVisuals`) — zero hits. This is a real, confirmed absence, not an
assumption. The general override rule is documented in prose (Load Order
Guidance doc, sourced from Larian's own `#modding-guidelines`), but there's
no machine-checkable way to ask "do these two candidate mods touch the same
table entry."

**Deployment type.** No dedicated column or table for PAK / MOD FIXER /
LOOSE FILES / NATIVE / MANUAL / SCRIPT EXTENDER classification. The only
proxy is the `requires-script-extender` classification term (263 mods),
itself bounded by the 18.3% overall classification coverage. This matters
for both build order (install sequencing differs by deployment type) and
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
context, not a new design gap.

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

Per the total-project-plan's ranking rule, **Phase 2 (Source Research)**
should prioritize the two Blocking domains first (item injection/ParaTool,
load-order positioning rules), then work through the Significant list
(shared-table conflicts, deployment type, patch-8/maintenance status,
known-broken status, incompatibility-claim review backlog). The Minor items
and the `mod_classifications` documentation correction don't need dedicated
sourcing work — the doc-fix should just be applied directly to the
loadout-advisor design doc when Phase 4 resumes.

As already flagged in the total-project-plan doc: several of the
higher-value sources for the Blocking/Significant gaps (Nexus Collections
community discussion, Discord servers, mod-author changelogs/README pages
requiring real browsing) plausibly need genuine browser access
(`claude-in-chrome`), which is environment-dependent the same way the Load
Order Guidance research was — worth checkpointing Phase 2's sourcing plan
the same way v12→v13 was handed off between machines if this session's
environment can't reach a given source.
