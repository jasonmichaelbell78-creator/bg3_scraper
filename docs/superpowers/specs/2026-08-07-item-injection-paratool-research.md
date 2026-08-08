# Item Injection / ParaTool — Deep Research Findings

Full multi-agent research run via the newly-ported `deep-research` skill (see
`docs/superpowers/specs/2026-08-07-phase2-source-research-plan.md`, gap #1,
the highest-priority Blocking finding from
`docs/superpowers/specs/2026-08-07-catalog-gap-report.md`). Raw pipeline
artifacts (findings, challenges, dispute resolutions, claims/sources JSONL)
live in `.research/item-injection-paratool/` (gitignored — see `.gitignore`).
This doc promotes the durable conclusions into the project's tracked record.

## Pipeline summary

4 searcher agents (D1-D4) → 1 orchestrator-run live API verification (D5) →
synthesis → 2 verifier agents (V1/V2, one required a re-spawn after a
truncated first attempt) → contrarian + OTB challenges → dispute resolution
(5 formal disputes) → re-synthesis (v2) → gap-pursuit scan (0 actionable
gaps, skipped) → self-audit. 12 agents total, 34 claims, 51 sources.

## Bottom line

**No ready-made, curated, bulk-extractable compatibility list exists
anywhere for "which mods need ParaTool" — confirmed absent across ParaTool's
own GitHub repo, BG3ModManager's full source, two community wikis, and a
dedicated fan wiki.** This is a genuine, actively-confirmed absence, not an
unsearched gap.

**The premise behind the field needs correction, not just better sourcing.**
ParaTool is not a general "make injected items accessible" tool — it's
narrowly scoped to Ancient Mega Pack (AMP), fixing a specific loot-table
double-roll bug when integrating third-party equipment into AMP's
randomized loot pools. Most equipment mods self-deliver items (baskets,
camp chests, vendors) with zero tool dependency, and a universal fallback
(Script Extender console spawning) exists independent of ParaTool entirely.
Sparse coverage of this field is expected by design, not a data-quality
defect to chase.

**The field name (`paratool_required`) is too narrow even on its own
terms.** A separately-branded sibling tool, "REL Generator" (Nexus mod
8811), does the same job for a related mod (REL). A schema field named
only after ParaTool will systematically miss REL Generator mentions.

**Adversarial review (contrarian challenge) caught two real, zero-cost
misses in the original research pass**, both independently confirmed by
direct DB queries before being accepted:
- A plain `LIKE '%ParaTool%'` / `'%REL Generator%'` scan against the
  already-scraped `mods.description` field (99.5% populated, no new
  scraping) surfaces real hits: 2 for "ParaTool" (including on Ancient
  Mega Pack's own listing), 5 for "REL Generator."
- Ancient Mega Pack (mod_uid 29375) already has 8 real `hard_required`
  reverse-dependents in the `dependencies` table via mod.io's own
  structured API — a structured AMP-ecosystem signal that existed in the
  DB the whole time and was never checked.

**A separate outside-the-box challenge caught that the recommended schema
fix would have been low-value**: a direct grep confirmed `item_injection`
has zero downstream consumers in `app/` today — the loadout-advisor's
`conflict_checker.py`/`dependency_resolver.py` never read it. Recommendation
priority was reordered accordingly.

## Recommendations (priority order)

1. **Before any schema rework, resolve consumption.** Evaluate folding
   `item_injection` into the `evidence_claims`/`evidence_source_records`
   model — the same pattern already used for the `mod_comments` migration
   in B26 Phase 3 — rather than producing a second well-named but
   still-unread column.
2. **Don't hunt for a master list — run the free local scan instead.** The
   `mods.description` LIKE scan for "ParaTool"/"REL Generator" (and any
   newly-identified tool names, e.g. a "FED AIO" lead surfaced during this
   research) is a zero-cost first step against data already in hand.
3. **If a standalone field is still wanted after (1): generalize it**
   (nullable enum: `paratool` / `rel_generator` / `other` / `none`, or
   better, a general "does this description name a required companion
   tool" free-text pattern-match feeding `evidence_claims.target_text`
   directly) — treated as a fallback design, not the primary path.
4. **Treat sparse coverage as expected**, but don't assume uniform
   population-wide sparsity — the 8-mod self-delivery sample skews toward
   popular mods (survivorship-bias caveat), and the loadout-advisor's real
   use case cares about conditional hit rate within a specific candidate
   list, not % of all 19,967 mods.
5. **Pursue Nexus's `tags` GraphQL field as a separate follow-up** — never
   scraped by this project at all (zero Nexus rows in `platform_tags`),
   includes a directly useful "Patch 8 Compatible" tag, but belongs to the
   patch-8/maintenance-status gap (Phase 2 plan gap #5), not this one.
6. **If ever revisited for bulk automation**: the AMP `dependencies`-table
   reverse-lookup (needs official-vs-third-party triage on the 8 rows,
   should also be run against REL's own mod_uid), live-querying Nexus's
   `modRequirements.nexusRequirements` at scale, and self-delivery phrase
   patterns as a negative-signal ("confidently doesn't need this")
   classifier feature.
7. **Cross-workstream**: BG3ModManager's Script-Extender-detection pattern
   (`ScriptExtender/Config.json` presence inside a `.pak`) is a clean,
   reusable, code-verified rule for the separate deployment-type gap
   (Phase 2 plan gap #4) — a serendipitous byproduct of this research, not
   an item-injection finding.

## What's still open (not blocking, tracked for a future pass if revisited)

- Whether `nexusRequirements` ever surfaces REL Generator on real
  REL-dependent mods at scale (untested).
- How broadly Nexus's `tags` field is populated beyond the one spot-checked
  mod.
- Whether ParaTool is bundled as an optional file on AMP's own mod.io/Nexus
  listing rather than solely a standalone GitHub download.
- Reddit megathread/FAQ search — genuinely blocked by tool access
  limitations in this pass (same pattern as the Load Order Guidance
  research; would need `claude-in-chrome` from an unblocked machine).

## Process note for future deep-research runs in this repo

One verifier agent (V2) truncated on its first attempt — a known Windows
agent-output bug the skill's persistence safety net is designed for.
Caught by checking the findings file was actually non-empty (it wasn't)
rather than trusting the returned summary text, then re-spawned once with
a tighter tool-call budget, which succeeded. Worth remembering for future
runs: always verify a findings/challenge file landed on disk before
treating an agent's "done" summary as ground truth.
