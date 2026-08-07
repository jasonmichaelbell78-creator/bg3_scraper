# Total Project Plan: Reference Catalog Completeness → Loadout Advisor — Design

## Goal

Get from the current state (a reference catalog that's complete for its originally-defined scope, plus a paused conversational loadout-advisor design) to the actual final deliverable: a conversational process where the user describes a playthrough, Claude recommends mods, builds a load order, and helps troubleshoot — all grounded in the catalog, with as little live web lookup as possible during that conversation.

**The triggering realization (2026-08-07)**: the catalog's own defined scope was never actually validated against what a real loadout-advisor conversation needs. The ParaTool/item-injection discovery is the proof — a real, load-bearing gap (only ~12% of mods reviewed for whether they need a third-party tool to make their items accessible, and most of that 12% is unverified auto-parsed text) that nobody had checked for, because nothing prompted checking for it specifically. There is no reason to believe it's the only one.

## Guiding principle

**Minimize what has to be looked up live, during an actual advisor conversation.** This reframes "is the catalog complete" away from "does it cover its originally-scoped tables well" (already true — see `Google Drive/00_READ_ME.md`'s own "complete for its defined reference-data scope" claim) and toward "does it cover what the advisor's three jobs actually need." Those jobs, unchanged from the loadout-advisor design:

1. Recommend mods for a described playthrough.
2. Build a working load order for the chosen mods.
3. Troubleshoot problems that come up during play.

A gap only counts if it's load-bearing for one of these three. This is deliberately not "make the catalog maximally comprehensive" — that's the same overcomplication this project has been steered away from before.

## The four phases

Only Phase 1 is planned in full detail here. Phases 2-4 are planned at a methodology level — their specifics depend on Phase 1's actual findings (Phase 2/3) or on the loadout-advisor spec already written (Phase 4, already fully speced, just paused).

---

## Phase 1: Gap Analysis (planned in full, executable now — no network/scraping required)

Pure SQL against the local candidate DB (`catalog/B26/BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db`, read-only) plus reasoning grounded in the Load Order Guidance doc's own findings. No new data collection in this phase — it's an audit of what's already there.

### Step 1.1: Build the domain list

A domain is one category of "thing the advisor needs to know about a mod or the catalog as a whole." Seeded from two sources: the Load Order Guidance doc's own section structure (it already enumerates, from real research, the categories that actually matter for building/troubleshooting a modlist), and this project's own existing table inventory (to catch domains that already have partial coverage worth checking, like `item_injection` did).

Starting list (to be refined, not treated as final, during Step 1.2 — some of these may turn out to already be well-covered, some may split into finer sub-domains):

| Domain | Advisor job it serves | Known DB representation |
|---|---|---|
| Dependencies (required/optional/external-tool) | build order, troubleshoot | `dependencies`, `dependency_closure` |
| Incompatibilities/conflicts | recommend, troubleshoot | `evidence_claims` (claim_type='incompatibility', free-text target, mixed confidence) |
| Load-order positioning rules (tier, "load last", divider conventions) | build order | `load_order_hints` (654 rows — thin relative to 19,967 mods), `evidence_claims` (claim_type='load_order') |
| Shared-table/override conflicts (`Progressions`, `ClassDescriptions`, `SpellLists`, `CharacterVisuals`) | build order, troubleshoot | unknown — not confirmed to exist as a per-mod flag anywhere; likely only in Guidance-doc prose |
| Item/equipment injection + ParaTool requirement | recommend, build order | `item_injection` (~12% coverage, mostly unverified) |
| Mod deployment type (PAK / MOD FIXER / LOOSE FILES / NATIVE / MANUAL / SCRIPT EXTENDER) | build order, troubleshoot | unknown — not confirmed to exist per-mod |
| Patch-8 compatibility / maintenance status | recommend, troubleshoot | `risk_flags` (`not_maintained`, 131 rows — thin) |
| Known-broken / needs-community-patch status | recommend | `risk_flags` (partial overlap with `not_maintained`?), otherwise only Guidance-doc prose |
| NSFW/nudity-toggle interaction | recommend | comments corpus has NSFW-gated capture; not a structural per-mod flag |
| Companion/class/race-specific special handling | recommend, troubleshoot | unknown |
| Author-declared framework exceptions (e.g. "don't declare CF as a dependency") | build order | not tracked structurally, Guidance-doc prose only |
| Thematic/browse classification | recommend | `catalog_browse_labels` (100%), `mod_classifications` (~41%) |
| Popularity/quality signal | recommend | `mod_rank`, `platform_listings.endorsements_or_downloads` |
| Curated bundles as recommendation seeds | recommend | `catalog_collections`, `catalog_collection_memberships` |
| Comment/evidence qualitative color | recommend, troubleshoot | `mod_comments` (via evidence view), `catalog_collection_comments` |
| Technical log-reading knowledge | troubleshoot | not DB data — lives in the Load Order Guidance doc itself (§1.1, v14) |

### Step 1.2: Audit each domain

For each domain with a known DB representation, run the same style of query used for `item_injection`:
- Row count vs. total mod count (`19,967`), or vs. the correct narrower denominator when the domain doesn't apply to every mod (established this session: get this denominator right, don't just divide by 19,967 blindly — the ParaTool conversation's own correction applies generally).
- Confidence/provenance breakdown where the table has an equivalent field (`item_info_source`-style columns, `claim_state`, `evidence_state`).
- For domains with *no* known DB representation: confirm via schema search (`sqlite_master` table list, column search across tables) that no table actually covers it before concluding it's a true gap — don't assume absence without checking, the way `item_injection`'s existence was nearly missed.

### Step 1.3: Produce the Gap Report

A single markdown document, one entry per domain, each with: current coverage/confidence (or "no representation found"), which of the three advisor jobs it's load-bearing for, and a severity ranking (blocking / significant / minor) based on how often the advisor would plausibly need to guess or live-search without it. Save to `docs/superpowers/specs/YYYY-MM-DD-catalog-gap-report.md` at execution time (dated then, not now, since the audit itself hasn't run yet).

**Phase 1 deliverable**: the Gap Report. Nothing else changes — no new scraping, no DB writes, no code beyond the audit queries themselves (which don't need to be committed as a script; ad hoc `sqlite3` queries, same as this session's own audits, are sufficient and match this project's established practice).

---

## Phase 2: Source Research per gap (methodology now, specifics after Phase 1)

For each domain the Gap Report ranks as blocking or significant: determine where authoritative data would actually come from, using this project's established sourcing rigor (primary source preferred over paraphrase, confidence tracked, corrections found and recorded rather than hidden — the same standard the Load Order Guidance doc and today's ParaTool research both followed).

**Known in advance, from today's session**: some sourcing work needs a real browser session (Nexus Collections, Discord communities, anything behind Cloudflare) and is blocked on this machine's environment the same way the Load Order Guidance research was blocked at work through v12 — `claude-in-chrome`'s browser extension tunnels through the local machine regardless of where the Claude session itself runs, unlike `WebSearch`/`WebFetch`/`gh`, which already worked fine in this Codespace today (the ParaTool and BG3ModManager research). **This is the reason for checkpointing and continuing from home** — not because nothing can be done here, but because the highest-value sources for several likely gaps (community-verified equipment-injection data, shared-table conflict per-mod flags, deployment-type data) plausibly need real browser access to Nexus/Discord/community wikis the way ParaTool itself was only found by going straight to source code and issue trackers, not summarized search results.

Output of this phase: a per-gap sourcing plan (what to check, in what order, primary vs. corroborating sources), not yet the mined data itself.

## Phase 3: Deep Mining Execution (methodology now, specifics after Phase 2)

Actual data collection per Phase 2's sourcing plans. Expect this to look like the project's established pattern: research/scraping scripts where the source is API-shaped (mirroring `nexus_bg3_scraper.py`/`modio_deep_comments.py`'s style), direct browser research where it isn't (mirroring the Load Order Guidance doc's own methodology). Anything that writes to the reference catalog DB follows the same discipline every prior phase has: hash-gate before mutating, backup first, TDD tests against fixture DBs, independent post-run verification, a written receipt — the same pattern `claude_phase3`/`claude_phase4` already established. This likely becomes its own numbered phase (`claude_phase5` or similar) once scoped.

## Phase 4: Resume the Loadout Advisor (already speced, paused)

`docs/superpowers/specs/2026-08-07-loadout-advisor-design.md` is complete and correct as written — Approach B (process + tested helpers for dependency-closure resolution and conflict-checking), directory structure, function interfaces (already corrected once against the real schema), loadout document format, testing approach. Once Phase 1-3 close the load-bearing gaps, resume this design's own next step (writing-plans) rather than re-brainstorming it. If a gap turns out to be genuinely unfillable (data that simply doesn't exist anywhere, not just hard to find), the advisor's design already has a place for that: the conflict-checker's `evidence_to_review` surfaces what's known rather than asserting false completeness, and live conversational reasoning was always the fallback for anything the catalog doesn't cover, per the user's own "I just want flexibility."

---

## What happens after this design is approved

Per the user's explicit request: checkpoint session state, commit this design doc, push, and merge — both so the work survives a session boundary and so Phase 2/3's browser-dependent research can continue from home, the same handoff pattern already used successfully for the Load Order Guidance research (blocked at work through v12, completed at home in v13).
