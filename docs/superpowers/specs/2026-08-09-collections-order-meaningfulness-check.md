# Collections `modFiles` order-meaningfulness check — RESOLVED (negative)

Follow-up to `docs/superpowers/specs/2026-08-08-load-order-positioning-research.md`,
Recommendation 1 — "the one remaining open question from the whole research
pass." Raw data (fresh Nexus GraphQL response, loadorderlibrary.com API
response, parsed comparison, name-overlap list) lives in
`.research/load-order-positioning-rules/collections-order-check/`
(gitignored).

## Question

Does Nexus's Collections `modFiles` array order reflect the curator's actual
load order? If so, this project's existing 930-collection Collections sweep
(49,907 membership rows, already captured) could cheaply yield curator-ordered
lists — just a scraper patch (capture array index) and a re-run — without any
new scraping, licensing, or Cloudflare risk.

## Method

1. Fresh direct query (no browser needed — confirmed no-auth, no-Cloudflare
   host from the original 2026-07-24 Collections research) against
   `https://api.nexusmods.com/v2/graphql` for the "Difficulty, Immersion,
   Quality" collection (slug `pns4qv`, 226K endorsements, 1,016 mods) —
   the same collection the original deep-research pass (D8) had already
   independently identified as having a real, curated, publicly mirrored
   load order on loadorderlibrary.com. Returned 1,015 `modFiles` entries in
   API response order.
2. loadorderlibrary.com's frontend is a client-rendered SPA — `curl`/`WebFetch`
   only gets the empty HTML shell, matching what D8 found. Rather than
   requiring a browser, found and used its underlying (undocumented, but
   genuinely anonymous-read, zero-auth) JSON API directly:
   `https://api.loadorderlibrary.com/v1/lists/difficulty-immersion-quality`
   — returns the full 1,334-entry modlist.txt content as a JSON array,
   `+`/`-` enabled/disabled prefixed, with explicit `_separator` category
   header lines. Confirmed live in a real browser afterward (page metadata
   — 941/1334 enabled, version 144.0 — matches the API response exactly).
3. Parsed both into ordered mod-name lists (loadorderlibrary: 1,334 entries,
   1,334 real mods after dropping category-header separator lines and the
   trailing Mod-Organizer-generated comment line). Matched by exact mod
   name: **387 mods overlap** between Nexus's 1,015-entry array and
   loadorderlibrary's 1,334-entry list.
4. Computed Spearman rank correlation between each mod's position in the
   two orderings, plus a direct spot-check on the single most diagnostic
   mod for this collection: **Compatibility Framework**, which
   loadorderlibrary's list places at position 1333/1334 — the literal last
   real entry, consistent with CF's hard requirement to load after
   everything else it patches.

## Result

- **Spearman rank correlation: -0.077** (n=387) — statistically
  indistinguishable from zero. Nexus's array order does not track
  loadorderlibrary's curated order in either direction.
- **Compatibility Framework sits at position 803/1015 in Nexus's array** —
  roughly the middle, not the end. If Nexus's order carried any of the
  curator's actual load-order intent, CF would be at or very near the end
  here too; it isn't.
- **Not alphabetical either**: only 1/1015 names match a case-insensitive
  alphabetical sort of the same list — ruling out "it's just alphabetized"
  as an alternative explanation for the array order.

## Conclusion

**Nexus's Collections `modFiles` array order is not curator-meaningful.**
Most likely reflects upload/database-insertion order or some other
non-semantic internal ordering, not the collection author's intended load
order. This is a real, clean negative result on the single open question
the 2026-08-08 load-order-positioning research left unresolved.

## Recommendation impact

Recommendation 1 from the load-order-positioning research
(patch `nexus_collections_scraper.py`/`modio_deep_collections.py` to capture
per-entry position, add a `position` column to
`catalog_collection_memberships`, re-run the full 930-collection sweep) is
**closed as not worth pursuing** — the underlying premise (Nexus's existing
array order already encodes curator intent) does not hold. Recovering real
per-mod positioning data from Collections would require actually parsing
each collection's own `modlist.txt`-equivalent export (where one exists) or
some other per-collection source, not a cheap re-scrape of already-fetched
API data. Not pursued further — no such bulk per-collection export source is
currently known to exist across all 930 collections (loadorderlibrary.com
itself only hosts 7 total BG3 lists, one of them this DIQ collection).
