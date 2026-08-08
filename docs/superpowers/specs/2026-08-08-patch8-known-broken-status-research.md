# Patch-8/Maintenance Status + Known-Broken Status — Research Findings

Per `docs/superpowers/specs/2026-08-07-phase2-source-research-plan.md` gaps
#5 and #6, picked up in **consumption-weighted order** (user decision,
2026-08-08): these two domains, plus incompatibility-evidence review (#7),
are the 3 of 7 actionable Gap Report domains actually read by the
loadout-advisor's tested code today (`conflict_checker.py` via
`risk_flags`), ahead of the two Blocking-but-unconsumed domains (item
injection, load order).

Both domains' Phase 2 plan already scoped the real work as mostly local
corpus-mining (Phase 3), with a thin "corroborating research" question each.
This doc covers that corroborating research, done as live empirical API
checks rather than a full deep-research pipeline run — the questions were
narrow and directly testable, not landscape surveys.

## Domain 5: Patch-8 / maintenance status — real signal found on BOTH platforms, zero extra scraping cost

**Live-checked 2026-08-08 against both platforms' actual APIs** (not docs,
not summaries). **Self-correction, same day**: this section originally
concluded Nexus had no patch-version tag at all — that was wrong, caught
and fixed within the same research session (see "Correction" below) before
being finalized. Recording the wrong-then-fixed sequence rather than
quietly editing it away, matching this project's established discipline.

- **mod.io `/games/6715/tags`**: a `Type` tag group includes
  **`Patch 8 Tested`**. Queried live via `tags-in=Patch 8 Tested`:
  **3,131 of 8,360 total BG3 mods (37.5%)** carry this tag.
- **Nexus GraphQL — has an equivalent tag, under a different type than
  first checked.** The root `tags(gameId, includeGlobal)` query (returning
  the `Tag` type) really does only have 23 generic genre tags, as first
  found — but that was the wrong field. **Per-mod tags on Nexus use a
  separate, older `LegacyTag` type**, reachable via
  `mod(modId, gameId).tags` or the `legacyTags(gameId)` root query — 177
  total for BG3, distinct from the 23 `Tag`-type ones. This list
  **does include `Patch 8 Compatible`** (id 4739, BG3-specific/non-global).
  Confirmed live via `mods(filter: {gameId, tag: {value: "Patch 8
  Compatible"}})`: **3,787 of 18,850 current Nexus BG3 mods (20.1%)**.
  Caught by directly loading a real mod page (`nexusmods.com/baldursgate3/
  mods/22457`) via `claude-in-chrome` and seeing the tag chip rendered on
  the page — the live page contradicted the earlier API-only finding, which
  is what triggered rechecking the schema and finding the second tag type.
- **Both signals confirmed zero extra scraping cost**: mod.io's `tags` is
  already present in the standard `/games/6715/mods` list response
  (`bg3_scraper.py` already iterates this endpoint) — confirmed via grep,
  zero `tags` handling exists, so the field is silently discarded today.
  **Nexus's `tags` field is also already fetched per mod by
  `nexus_bg3_scraper.py`** — but only used transiently to filter
  non-English mods (`has_non_english_tag()`) and never persisted to output.
  Both platforms: real signal, sitting in already-fetched API responses,
  currently thrown away — the same "unused local signal" pattern as the
  item-injection research's `dependencies`-table finding, just on two
  platforms instead of one.
- Combined, this is meaningfully better than either platform alone: two
  independent, differently-sourced (author/reviewer-applied) signals,
  together covering more of the 19,967-mod catalog than either alone, both
  vastly ahead of the DB's current `risk_flags.not_maintained` coverage
  (131 mods, 0.7%).

**Correction to the item-injection research doc, corrected again**: that
doc's recommendation #5 originally (correctly, as it turns out) said the
tag was on Nexus. An earlier pass of *this* doc incorrectly "corrected" it
to say the tag was mod.io-only — that correction was itself wrong, per the
`LegacyTag` finding above. The truth: **both platforms have a real
Patch-8-compatibility tag**, just under different names and, on Nexus, a
non-obvious second tag type. Doc fixed to reflect this.

**Recommendation**: add `tags` extraction to both `bg3_scraper.py` (mod.io)
and `nexus_bg3_scraper.py` (Nexus, promoting the already-fetched-but-
discarded field to real output) and load both into a `platform_tags`-shaped
table, or fold directly into `risk_flags` as new `patch8_tested`/
`patch8_compatible` categories the same way `not_maintained` already works.
This is a Phase 3 scripting task, not further research.

## Domain 6: Known-broken / community-patch status — no equivalent free signal found

**Checked both platforms for an analogous zero-cost tag/field, found
nothing**:
- mod.io's full BG3 tag list (9 groups, checked live above) has no
  "broken"/"outdated"/"needs patch" tag — `Patch 8 Tested` is the closest
  thing and it's an affirmative signal (author/reviewer marked it working),
  not a negative one.
- mod.io's per-mod object fields (`status`, `visible`, `maturity_option`,
  `metadata_kvp`) are moderation/maturity flags, not gameplay-health
  signals — checked the full field list live, nothing fits.
- Nexus's full tag inventory checked properly this time — both the 23
  `Tag`-type tags and all 177 `LegacyTag`-type tags (the type that turned
  out to hold `Patch 8 Compatible`, see Domain 5's correction) — searched
  for broken/outdated/deprecated/abandoned/not-working/maintain keywords.
  Only compatibility-affirming tags exist (`Compatibility`, `Bug Fixes`,
  `Compatibility Patch`, `Release Version Compatible`, `Patch 8
  Compatible`) — nothing negative-signal. Conclusion holds even after
  finding the second tag type.

**Conclusion**: unlike domain 5, there's no equivalent "already in the API
response, just never captured" shortcut here. The Phase 2 plan's original
approach stands as the primary path: mine the comment corpus (527,928 rows,
already scraped) and mod descriptions for crash/broken-report language —
a Phase 3 script, not further sourcing research. The plan's corroborating
question (does Discord/Reddit have a curated "known issues" list, more
efficient than per-mod comment mining) is **not yet answered** — genuinely
deferred, not attempted this round. Likely needs `claude-in-chrome` browser
access the same way prior Discord-sourced research in this project has
(Load Order Guidance v12→v13, item-injection's own "blocked, needs
unblocked machine" note) — worth checking early whether this session's
environment can reach Discord before assuming the same block applies.

## Domain 7: Incompatibility evidence review backlog — confirmed out of scope for Phase 2

No new work done here, matching the Phase 2 plan's own scoping: this is an
internal review/promotion task against 3,171 already-captured `proposed`
`evidence_claims` rows, not a sourcing question. Tracked for its own Phase 3
review pass.

## Summary for Phase 2 sequencing

Of the 3 consumption-weighted domains: **#5 closed with two strong, real,
near-zero-cost findings** (mod.io `Patch 8 Tested`, 37.5% coverage; Nexus
`Patch 8 Compatible` via the `LegacyTag` type, 20.1% coverage — both
already-fetched-but-discarded fields, one-field scraper additions on each
platform). **#6 has no equivalent shortcut, on either platform** — falls back
to comment-corpus mining (Phase 3) plus an optional, not-yet-attempted
Discord corroborating check. **#7 was never a Phase 2 task.** Next
candidates, per the original priority order: gap #2 (load-order positioning
rules) or gap #3 (shared-table conflicts, already reframed as an
evidence-review task like #7) — both still open, not started this round.
