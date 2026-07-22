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

## `nexus_deep_comments.py` — build status (2026-07-21, UNRESOLVED)
- Written, mirrors `modio_deep_comments.py`'s shape but had to diverge on
  auth after several failed approaches — full story is in the script's own
  docstring (v1.4). Short version:
  - v1.0 (mod.io pattern: mint cookies once, hand off to `requests`) — 403s
    every time. Confirmed why: see "Auth/cookies" note above.
  - v1.1 (keep one Playwright *page* open, `page.goto()` per mod) — first
    navigation on a fresh page always passes; reusing that same page object
    for a second/third/etc. top-level navigation gets challenged again. Looks
    behavioral (repeated-navigation pattern on one page), not a fingerprint
    check.
  - v1.2 (one browser *context* stays open for the whole run, brand-new
    page per mod) — confirmed working in isolated manual tests at the time.
    Also blocked image/font/css/media requests via `context.route()` for
    speed.
  - **v1.3: removed the route-blocking.** A clean same-mod, same-session A/B
    strongly implicated it (blocking on → 403 "Just a moment..."; blocking
    off, nothing else changed → 200) — a browser that never loads its own
    stylesheets/fonts is a plausible bot signal. But this was **not the full
    fix**: a follow-up `--limit 3` run failed on all 3 mods again right
    after, including one that had just individually succeeded.
  - Has retry-with-backoff (`fetch_with_retry`, waits 20s then 60s) as a
    safety net, but it does not reliably recover once things go bad.
- **Not yet validated end-to-end against real data — genuinely unresolved,
  not just "needs one more cooldown."** The pattern across the *entire*
  multi-hour debugging session: isolated single-page tests tend to succeed;
  anything firing several requests back-to-back (a `--limit 3` run, or a
  fast sequence of one-off debug tests) tends to fail partway through —
  even after a ~75–80 minute cooldown that did clear a single test. This
  looks like cumulative, volume-based IP scoring on top of the
  route-blocking issue. Critically, **every test — pass or fail — adds to
  that same tally**, so rapid iteration to "fix" this makes the next
  attempt less likely to succeed, not more. Do not debug this the way this
  session did (many browser launches in quick succession); it likely made
  things worse each time.
  **UPDATE (2026-07-21, ~2hrs later): tested again, same result, and this
  now looks structural rather than a lingering effect of the original
  debugging session.** After a genuine ~2-hour gap with zero requests to
  nexusmods.com, a single manual page load with `headless=False` (v1.4)
  succeeded cleanly on mod 366 (ImpUI). Within roughly a minute, running
  `py nexus_deep_comments.py --limit 1` against **that same mod** failed
  every retry attempt (80s of backoff, all exhausted).
  This is the third independent confirmation of the same shape: a lone,
  isolated request tends to succeed; anything that follows it soon after
  — regardless of headless vs headed, regardless of route-blocking on/off,
  regardless of fresh-page-per-mod vs reused-page — fails. Three different
  code-level variables have now been tried and ruled out as the primary
  cause. What hasn't varied across any of these tests: the source IP, and
  the fact that requests keep coming in quick succession relative to each
  other. **Read this as frequency/volume-based scoring on this IP, not a
  browser-fingerprint or headless-detection problem** — those are still
  probably contributing factors, but not sufficient to explain the pattern
  alone.
  Practical implication: a 2-hour cooldown is enough for *one* request to
  clear, but not enough headroom to run even a single mod's full comment
  pagination (which is itself multiple sequential requests a few seconds
  apart) without tripping back into the same state. If this holds, scraping
  3,661 mods — each needing 1 to (for popular mods) 100+ sequential
  requests — may not be practical from this IP at any patience level using
  this approach, or would require per-request delays long enough to make
  a full sweep take an impractically long time (weeks+, unverified).
  **Options going forward (unranked, none tested yet):**
  - A genuinely different source IP (mobile hotspot, VPN, proxy) — the
    most direct test of the "is this really IP-bound" theory, and the
    likely real fix if so.
  - `curl_cffi` (TLS-fingerprint-matching HTTP client) reusing a
    Playwright-minted `cf_clearance` — untested whether this changes
    anything if the block truly is frequency-based rather than
    fingerprint-based.
  - Drastically slower pacing (e.g. one request every several minutes) —
    only worth trying if the scoring window turns out to be short; would
    need a live test to find the actual safe interval, which itself costs
    more attempts against an already-suspicious IP.
  - Revisit the GraphQL API (`api.nexusmods.com/v2/graphql`) as a
    differently-protected path — still unvalidated from the original
    investigation.
  - Reconsider scope: e.g. hand-scrape or spot-check only the highest-value
    mods rather than all 3,661, if a reliable bulk method doesn't pan out.
- Parsing logic (`parse_comments`) itself is validated — it's the same
  BeautifulSoup extraction shape confirmed against real response HTML
  during the investigation phase, unrelated to the auth issue above.

## Next steps (from home)
1. ~~Confirm `nexusmods.com` loads normally from home.~~ Done — see above.
2. ~~Investigate the Posts tab live via Playwright.~~ Done — see above;
   endpoint, auth pattern, and HTML shape are all identified.
3. ~~Build `nexus_deep_comments.py`~~ Written (v1.2), but not yet validated
   end-to-end — see build-status section above. Next session: cold-start
   test with `--limit 3` after a real cooldown period.
4. Once a clean test run produces real comments, run the full sweep
   (`py nexus_deep_comments.py`, all 3,661 mods minus Mod Fixer) and merge
   into a `nexus_comments_merged.jsonl` analogous to the mod.io merge.

## Security note
`bg3_scraper.py` previously had a mod.io API key hardcoded in plaintext.
Changed to read from the `MODIO_API_KEY` env var (see `.env.example`) before
this became a public repo. The old key itself was **not rotated** (user's
call) — treat it as already exposed if you find it in old local copies/zips.
