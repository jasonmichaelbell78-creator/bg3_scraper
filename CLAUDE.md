# BG3 Mod Scraper — Project Status

## Goal
Pull BG3 mod data from Nexus Mods and mod.io. Official APIs already cover
metadata/files/changelogs/dependencies for both sites. The actual gap this
project closes is **comments/discussion threads**, which the APIs don't
fully expose.

## Environment notes (this machine)
- Python is invoked as `py` (Python 3.14 launcher), not `python`/`python3`.
- Installed: `requests`, `playwright` (+ Chromium browser via
  `py -m playwright install chromium`).
- Large data files live alongside this repo but are gitignored (see
  `.gitignore`) — too large to commit, and Nexus's API acceptable-use policy
  discourages rehosting bulk API-sourced data publicly. They travel between
  machines as a manually-carried zip, not through git.
- Repo: https://github.com/jasonmichaelbell78-creator/bg3_scraper (renamed
  from `bg3_nexus_scraper` — it's not Nexus-only anymore).
- `gh` CLI appears to be missing on this machine (its wrapper points to a
  path that no longer exists). Git operations here used `git` directly with
  a cached Windows Credential Manager credential (`credential.helper =
  manager`, i.e. Git Credential Manager) instead.

## mod.io — comments gap: CLOSED
- `bg3_scraper.py` did a full sweep of mods/files/deps/events/team — fine.
- Its comment fetch had no pagination loop, so it silently capped at ~100
  comments/mod (`modio_comments_fullsweep.jsonl`, 56,417 rows across 4,361
  mods; 115 mods hit the ceiling).
- Investigated live: mod.io's own frontend calls
  `https://mod.io/v1/games/@<slug>/mods/@<slug>/comments?_offset=N&_sort=-id`
  — NOT the documented `api.mod.io` host. Auth is via Cloudflare
  bot-management cookies (`__cf_bm`, `__cflb`, `_cfuvid`) minted by loading
  the page in a real browser, plus custom headers (`x-modio-game`,
  `x-modio-mod`, `x-modio-origin: web`) — no API key needed for this path.
- `modio_deep_comments.py`: does ONE Playwright page load to mint those
  cookies, then reuses the session via plain `requests` for fast bulk
  pagination (no browser per mod). Confirmed the ~100 cap was a pagination
  bug, not a real limit — e.g. "Ancient Mega Pack" actually has 3,666
  comments, not ~100.
- Ran against all 115 previously-capped mods: 31,266 comments fetched, zero
  failures → `modio_comments_deep_refresh.jsonl`.
- `modio_merge_comments.py` (v1.1): merges that into `modio_comments_merged.jsonl`
  (44,777 untouched rows + 31,266 fresh rows, 11,512 stale rows dropped,
  128 duplicate-id rows deduped out — 76,043 unique rows total).
  **`modio_comments_merged.jsonl` is the file to use going forward** —
  `modio_comments_fullsweep.jsonl` is left as-is, unmerged.
- Full provenance (scraper versions, run timestamps, mod-selection rule,
  auth/pagination details, dedup root-cause, file hashes) is in
  `manifest_modio_comments.md` / `.json`, with per-mod counts in
  `manifest_modio_per_mod.csv` — written in response to a ChatGPT audit
  request cross-checking this dataset.

## Nexus Mods — comments gap: NOT STARTED
- `nexus_bg3_scraper.py` fully scraped metadata/files/changelogs/dependencies
  for 16,191 mods (June 2026). Its comment fetch calls a
  `{mod_id}/comments.json` endpoint on the v1 REST API that **does not
  exist** — always 404s, silently treated as "no comments." Nexus's REST v1
  API has no comments endpoint at all.
- Possible alternative: Nexus has a GraphQL API (`api.nexusmods.com/v2/graphql`)
  with a `searchComments` query (cursor pagination: filter/sort/after/
  before/first/last, returns edges/nodes/pageInfo/totalCount) — **not yet
  validated live**. Exact filter shape (how you scope it to one mod) is
  unconfirmed; would need a schema introspection query against the live
  endpoint to nail down before relying on it.
- **Blocker discovered**: `nexusmods.com` is entirely blocked on the work
  network by a Mimecast Secure Web Gateway (categorized as "Games", not
  Nexus's own doing). Confirmed this is a **work-network-only** block — the
  user's home network does not have it. mod.io is unaffected either way.
  **Any Nexus scraping work (building/testing the scraper against live
  pages) needs to happen from home.**
- Scope: not all 16,191 mods — `BG3_Nexus_Tier1_Tier2_Mods.csv` (3,662 curated
  mods, both tiers, columns include `nexus_mod_id`/`nexus_url`) is the
  target list, prioritized by endorsements/dependency usage/category
  ranking. Decided: target **all 3,662** (not just Tier 1) once built.

## Next steps (from home)
1. Confirm `nexusmods.com` actually loads normally on the home network.
2. Load a real Nexus mod page's "Posts" tab (e.g.
   `https://www.nexusmods.com/baldursgate3/mods/141?tab=posts`) via
   Playwright and inspect: is it server-rendered or a JS SPA? What
   auth/cookies does it need? Does the same "one browser warm-up, then
   reused-session plain requests" pattern from mod.io apply, or is something
   else going on (e.g. the GraphQL API might actually be simpler)?
3. Build `nexus_deep_comments.py` (mirror `modio_deep_comments.py`'s
   structure) targeting all 3,662 mods from the tier CSV.
4. Merge into a `nexus_comments_merged.jsonl` analogous to the mod.io merge.

## Security note
`bg3_scraper.py` previously had a mod.io API key hardcoded in plaintext.
Changed to read from the `MODIO_API_KEY` env var (see `.env.example`) before
this became a public repo. The old key itself was **not rotated** (user's
call) — treat it as already exposed if you find it in old local copies/zips.
