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

## Running from work: GitHub Codespaces (2026-07-22)
- Discovered the Mimecast block is **device/agent-level, not network-level**
  — it follows the laptop regardless of which network (work wifi, home wifi,
  mobile hotspot, personal VPN) it's connected to, and staying on the work
  network is required anyway for other work programs. Switching networks is
  not a viable workaround.
- Fix: run the actual browser/scrape entirely off-device, in a GitHub
  Codespace. The laptop only ever talks to `github.dev`/`vscode.dev` over
  HTTPS (the web IDE); the Codespace container itself (in Azure) makes the
  `nexusmods.com` requests, so the Mimecast agent on the laptop never sees
  that traffic at all. This is a different mechanism than "switch networks"
  — the traffic never touches the laptop's network stack in the first place.
- Added `.devcontainer/devcontainer.json`: Python 3.12 base image, the
  `desktop-lite` devcontainer feature (Xvfb + a lightweight desktop reachable
  over noVNC), `postCreateCommand` installs `requirements.txt` and runs
  `playwright install --with-deps chromium`. The Xvfb desktop means the
  script's default headed (`headless=False`) launch works unmodified in a
  Codespace with no physical display.
- Added a `--headless` flag to `nexus_deep_comments.py` (v1.6) so headless
  mode itself can finally be tested against the live site — the v1.4 note
  above theorized headed-vs-headless wasn't the actual Cloudflare signal
  (the `navigator.webdriver` patch was), but that was never confirmed
  headless against production. Default behavior (headed) is unchanged for
  existing home-network runs.
- **Codespaces testing, 2026-07-22:**
  - Step 2 (single mod, headed, `--limit 1`, mod 366 ImpUI): **passed** —
    5,565 comments, zero challenges, exact match to the home-run baseline.
    Confirms the Codespace/Azure IP isn't treated any differently by
    Cloudflare than the home connection was, and the Xvfb virtual desktop
    is sufficient for headed Chromium to behave normally.
  - Step 3 (`--headless`, mod 213 Tav's Hair Salon): **failed** — Cloudflare
    challenge re-triggered on all 3 retry attempts (0/20/60s backoffs),
    ultimately raising `PermissionError` and skipping the mod. This settles
    the question the v1.4 note left open: headless Chromium **is** an
    independent Cloudflare bot-management signal on top of the
    `navigator.webdriver` patch, not a non-factor. **Conclusion: headless
    mode does not work against Nexus; headed (via Xvfb) is required.** The
    `--headless` flag stays in the script since it's a legitimate, cheap
    way to re-test this later if Cloudflare's heuristics change, but should
    not be used for the real sweep.
  - Added `--mod-ids` (v1.7): takes an explicit comma-separated mod ID list,
    bypassing the tier CSV's file-order slicing that `--limit` does. Needed
    because the tier CSV is sorted by endorsements descending, so `--limit`
    can only ever sample from the top of the popularity distribution.
  - **Timing estimate**: tested 33 mods from the top of the list (68,099
    comments, ~1 hour) plus 11 more spread across ranks ~100-3,661 via
    `--mod-ids` (1,059 comments, ~2 min, zero challenges either batch).
    Comments-per-endorsement ratio differs between the two samples (0.082
    top-33 vs. 0.157 spread-11 — low-endorsement mods proportionally have
    *more* comments, not fewer), so extrapolating total volume across all
    3,661 mods via that ratio against the full endorsement sum (2,918,837)
    gives a **4.0-7.7 hour** range depending which ratio is used — nowhere
    near the ~5-day figure a naive flat per-mod extrapolation would give
    (that approach badly overweights the sample, since it's drawn entirely
    from the top ~1% by endorsements). Order-of-magnitude confidence only:
    "hours, not days," not a precise number.
  - Added a consecutive-failure circuit breaker (v1.8, `CONSECUTIVE_FAILURE_LIMIT
    = 5` in `nexus_deep_comments.py`): aborts the run early if 5 mods in a row
    fail outright (each already having exhausted its own 3-attempt retry),
    rather than silently grinding through the remaining mod list for hours
    if something systemic breaks (persistent block, network loss, etc.).
  - **Unattended-run plan**: idle timeout bumped to max (240 min) in personal
    Codespaces settings; launch via `nohup python3 nexus_deep_comments.py
    --resume > sweep.log 2>&1 &` + `disown` so the process survives a client
    disconnect. Deliberately *not* relying on tmux/nohup output to auto-reset
    the idle timer -- nohup's file-redirected output doesn't reach a terminal
    at all, so GitHub's idle-timeout mechanism (which resets on terminal I/O,
    per its docs) won't see it as activity. Since the estimate (4-8h) can
    exceed the 4h max idle timeout, the plan is to just check in every 2-3
    hours with `tail -n 20 sweep.log` (an actual keystroke, which does count
    as activity) rather than assume it survives fully unattended.
  - Correction found live during the actual launch: continuously watching
    with `tail -f sweep.log` in a connected terminal is a *better* fallback
    than periodic manual check-ins, since the live output itself is terminal
    activity and should reset the idle timer automatically for as long as
    the connection stays open. Only matters while actually connected --
    closing the laptop/tab still stops the output (and the idle-timeout risk
    resumes), so it doesn't replace bumping the idle timeout, just adds a
    zero-effort option when at the computer anyway.
  - **Full sweep launched 2026-07-22**: `nohup python3 nexus_deep_comments.py
    --resume > sweep.log 2>&1 &` + `disown`, resuming past the 44 already-
    tested mods (3,617 remaining). First few results confirmed the resume
    logic picked up correctly and the pattern from testing holds (occasional
    single-mod Cloudflare challenges that clear on retry, e.g. mod 3483
    Extra Gear failed all 3 attempts and will be retried by a future
    `--resume` since no sentinel gets written for real failures).

## NSFW-gated mods: plan (not yet executed, 2026-07-22)
- Confirmed gap: NSFW-tagged mods return 0 comments because Nexus hides the
  thread_id (and the rest of the Posts tab) from an anonymous/non-opted-in
  session -- not a bug, `fetch_all_comments` correctly returns `[]` when it
  can't find a thread_id, but that's indistinguishable in the output from a
  mod that genuinely has zero comments (both produce the same `_status:
  no_comments` sentinel -- there's no marker yet for *why* a mod came back
  empty).
- The tier CSV's `category` column has no adult/NSFW value (it's content-type
  categories like Gameplay/Armor/Spells), so we can't count how many of the
  3,661 are affected ahead of time -- only empirically, from sweep output.
- **Fix requires a logged-in Nexus account with "Show adult content" enabled
  in its preferences** -- this is account-level on Nexus, not a cookie an
  anonymous session can set itself. Decided: use a **throwaway account**,
  not a personal one, since its session gets reused by an automated script.
- Built ahead of time (while the main sweep was running, so as not to add a
  second concurrent Cloudflare-exposed session on the same Codespace IP
  during the big run):
  - `nexus_login_capture.py`: one-time interactive helper -- opens a real
    headed Chromium window, you log in and enable adult content by hand,
    then it saves a Playwright `storage_state` to `nexus_auth_state.json`
    (gitignored -- this is session/credential data, never committed).
  - `nexus_deep_comments.py` v1.9: `open_browser_context()` and `main()`
    take an optional `--auth-state PATH`, passed straight to
    `browser.new_context(storage_state=...)`. Unset by default (anonymous),
    so this doesn't change existing behavior.
- **Deliberately deferred, not run yet**:
  - The actual account creation + `nexus_login_capture.py` run should
    happen from home, not the Codespace -- this one-time interactive login
    doesn't need to dodge Mimecast at all (only bulk scraping does), so
    there's no reason to fight noVNC/Xvfb desktop interaction inside the
    Codespace for it. Just run the capture script locally at home, then copy
    the resulting small JSON file into the Codespace afterward.
  - Should wait until the main 3,661-mod sweep finishes before doing any of
    this, to avoid a second browser session hitting nexusmods.com from the
    same Codespace IP concurrently with the big unattended run.
  - Once available, the plan is to re-run with `--auth-state
    nexus_auth_state.json` against the mods already recorded as
    `no_comments` (not the whole sweep again) -- accepting that most will
    still correctly come back empty, rather than first building a detector
    for "was this specifically the adult-content gate."

## Next steps
1. ~~Confirm `nexusmods.com` loads normally from home.~~ Done.
2. ~~Investigate the Posts tab live via Playwright.~~ Done — endpoint, auth
   pattern, and HTML shape identified.
3. ~~Build and validate `nexus_deep_comments.py`~~ Done (v1.5) — see
   build-status section above.
4. ~~Validate the Codespaces setup~~ Done (2026-07-22) — headed works, headless
   confirmed broken, resume gap fixed, timing estimated at 4-8 hours.
5. Run the full sweep (`nohup python3 nexus_deep_comments.py --resume
   > sweep.log 2>&1 &`, all 3,661 mods minus Mod Fixer, resuming past the
   44 mods already tested) and merge into a `nexus_comments_merged.jsonl`
   analogous to the mod.io merge — though unlike mod.io there's no legacy
   partial dataset to reconcile against, so this may end up being just a
   filter pass that strips the `_status` sentinel bookkeeping lines rather
   than a true merge. **In progress as of 2026-07-22** (launched via nohup,
   see above).
6. NSFW-gated mods (see dedicated section above): create a throwaway Nexus
   account, run `nexus_login_capture.py` from home once the main sweep is
   done, copy `nexus_auth_state.json` into the Codespace, then re-run
   `nexus_deep_comments.py --auth-state nexus_auth_state.json` against the
   mods currently recorded as `no_comments`. Not started.

## Security note
`bg3_scraper.py` previously had a mod.io API key hardcoded in plaintext.
Changed to read from the `MODIO_API_KEY` env var (see `.env.example`) before
this became a public repo. The old key itself was **not rotated** (user's
call) — treat it as already exposed if you find it in old local copies/zips.
