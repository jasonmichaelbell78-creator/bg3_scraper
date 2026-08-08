# Phase 2: Source Research Plan (per-gap sourcing strategy)

Per `docs/superpowers/specs/2026-08-07-total-project-plan-to-loadout-advisor.md`,
Phase 2's deliverable is a per-gap sourcing plan — what to check, in what
order, primary vs. corroborating sources — not the mined data itself. Built
against the 8 actionable findings in
`docs/superpowers/specs/2026-08-07-catalog-gap-report.md` (2 Blocking, 6
Significant; the "known-broken/community-patch" and "incompatibility
evidence" pair get combined below where their sourcing overlaps).

**Updated 2026-08-07 (adversarial review)**: the Gap Report this plan is
built on got its own contrarian/OTB challenge pass after item injection's
research demonstrated the value of one. See that report's "Corrections from
adversarial review" section for the full record. Two corrections are
already folded into domains 3 and 4 below. Two more are flagged there but
not yet applied to this plan's priority order: (a) only 3 of 7 domains are
actually read by the loadout-advisor's tested code today (patch-8 status,
known-broken status, incompatibility evidence) — a consumption-weighted
ordering would front-load those over the two Blocking, live-reasoning-only
domains; (b) domains 1 (item injection, done), 2 (load-order), 5, and 6 all
use the identical description/comment-corpus keyword-extraction technique
and may be worth scoping as one shared Phase 3 utility rather than four
separate scripts. Both are sequencing decisions for the project owner, not
applied here.

## Tooling decision (this session)

Ported the `deep-research` skill (multi-agent decompose → parallel search →
confidence-tagged claims → verify → contrarian/OTB challenge → synthesis
pipeline) from the user's JASON-OS/sonash-v0 repos into this repo's own
`.claude/skills/deep-research/` + `.claude/agents/` — not the full
deep-plan/convergence-loop/GSD apparatus around it, which is scaled for
those larger, longer-running projects. Added a new `gaming-modding.yaml`
domain module (`.claude/skills/deep-research/domains/`) since none of the
existing modules (technology/academic/business) fit this project's actual
source landscape — it encodes Nexus/mod.io/official-GitHub as Tier 1,
community wikis/Discord/Reddit as Tier 2, matching this project's own
established sourcing discipline (primary source over paraphrase — see the
BG3ModManager log-path correction and Osiris Log correction already
recorded in CLAUDE.md).

**Important scoping note, found while drafting this plan**: deep-research
answers open research *questions* well (landscape surveys, source
evaluation, methodology). It does not replace the bulk per-mod scraping
scripts this project already relies on (`nexus_bg3_scraper.py`-style). For
gaps where the real work is "verify this signal across thousands of
individual mods," deep-research's job is to answer the *methodology*
question first (where would that signal reliably come from, is it
bulk-extractable) — the actual per-mod extraction is still a Phase 3
scripting task, mirroring this project's existing scraper pattern.

## Per-gap plan

### 1. Item injection + ParaTool (Blocking) — RESEARCHED 2026-08-07

Full `deep-research` run complete (12 agents, 34 claims, 51 sources, 5
disputes formally resolved after a contrarian challenge caught real,
zero-cost misses in the first pass). Findings promoted to
`docs/superpowers/specs/2026-08-07-item-injection-paratool-research.md`.
Bottom line: no master compatibility list exists (confirmed absent, not
unfound); the schema's premise (ParaTool as a general accessibility gate)
was wrong — it's narrowly AMP-specific and optional for most mods; the
field name is too narrow (misses sibling tool "REL Generator"); and,
caught only during adversarial review, `item_injection` currently has zero
downstream consumers in the loadout-advisor code, so schema rework should
wait on resolving that first. Two free, zero-cost signals were found
sitting unused in already-scraped local data (a `mods.description` keyword
scan, an AMP `dependencies`-table reverse-lookup) — see the promoted doc's
Recommendations for the full priority order. This gap is closed for
Phase 2 purposes; any further work on it is Phase 3 (implementation),
not more sourcing research.

<details>
<summary>Original Phase 2 sourcing plan for this gap (superseded by the research above, kept for record)</summary>

**Research question for deep-research**: Does ParaTool (or an equivalent
tool) publish its own compatibility/mod list or detection logic that could
replace the current auto-parsed-description heuristic? Are there other
bulk-extractable per-mod signals (structured Nexus/mod.io category tags,
file-list patterns) that corroborate `paratool_required`?

**Primary sources**: ParaTool's own GitHub repo (README, releases, any
compatibility list/wiki), the tool's own issue tracker (mods reported as
needing/not needing it). **Corroborating**: BG3ModManager source (already
directly read once this session for the log-path finding — check if it has
any equipment-injection detection logic), community wiki pages for
individual popular item-adding mods as spot-checks.

**Not deep-research's job**: re-verifying/extending coverage across the
2,412 already-flagged mods plus the other 87.9% with zero signal — that's a
Phase 3 script once the methodology question above is answered.

**Priority**: 1st (Blocking, and the original triggering finding).

</details>

### 2. Load-order positioning rules (Blocking)

**Research question**: What load-order sourcing exists beyond what Load
Order Guidance v14 already captured that's *per-mod* and *bulk-extractable*
— specifically: does VOLO (the not-yet-public masterlist project found
during the v13 research round) have any accessible data yet; does the BG3
Load Order Optimizer (Nemix3D) expose its ordering data publicly (API,
export, or scrapable page); can KAVT's/LN's/Astra's/Sai's/mod-15851's
divider-mod conventions be mapped to a structured per-mod bucket field.

**Primary sources**: VOLO/BG3 Load Order Optimizer's own
sites/repos/Discords (re-check status — v13 found VOLO "not yet public" in
2026-08-06, may have changed). **Corroborating**: the `load_order_hints`
table's own 654 existing rows as a seed pattern, comment corpus (already
scraped, 527,928 rows) mined for load-order keyword mentions as a
free/local corroborating source before any new external research.

**Priority**: 2nd (Blocking).

### 3. Shared-table/override conflicts (Significant) — REFRAMED 2026-08-07

**Superseded by adversarial review**: an adversarial pass against the Gap
Report (see `docs/superpowers/specs/2026-08-07-catalog-gap-report.md`'s
"Corrections from adversarial review" section) found this domain is NOT a
"zero representation, need to find external sourcing" problem as originally
framed below. `evidence_claims.claim_text` already has 14 real, on-topic
rows describing exactly this conflict pattern (e.g. two mods both
overriding the same progression entry, load order deciding the winner),
captured under existing `claim_type` values but not tagged as their own
category. **This is a review/tagging task against data already captured,
not a from-scratch sourcing question** — no external research needed to
start. It's also plausibly the same underlying gap as domain 7
(incompatibility-evidence review) wearing a different name: a
compatibility-patch page describing a table conflict already produces
exactly the kind of `evidence_claims` row `conflict_checker.py` already
knows how to surface via `evidence_to_review`.

**Revised approach**: fold this into domain 7's evidence-mining/review work
rather than scoping it as an independent sourcing effort. If new external
sourcing is still wanted after mining the existing 14+ rows (e.g. to find
compatibility-patch pages that were never scraped as comments/descriptions
at all), the original research question below remains a valid fallback, just
demoted to a secondary step, not the primary path.

<details>
<summary>Original Phase 2 sourcing plan for this gap (superseded by the review above, kept for record)</summary>

**Research question**: Does any existing community resource document,
per-mod or per-mod-pair, which LSX tables (`Progressions`,
`ClassDescriptions`, `SpellLists`, `CharacterVisuals`) a mod edits? This is
a landscape question first — the Gap Report confirmed zero DB
representation, but it's not yet confirmed whether the *underlying data*
exists anywhere in scrapable form at all, vs. only ever existing as
one-off compatibility-patch READMEs.

**Primary sources**: `wiki.bg3.community`/`bg3.wiki` compatibility pages,
Norbyte's Toolkit/LSLib docs (for whether table-editing is
introspectable from a mod's own files without downloading/parsing every
`.pak`), known compatibility-patch mod pages (these often state "patches
mod X and mod Y's shared entry in table Z" directly).

**If the answer is "no bulk-extractable source exists"**: the honest
fallback, already partly built into the loadout-advisor design, is
live per-candidate-list reasoning grounded in the Load Order Guidance
doc's general override rule — not a structured DB field. Worth deep-research
settling this explicitly rather than assuming either way.

</details>

**Priority**: unchanged position for now (3rd), but scope changed from
"external sourcing" to "mine/review existing `evidence_claims` content
first" — see domain 7 below, which this likely merges into.

### 4. Deployment type (Significant)

**Local-data check done this session**: confirmed `platform_file_records`
only has outer download archives (106,783 rows, 99.4% of listings have at
least one file record) — the DB cannot answer this from data already
scraped; the archives would need to be downloaded and unpacked to inspect
contents directly, a materially bigger undertaking than this project's
existing metadata-only scraping. *Corrected 2026-08-07 (adversarial review
of the Gap Report)*: a broader `LIKE '%.pak%'` sweep (vs. the original
exact-suffix check) does find `.pak` substrings in 229 filenames / 79
distinct mods — still a weak, non-representative signal (most filenames are
opaque hashed zip wrappers), but not literally zero. Doesn't change the
"needs real inspection, not a one-line query" conclusion.

**Research question for deep-research**: Is there a reliable *external*
signal short of downloading every archive — e.g., does Nexus's or mod.io's
own file-listing UI expose a file-type tag; do author-written install
instructions in mod descriptions follow a detectable pattern
("extract to X" vs "drop the .pak in Y" vs "requires Script Extender")
that's bulk-parseable the same way `item_injection`'s description-parsing
already works.

**Primary sources**: Nexus/mod.io file-page HTML structure (check for a
file-type/category field via their APIs, not yet checked this session),
BG3ModManager's own source (may already classify install types for its own
UI — worth checking directly, matching how its log path was found this
session).

**Priority**: 4th (Significant; may turn out to need the heavier
archive-download approach, which would be its own scoping decision, not
assumed here).

### 5. Patch-8 / maintenance status (Significant)

**Research question**: What's the most reliable *bulk* signal for
"still works on the current patch" — `platform_listings.last_updated`
cross-referenced against patch release dates, explicit author statements,
or community-reported breakage?

**Primary sources — mine what's already scraped first, zero new
external research needed for this piece**: the comment corpus
(527,928 rows) and mod descriptions already in the DB, keyword-searched for
patch-number mentions and "broken"/"not working"/"abandoned" language. This
is a local script task, not deep-research.

**Corroborating, needs research**: does Nexus display any own "last tested
against version" field community members rely on; are there known
patch-8-specific compatibility megathreads (Reddit/Discord) worth mining
the same way the Load Order Guidance v13 research already did.

**Priority**: 5th (Significant; cheapest of the six since half the work
is local mining of data already in hand).

### 6. Known-broken / community-patch status (Significant)

**Same sourcing shape as #5** — extend `risk_flags`'s existing narrow
categories (`level_cap_stack`, `legacy_ModFixer`, `subclass_no_CF`,
`lockpick_trap_crash_reports`) by mining the comment corpus for
crash/broken-report language first (local, free), then research whether
Discord/Reddit have any structured "known issues" tracking beyond
individual comment threads (a curated list would be far more efficient
than per-mod comment mining alone).

**Priority**: 6th (Significant; overlaps enough with #5 that both should
probably be scoped as one combined Phase 3 script — comment-corpus mining
for maintenance-status *and* known-broken signal in a single pass, since
both read the same source data).

### 7. Incompatibility evidence review backlog (Significant — not a sourcing task)

**Not a deep-research candidate.** 3,171 of 3,184 `incompatibility`
evidence claims are already captured (`claim_state='proposed'`) — this is
an internal review/promotion task against data already in the DB
(`evidence_claims` + `evidence_claim_links` + `evidence_source_records`),
not new external sourcing. Flagged here only to confirm it's excluded from
this plan and needs its own review pass (manual or scripted against the
already-captured evidence) when Phase 3 is scheduled.

### 8. `mod_classifications` documentation correction

Already fixed directly in `docs/superpowers/specs/2026-08-07-loadout-advisor-design.md`
this session. No further action.

## Sequencing and environment flags

Priority order: **1 (item injection) → 2 (load order) → 3 (shared-table) →
4 (deployment type) → 5+6 combined (maintenance/broken status, local-first)
→ 7 (evidence review, separate track, not blocked by the above)**.

**Environment dependency, known in advance**: gaps #2 and #3 in particular
plausibly need real Discord/community-wiki browser access
(`claude-in-chrome`), which has been environment-blocked on the work
machine before (same constraint the Load Order Guidance v12→v13 handoff
hit). Should be run from home if this session's environment can't reach a
given source — check early per-gap rather than discovering it mid-research.

## Next step

Run `deep-research` for gap #1 (item injection/ParaTool) first, since it's
the highest-priority Blocking gap and the original trigger for this whole
plan. Depth L1 (Exhaustive) per the skill's floor — no shallow mode.
