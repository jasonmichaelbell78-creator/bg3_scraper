# BG3 Loadout Advisor — Design

## Goal

A repeatable process for building and troubleshooting BG3 mod lists conversationally: the user describes what they want out of a playthrough (theme, difficulty, must-haves), Claude recommends mods grounded in the reference catalog, resolves dependencies and known conflicts for the candidate list, constructs a load order using the Load Order Guidance doc's mechanics, and later helps troubleshoot problems that come up during actual play — all backed by a durable, git-tracked document per playthrough rather than starting cold each session.

This is the final deliverable this whole project (the BG3 mod scraper + reference catalog + Load Order Guidance research) has been building toward. It is explicitly not the "Gate 6 personal loadout system" originally sketched in the project's retired multi-AI conference-point roadmap (a separate database with deterministic validators) — that framing was reconsidered in favor of something the user actually wants: a conversation with Claude, not another system to operate.

## Why conversational, not a standalone tool

Considered three approaches:

- **Pure conversational, no new code** — maximum flexibility, but hand-written SQL for dependency-closure and conflict-checking risks silently missing a transitive dependency or an indirect conflict, session to session.
- **Process + a small tested query library (chosen)** — the two operations that are genuinely easy to get wrong ad hoc (dependency-closure resolution, known-conflict checking) get tested helper functions. Everything else — matching mods to a described theme, weighing evidence/comments, constructing the actual load order — stays flexible, reasoned about live each session. The user explicitly asked for flexibility; over-formalizing thematic search into rigid queries would work against that.
- **Standalone tool** — ruled out directly by the user: the point is a conversation with Claude, not a tool run independently.

## Architecture

```
app/loadout_advisor/
    __init__.py
    dependency_resolver.py
    conflict_checker.py
    tests/
        __init__.py
        fixtures.py
        test_dependency_resolver.py
        test_conflict_checker.py
loadouts/
    <playthrough-slug>.md
```

`app/loadout_advisor/` is a new top-level module, sibling to `app/scripts/` and `app/catalog_pipeline/`. It is **read-only** against `catalog/B26/BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db` — it never writes to the reference catalog, so it needs none of the hash-gate/backup/migration-history machinery `app/catalog_pipeline/` uses. A plain `sqlite3.connect(db_path)` is sufficient; no `PRAGMA foreign_keys` concern applies since nothing is inserted.

`loadouts/` is a new top-level directory, one markdown file per playthrough, **tracked in git** (unlike `data/` and `catalog/`, which are gitignored — these documents are small, human-authored/curated content, not scraped bulk data, and their value is in their history: `git log` on a single loadout file becomes a natural record of how it evolved across troubleshooting sessions).

## The two helper functions

**Verified against the real schema (2026-08-07)**: `dependencies`, `dependency_closure`, `mod_relationships`, and `risk_flags` all key on `mods.mod_uid` (the identity-resolved level — one row per logical mod), not `platform_listings.listing_uuid` (the per-platform-listing level, joined to `mods` via `platform_listings.mod_uid`). The functions below operate at the `mod_uid` level to match the tables they actually query; bridging from a `listing_uuid` known during conversational search is a one-line join (`SELECT mod_uid FROM platform_listings WHERE listing_uuid = ?`), not this module's concern.

### `dependency_resolver.py`

```python
def resolve_dependency_closure(conn: sqlite3.Connection, mod_uids: list[int]) -> dict:
    """
    Given a candidate mod list (by mods.mod_uid), walks the dependencies/
    dependency_closure tables to find the full transitive dependency set.

    Returns:
      {
        "already_included": [mod_uid, ...],   # deps already in the input list
        "missing": [
          {"mod_uid": int, "name": str, "required_by": [mod_uid, ...]},
          ...
        ],
      }
    """
```

### `conflict_checker.py`

**Corrected during design verification (2026-08-07)**: `mod_relationships.relationship_type` has no `incompatibility` value at all — its real values are `alternative_to`, `patch_for`, `series_companion`, `soft_mention` (confirmed against live data). The real incompatibility signal (3,184 rows) lives in `evidence_claims.claim_type = 'incompatibility'` instead — but those claims target a mod by **free text** (`target_text`, e.g. `"Mind Weaver Animations"`), not a foreign key, and carry a `claim_state` (`proposed` / `reviewed_supported` / `reviewed_insufficient` / `contradicted` / `promoted`) reflecting how much this project's own evidence review has actually validated them. Resolving `target_text` to a specific candidate `mod_uid` is a fuzzy-matching problem, not a clean join, and this project's own evidence hierarchy (documented in Drive's Work Delineation doc) is explicit that a claim is never auto-promoted to a canonical fact. So this function surfaces evidence for a human/Claude to read and judge — it does not assert conflict verdicts:

```python
def check_known_conflicts(conn: sqlite3.Connection, mod_uids: list[int]) -> dict:
    """
    Two genuinely different kinds of signal, returned separately rather than
    merged into one falsely-uniform list:

    Returns:
      {
        "risk_flags": [
          {"mod_uid": int, "risk_category": str, "risk_level": str, "basis": str},
          ...
        ],
        # Structured, mod_uid-keyed, clean signal straight from risk_flags.

        "evidence_to_review": [
          {"mod_uid": int, "claim_type": str, "claim_state": str,
           "target_text": str, "claim_text": str},
          ...
        ],
        # incompatibility/compatibility-type evidence_claims whose SOURCE
        # listing (via evidence_claim_links -> evidence_source_records
        # .source_listing_uuid -> platform_listings.mod_uid) is one of the
        # candidate mods. target_text names what the claim is ABOUT, in the
        # source's own words -- read it, don't assume it names another
        # candidate mod_uid.
      }
    Both lists empty means no known risk/incompatibility signal recorded for
    this candidate list -- not a guarantee none exists.
    """
```

`mod_relationships`' real values (`alternative_to`, `series_companion`, etc.) are still useful signal, but for the thematic-search phase (e.g. "these two are alternatives, probably don't want both"), not this conflict-checking helper — deliberately left as something to consider live during search rather than folded into a helper that isn't really about conflicts.

Both functions take a connection and a plain list of `mod_uid` integers — no other state. During a session, once mod candidates have been narrowed down conversationally (naturally surfacing `platform_listings.listing_uuid` first, since that's what has names/URLs/categories), the join above bridges to `mod_uid` before calling these, before finalizing a load order.

## The loadout document

One file per playthrough at `loadouts/<slug>.md`:

```markdown
# <Playthrough name>

## Intent
<What was described wanting -- theme, difficulty, must-haves, deal-breakers>

## Final mod list
- <mod name> (<platform>:<platform_mod_id>) -- <one-line why it's here>
...

## Dependency check
Resolved clean, or: <N> missing dependencies added -- <list, each with what required it>

## Known conflicts / risks surfaced
<Each finding from check_known_conflicts, or "None found in the catalog's recorded relationships/risk flags.">

## Load order
1. <mod> -- <rationale, citing a Load Order Guidance doc section where relevant>
...

## Troubleshooting log
### <date> -- <symptom>
<What was checked (triage table, logs per Load Order Guidance §1.1, catalog evidence/comments), what was found, what changed>
```

## Testing

Standard TDD, matching this project's established pattern (`app/catalog_pipeline/claude_phase3`, `claude_phase4`): pytest against an in-memory SQLite fixture mirroring only the tables these two functions touch (`platform_listings`, `dependencies`, `dependency_closure`, `mod_relationships`, `risk_flags`). No real database is ever touched by tests.

## Explicitly not being built (YAGNI, per "I just want flexibility")

- No thematic-search function or scoring algorithm — matching a described playthrough theme to candidate mods stays live reasoning each session, using `catalog_browse_labels`, `platform_tags`, `mod_rank`, `catalog_collections`, and comment/evidence data directly.
- No automated load-order sorter — constructing the actual order stays reasoning grounded in the Load Order Guidance doc's mechanics plus `load_order_hints` and any `relative_load_order` evidence claims, not a deterministic algorithm.
- No CLI wrapper, no web UI, no new database, no schema changes to the reference catalog.

## Known limitation to design around, not discover mid-session

`mod_classifications` covers 3,649 of 19,967 mods (~18.3%) as of the 2026-08-07 Phase 1 Gap Analysis audit (`docs/superpowers/specs/2026-08-07-catalog-gap-report.md`) -- corrected from an earlier "8,249 (~41%)" figure, which was actually the table's *row* count (mods can carry multiple classification terms), not the distinct-mod count. Thematic search via classification data will have real gaps; `catalog_browse_labels` (populated for all 19,967) and live evidence/comment lookups are the more reliable fallback when classification data is thin for a candidate mod.
