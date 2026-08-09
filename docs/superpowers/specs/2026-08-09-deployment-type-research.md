# Deployment-Type External Signal — Deep Research Findings

Full multi-agent research run via the `deep-research` skill (gap #4 from
`docs/superpowers/specs/2026-08-07-catalog-gap-report.md`, sourcing plan in
`docs/superpowers/specs/2026-08-07-phase2-source-research-plan.md` section 4,
resumed after the Collections order-meaningfulness check closed gap #2's last
open item). Raw pipeline artifacts (findings, challenges, disputes, gap-pursuit,
claims/sources JSONL, RESEARCH_OUTPUT.md v1.0-v3.0) live in
`.research/deployment-type/` (gitignored). This doc promotes the durable
conclusions into the project's tracked record.

## Pipeline summary

7 searcher agents (D1-D7) → synthesis (v1.0) → 2 verifier agents (V1/V2, both
needed one retry after the known Windows agent-output-truncation bug) →
contrarian + OTB challenges (2 CRITICAL, 2 HIGH findings) → 1 formal dispute
resolution (2 disputes) → Phase 3.9 re-synthesis (v2.0) → mandatory gap-pursuit
round (G1-G3, G1/G2 each needed one retry after the same truncation bug, G2's
first attempt lost entirely with zero recoverable text) → gap verification
(GV1/GV2) → final re-synthesis (v3.0). 17 agents total, 53 claims, 25 sources.

## Bottom line

**No platform hands you a ready-made "deployment type" field, on either Nexus
or mod.io.** Neither platform's file schema, tag vocabulary, or metadata
system carries any PAK/Loose-Files/Script-Extender-Required/Native-Replacer
signal — confirmed exhaustively via live API introspection on both platforms.

**A genuinely new synthesis discovery was found, then tested to failure.**
Nexus's GraphQL API exposes `modFileContents` (and REST v1's
`content_preview_link`) — a bulk-queryable listing of every archive's internal
file paths, already indexed at scale (434,192 rows for BG3). Separately,
BG3ModManager's actual source code was read directly and found to detect
Script-Extender-dependency via one exact rule: does the mod's file listing
contain `ScriptExtender/Config.json`? This convention is independently
corroborated by Script Extender's own official docs. Combining these two
findings — a bulk file-listing API plus BG3ModManager's exact detection rule —
was a real synthesis discovery no single searcher proposed.

**It does not work in practice.** A dedicated gap-pursuit and
gap-verification round found:
- **Pak-opacity, confirmed twice independently**: `modFileContents` never
  unpacks a `.pak` archive's internal contents — it only surfaces nested paths
  for files shipped *loose*, outside a pak. Two known, genuinely
  Script-Extender-dependent framework mods (125 "5e Spells", 1333 "Community
  Library") ship pak-only and show zero SE-related paths via this API. A
  matched control (mod 13200, which ships its SE settings file loose) proves
  the mechanism directly.
- **A hard age-based coverage cutoff, confirmed and precisely bounded**:
  `modFileContents` has zero coverage for mods created in a ~6-week window
  between 2025-09-23 and 2025-11-06 onward — but this is moot for pak-packaged
  mods regardless of age, given the pak-opacity finding.

Since PAK is the majority Nexus deployment type, **the triangulated pipeline
is confirmed non-viable for its primary purpose** — a real, well-evidenced
negative, not an open question.

**What actually works, found via the OTB challenge**: VOLO's public,
CC0-licensed masterlist (already vetted by this project's 2026-08-08
load-order research) already has a computed `usesScriptExtender` boolean field
for 6,296/19,967 mods (31.5% of the corpus), zero new scraping needed. This is
now the report's single strongest, most actionable recommendation.

**The honest final answer**: after three full research rounds, roughly 68.5%
of the corpus — everything VOLO doesn't already cover — has no good
bulk-extractable external deployment-type signal. This is the real shape of
the answer to gap #4.

## Other findings

- **mod.io: clean negative**, reconfirmed across every pass — no filetype/tag/
  metadata field carries deployment-type signal on that platform at all
  (structural: its built-in mod browser makes install instructions
  unnecessary for authors, so the information was never generated).
- **Community wiki taxonomy, now fully read (not snippet-inferred)**:
  `wiki.bg3.community`'s real GitHub source repo (`BG3-Community-Library-Team/
  bg3-community` — this project's standing open question about whether the
  wiki has a public git source is now resolved: yes) documents a six-category
  taxonomy (PAK / MOD FIXER / LOOSE FILES / NATIVE MODS / MANUAL INSTALLATION
  / SCRIPT EXTENDER). Good reference vocabulary for whatever schema this
  project eventually builds — confirmed no per-mod bulk list exists there.
- **Nexus's Vortex extension** (a separate, more authoritative codebase than
  third-party BG3ModManager) has a real `MOD_TYPE_LOOSE` detector for
  zero-.pak archives — but Vortex's own maintainers commented out that exact
  clause in their stricter warning-dialog logic, corroborating it's a weak/
  probabilistic signal, and it's never exposed as externally-queryable bulk
  metadata.
- **Deployment type should be modeled as independent boolean flags, not a
  single enum** — mods can be simultaneously PAK-packaged and SE-dependent, or
  PAK and native-override.
- **BG3ModManager's `avalonia` rewrite branch** was checked and preserves the
  same core detection logic as the 10-months-stale `master` branch, plus one
  real behavioral broadening (Osiris-scripting-alone now also triggers the
  override classification).

## Recommendations (priority order)

1. **Adopt VOLO's `usesScriptExtender`/`featureFlags` fields now** — 31.5%
   coverage, zero new access/licensing cost. Join via name+author fuzzy
   matching (VOLO has no direct Nexus/mod.io ID field).
2. **Do not build the Nexus-API triangulated pipeline** as originally
   envisioned — confirmed non-viable for the pak-packaged majority.
3. **Implement Script-Extender-dependency detection as a narrow, honestly
   scoped signal stack**: VOLO first → Nexus's structured
   `modRequirements.nexusRequirements` field → a `ScriptExtender/Config.json`
   check only for mods confirmed to ship loose files and old enough to have
   API coverage → description-text keyword fallback. For the remaining
   uncovered fraction, the honest answer is "unknown" — don't paper over it.
4. Cross-check VOLO's 128 `usesScriptExtender=true` mods against the
   description-text sample to resolve an unreconciled discrepancy in their
   positive rates before trusting the ranking as final.
5. Use the wiki's six-category taxonomy as reference vocabulary for schema
   design, not as a data source.

## Process notes

- Hit the documented Windows agent-output-truncation bug 4 times this run
  (V1, V2, G1, G2) — all recovered via a retry with a tighter tool-call
  budget and explicit incremental-write instructions, same fix as prior
  research runs in this project. G2's first attempt was the worst case (zero
  recoverable text on either channel) — resolved on the allowed single retry.
- The gap-pursuit round (mandatory scan, conditional execution) was the right
  call here: without it, this report would have shipped v2.0's LOW-confidence
  "needs more verification" framing instead of the confirmed, decisive
  negative v3.0 actually found — a materially different, more useful answer
  for anyone deciding whether to build against this.
