# Load-Order Positioning Rules — Deep Research Findings

Full multi-agent research run via the `deep-research` skill (see
`docs/superpowers/specs/2026-08-07-phase2-source-research-plan.md`, gap #2,
the other Blocking finding from
`docs/superpowers/specs/2026-08-07-catalog-gap-report.md`, resumed after the
consumption-weighted domains 5/6 — see
`docs/superpowers/specs/2026-08-08-patch8-known-broken-status-research.md`).
Raw pipeline artifacts (findings, challenges, dispute resolution, claims/
sources JSONL, RESEARCH_OUTPUT.md v2.1) live in
`.research/load-order-positioning-rules/` (gitignored). This doc promotes
the durable conclusions into the project's tracked record.

## Pipeline summary

7 searcher agents (D1-D7) → 1 orchestrator live-browser (`claude-in-chrome`)
verification pass (D8) → synthesis (v1.0) → 2 verifier agents (V1/V2, both
needed one retry after the known Windows agent-output-truncation bug — see
Process notes) → contrarian + OTB challenges → 1 formal dispute resolution
(CRITICAL severity) → full Phase 3.9 re-synthesis (v2.0) → a second
orchestrator live-browser follow-up pass closing the remaining open items
(v2.1). 12 agents total, 48 claims, 57 sources.

## Bottom line

**No structured, hand-curated, per-mod mapping to the community's named
divider-bucket conventions (KAVT/LN/Astra/Sai/mod-15851) exists anywhere
searched** — confirmed via Nexus mod pages (live-browser verified, not just
search snippets), `wiki.bg3.community`, `bg3.wiki`, and every relevant
GitHub tool. This closes the original framing of gap #2 with a real,
actively-confirmed absence, matching the pattern from the item-injection
research (gap #1).

**But the landscape changed materially in the ~2 days before this research
ran**, and the research found real, usable alternatives:

- **VOLO** (Verified Order & Load Optimisation) went from "not yet public"
  (2026-08-06) to a fully live, git-clonable, **CC0-licensed** (public
  domain, verbatim-confirmed) 3,138-mod masterlist JSON. Its `divider`
  field is literally Astra's real taxonomy (used with the author's
  permission) — but covers 2,814/3,138 mods (89.7%), and only **16 of
  those 2,814 (0.5%) are hand-verified**; the rest are algorithmically
  inferred at varying, documented reliability. Real data, not a substitute
  for verified human judgment.
- **BG3 Load Order Optimizer** (Nemix3D) separately publishes a
  machine-readable masterlist (61 rules / ~40 mods) as its own GitHub repo
  — but its data license explicitly restricts incorporation into "another
  optimizer, tool, application, or service" without permission. The
  project owner has stated this project is private/non-redistributed, so
  this is a documented consideration, not a blocker.
- **loadorderlibrary.com** hosts one real, large (1,334-mod), numbered,
  hierarchically-categorized load order (the well-known "Difficulty,
  Immersion, Quality" collection) — but it's a single anonymous curator's
  personal list, not a community-consensus source, and its exact numeric
  positions risk being collection-specific coincidences rather than
  portable per-mod-pair rules.
- **No built-in load-order logic exists in BG3ModManager, bg3se, or
  lslib** — confirmed via direct source read. A fan site's claim that
  BG3ModManager has a "Sort by Dependencies" feature is fabricated,
  refuted by both the source code and the project's own open GitHub
  Discussion #376.

**The single most important finding, however, is about this project's own
data, not anything external.** An Outside-the-Box challenge — verified
directly against this project's own scraper source code — found that the
930 Nexus + mod.io Collections already scraped by this project
(49,907 membership rows, `catalog_collection_memberships`) capture WHICH
mods are in each collection but **never captured the mods' internal
ORDER** — the GraphQL query doesn't request an index/position field, and
no position column exists in the DB. If Nexus's array order turns out to
be curator-meaningful (not yet confirmed — this is the one remaining open
question), recovering it would give this project ~930 curator-ordered
lists via infrastructure that already works at full scale — no new
Cloudflare risk, no new licensing exposure, no new scraping needed beyond
a small patch and a re-run.

## Recommendations (priority order)

1. **Highest priority: check whether Nexus's `modFiles` array order is
   curator-meaningful** (cheap — compare a fresh read of the "Difficulty,
   Immersion, Quality" Collection against its already-captured
   loadorderlibrary.com mirror). If confirmed: patch
   `nexus_collections_scraper.py`/`modio_deep_collections.py` to capture
   per-entry position, add a `position` column to
   `catalog_collection_memberships`, re-run the full 930-collection sweep
   (well under an hour). Do this before any external-ingestion work below —
   zero new licensing/access risk, reuses proven infrastructure. **This is
   now the single open item from the whole research pass.**
2. **Pilot VOLO's masterlist as a low-trust supplementary signal, not a
   blanket-trusted source.** Filter by its per-mod `evidence` field
   (install/working/broken counts) rather than uniformly ingesting all
   2,814 divider-assigned mods — only 0.5% are hand-verified.
3. ~~Verify VOLO's license~~ **Done**: `masterlist/LICENSE` is verbatim
   CC0 1.0 Universal — freely reusable, no permission needed.
4. **Before ingesting BG3 Load Order Optimizer's data, make an explicit
   decision** — request Nemix3D's permission, or document this project's
   private/non-redistributed posture as the basis for treating the
   restriction as non-blocking (user's call already leans toward the
   latter, per 2026-08-08 conversation — still worth a written note).
5. **If either masterlist is ingested, treat it as a live, periodically
   re-checked dependency, not a one-time snapshot** — both are under 2
   weeks old; this project's own precedent (Nexus mod 141, "BG3 Mod
   Fixer," going obsolete) argues against assuming permanence.
6. **If loadorderlibrary.com's DIQ list is used, don't bulk-import its
   numeric positions as general rules** — cross-check any extracted
   pairwise relationship against an independent source first; tag
   uncorroborated positions as "collection-specific example," not
   "positioning rule."
7. **Treat KAVT's positioning requirement as a narrow
   shared-table/`CharacterVisuals`-conflict rule**, feeding this project's
   existing Blocking-severity shared-table-conflicts gap — not a
   general-purpose divider convention like LN's/Astra's.
8. ~~Resolve the three disputed Nexus mod pages~~ **Done**: mod 21532 =
   "Astra's Load Order Dividers" (astralities — confirms the
   Astra/Astralities identity link to the KAVT wiki page's editor); mod
   15851 = "Patch 8 Load Order Dividers" (champagne26 — confirmed distinct
   from LN's mod); mod 13215 = "Guidelines for Load Order" (Sai — confirms
   title and real username).
9. **Lower priority**: check whether Wabbajack publishes a machine-readable
   gallery/catalog index of all actively-maintained BG3 lists (two were
   found by accident — "BG3 Enhanced Edition," "Listonomicon Again" — a
   third, "Infinite Pathways," was named but never followed up).
10. **Cheap follow-up**: check whether `wiki.bg3.community`'s markdown
    source lives in a public GitHub repo — would let the whole wiki be
    bulk-cloned and grepped, sidestepping its SPA-rendering problem
    entirely.
11. **Future, non-immediate**: mine this project's own ~528K-comment corpus
    for "here's my working order" signal via the existing
    `evidence_claims`/`load_order` pipeline — potentially an
    order-of-magnitude larger raw corpus than VOLO's own 14-order
    calibration set. Real NLP effort, not a quick win; depends on
    recommendation 3 already being resolved (it is).

## What's still open

- **Whether Nexus's Collections `modFiles` array order is actually
  meaningful** — the one remaining open question from the entire research
  pass, and now the top-priority next step (Recommendation 1).
- Astra's mod (21532) exact category-list content — title/authorship
  confirmed, but the specific bucket names weren't re-extracted during the
  final verification pass.
- Whether Wabbajack has a first-class catalog/gallery index (Recommendation
  9) — not investigated.
- Whether `wiki.bg3.community` has a public markdown-source GitHub repo
  (Recommendation 10) — not investigated.

## Process notes for future deep-research runs in this repo

- **Both Phase 2.5 verifier agents hit the Windows agent-output-truncation
  bug on their first attempt** (task-notification `<result>` text ending
  mid-sentence, and the expected findings file genuinely absent from disk —
  not just a formatting artifact). Both succeeded cleanly on a retry with a
  tighter tool-call budget and instructions to write incrementally — same
  fix as the item-injection research's V2 agent needed. Worth continuing to
  verify files landed on disk before trusting any agent's chat-visible
  summary, exactly as the skill's persistence safety net requires.
- **The orchestrator doing its own live-browser verification pass (twice —
  once mid-pipeline as D8, once post-synthesis to close remaining gaps)
  was more effective than spawning gap-pursuer subagents**, since
  subagents in this pipeline lack `claude-in-chrome` and would have hit the
  identical Cloudflare/SPA walls the original searchers did. When the
  actual blocker is "needs a real browser," only the orchestrator (or a
  differently-tooled agent) can close it — spawning more of the same
  agent type just re-confirms the same block.
- **A contrarian challenge caught a real, un-reconciled internal
  contradiction between two themes of the same synthesis** (VOLO's
  `divider` field vs. the "no per-mod mapping exists" conclusion) — this
  is exactly the kind of cross-theme consistency check a single synthesis
  pass is prone to missing, and is a second, independent confirmation
  (after the item-injection research) that the mandatory challenge phase
  earns its cost in this project.
