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

## Nexus Mods — comments gap: INVESTIGATED, not yet built
- `nexus_bg3_scraper.py` fully scraped metadata/files/changelogs/dependencies
  for 16,191 mods (June 2026). Its comment fetch calls a
  `{mod_id}/comments.json` endpoint on the v1 REST API that **does not
  exist** — always 404s, silently treated as "no comments." Nexus's REST v1
  API has no comments endpoint at all.
- **Blocker (work network only) confirmed resolved from home**: loaded
  `https://www.nexusmods.com/baldursgate3/mods/141?tab=posts` live via
  Playwright on 2026-07-21 from home — works fine. The Mimecast block is
  work-network-only, as expected.
- **Live investigation (2026-07-21, mod 141 "Mod Fixer", 2,599 comments)
  found the actual mechanism — much simpler than mod.io, and not GraphQL:**
  - The Posts tab is **server-rendered HTML** on initial page load (unlike
    mod.io's client-side XHR pagination) — the first page of comments is
    already in the HTML you get back from the normal page request.
  - Pagination beyond page 1 is driven by a legacy jQuery widget
    (`window.RH_CommentContainer.Send('page', N)`) that fires a GET to:
    `https://www.nexusmods.com/Core/Libs/Common/Widgets/CommentContainer`
    with query params `game_id` (3474 for BG3), `object_id` (mod id),
    `object_type` (1 = mod), `thread_id` (per-mod comment thread id, only
    discoverable from the rendered page — not derivable from mod_id alone),
    `page`, and `page_size` (observed default **10** — i.e. 2,599 comments
    = 260 pages at the default; worth testing whether a larger `page_size`
    value is honored to cut request count).
  - Response is an **HTML fragment** (`content-type: text/html`), not JSON.
    Each comment is a clean, parseable block:
    `<li class="comment" id="comment-{id}">`, username + profile URL in
    `.comment-user` / `.comment-name`, unix timestamp in
    `<time data-date="...">`, body in
    `.comment-content-text#comment-content-{id}`, `.comment-sticky`/
    `#locked-comment-label-*` flags, and nested replies inside a child
    `<ol class="comment-kids">` (same `<li class="comment">` structure,
    recursive).
  - **Auth/cookies: NOT the same as mod.io** — this was wrong in the first
    write-up. mod.io only sets a lightweight `__cf_bm` bot-management cookie.
    Nexus fronts pages with a **full Cloudflare JS challenge** ("Just a
    moment...", a `cf_clearance` cookie). `cf_clearance` is validated against
    the requesting client's actual TLS/JS fingerprint, not just the cookie
    value — handing it from a Playwright browser to a Python `requests`
    session (the mod.io pattern) does **not** work here; `requests` gets
    re-challenged and 403s every time. `page_size` also turned out to not be
    server-honored at all (tested 10/25/50/75/100 — always the same ~10
    top-level comments back), so the "cut request count" idea above doesn't
    pan out; pagination has to walk one page at a time regardless.
  - No login/session cookie was needed for read access otherwise — comments
    loaded fully while anonymous.
- Scope: not all 16,191 mods — `BG3_Nexus_Tier1_Tier2_Mods.csv` (3,662 curated
  mods, both tiers, columns include `nexus_mod_id`/`nexus_url`) is the
  target list, prioritized by endorsements/dependency usage/category
  ranking. Decided: target **all 3,662** (not just Tier 1) once built.
  **Excluded: mod 141 (BG3 Mod Fixer)** — large historical download count
  but outdated/superseded since patch 7/8, no longer needed by the current
  community (user's call, 2026-07-21).

## `nexus_deep_comments.py` — build status (2026-07-22, WORKING)
- Written, mirrors `modio_deep_comments.py`'s shape but needed a different
  auth fix. **Root cause, found after a long trial-and-error trail (v1.0–
  v1.4, all documented in git history / script docstring if the full story
  is ever needed): a vanilla `playwright.chromium.launch()` reports
  `navigator.webdriver = True`, a basic, near-deterministic bot signal that
  Cloudflare checks directly.** Confirmed by comparing against the
  Playwright MCP browser used for the original live investigation, which
  reports `navigator.webdriver = False` and never once got challenged
  across a dozen-plus real requests — while every one of this script's own
  runs failed. Route-blocking, headless-vs-headed, fresh-page-vs-reused-page,
  and IP/volume-based rate scoring were all suspected and tried first; none
  of them were the actual cause.
- **Fix (v1.5): `context.add_init_script("Object.defineProperty(navigator,
  'webdriver', { get: () => false });")`** right after creating the browser
  context. Verified locally (no network) that this flips the flag, then
  confirmed live: `--limit 1` (mod 366, ImpUI) → 5,565 comments, zero
  challenges. `--limit 3` (adds mod 213 Tav's Hair Salon, mod 97 NSFW) →
  366: 5,565, 213: 2,061, 97: 0 (see NSFW note below) — all clean, no
  retries needed.
- Data quality spot-checked on the 366 run: 5,565/5,565 comment_ids unique
  (no pagination-overlap dupes), 3,649 correctly carry a `parent_comment_id`
  (nested replies extracted correctly), sticky/timestamp/text fields all
  populated as expected.
- **Known gap: NSFW-tagged mods return 0 comments.** Not a bug — Nexus's
  own "adult content disabled" preference gate hides the whole page for an
  anonymous/non-opted-in session, so `thread_id` can't be found and
  `fetch_all_comments` correctly returns `[]` rather than crashing. If NSFW
  mod coverage matters, would need a logged-in session with that preference
  enabled — not investigated further, scope call not yet made.
- `headless=False` (kept from the earlier debugging) means a visible
  browser window pops up while this runs — fine for interactive use, would
  need revisiting (virtual display, etc.) for unattended/headless
  execution later if that becomes necessary.

## Next steps (from home)
1. ~~Confirm `nexusmods.com` loads normally from home.~~ Done.
2. ~~Investigate the Posts tab live via Playwright.~~ Done — endpoint, auth
   pattern, and HTML shape identified.
3. ~~Build and validate `nexus_deep_comments.py`~~ Done (v1.5) — see
   build-status section above.
4. Run the full sweep (`py nexus_deep_comments.py`, all 3,661 mods minus
   Mod Fixer) and merge into a `nexus_comments_merged.jsonl` analogous to
   the mod.io merge. Not yet started — full run will take a while (popular
   mods can be thousands of comments across hundreds of sequential
   paginated requests) and hasn't been time-estimated yet.

## Security note
`bg3_scraper.py` previously had a mod.io API key hardcoded in plaintext.
Changed to read from the `MODIO_API_KEY` env var (see `.env.example`) before
this became a public repo. The old key itself was **not rotated** (user's
call) — treat it as already exposed if you find it in old local copies/zips.
