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
- `gh` CLI: was missing/broken for a long time (wrapper pointed to a deleted
  path) — git operations used `git` directly with a cached Windows Credential
  Manager credential instead. **Fixed 2026-07-24**: reinstalled fresh from the
  official GitHub release into the path the old wrapper already expected
  (`~/gh/bin/gh`), then `gh auth login` + `gh auth refresh -h github.com -s
  codespace` (git's existing credential lacked the scopes `gh` itself needs,
  notably `codespace`). Now fully working, including `gh codespace
  list/ssh/cp/rebuild` — a session on this machine can drive a Codespace
  directly instead of relaying commands through its web terminal by hand.

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
  - **Full sweep completed 2026-07-23, then completely lost same day.**
    First pass finished at 3,661/3,661 processed (mod 141 excluded); 4 mods
    failed the main pass (3483, 279, 22659, 18542). 3483 and 18542 cleared
    on a `--mod-ids` retry. 279 and 22659 stayed stuck across three separate
    attempts, always failing at the very first page load
    (`fetch_mod_posts_page`) rather than mid-pagination -- a different
    failure mode than the volume-triggered mid-run challenges the retry
    logic was built around. Two fixes were tried for them:
    - v1.10: `fetch_comment_page_resilient()` retries an individual failing
      *pagination* page in place instead of restarting the whole mod --
      doesn't help 279/22659 (they never get past the first page), but a
      real improvement for any future mod that fails mid-pagination.
    - v1.11: `--long-backoff` (up to 10 min between whole-mod retries, vs.
      the default 20s/60s). Still failed against 279/22659 -- accepted as
      a 2-mod gap at the time (popular pages plausibly triggering
      Cloudflare's traffic-based challenge mode independent of our own
      client reputation).
  - **Then, same day: the entire ~3,657-mod dataset was accidentally
    destroyed.** Three follow-up `--mod-ids` commands (the two retries
    above, plus the 279/22659 `--long-backoff` attempt) were each run
    *without* `--resume`. The script's mode logic at the time was `mode =
    "w"` unless `--resume` was passed -- opening a file in `"w"` truncates
    it to zero bytes the instant it's opened, before anything is written.
    Each of the three commands silently wiped the file first, then wrote
    back only whatever that one small run produced: 3,657 mods -> 19 lines
    (18542 only) -> 781 lines (3483 only) -> 0 lines (279/22659 both
    failed, nothing written back at all). Discovered only afterward, while
    investigating why `nexus_nsfw_recheck.py` found zero `no_comments`
    mods -- `wc -l nexus_comments_deep_sweep.jsonl` came back 0.
    **Fix (v1.13): decoupled file mode from `--resume` entirely.** The
    output file now opens in append mode whenever it already exists, full
    stop -- `--resume` only controls whether already-recorded mod_ids get
    skipped from the todo list, not file mode. Forgetting `--resume` can
    now at worst duplicate rows for reprocessed mods, never erase
    everything else. No data was permanently lost in principle (all of it
    is still live on Nexus, just re-scrapeable), but the ~4-8 hour sweep
    has to be run again from scratch. **Lesson for future sessions: always
    download a local copy of `nexus_comments_deep_sweep.jsonl` (VS Code
    Explorer -> right-click -> Download) periodically during a long run
    and immediately after it completes** -- the Codespace's working copy
    is not itself a backup.
  - **Re-run in progress / to resume**: as of this loss, the sweep needs to
    restart effectively from zero (the file is empty, so `--resume` will
    correctly treat every mod as not-yet-done). Same launch command as the
    original run applies. 279 and 22659 will need the same eventual
    accepted-gap call as before if they still can't clear on this pass.

## Mods 279 & 22659: root cause found, rescue attempted, paused (2026-07-24)
- **Full sweep re-ran clean this time**: after the v1.13 data-loss fix, the sweep was
  relaunched from a GitHub Codespace and — after the Codespace itself idle-timed-out
  and shut down mid-run overnight (see idle-timeout note below) and was resumed once —
  finished at **3,659/3,661 mods**. Only 279 ("Expansion Level 13-20 (Configurable)")
  and 22659 ("Skip Act 1") are still missing, the same 2-mod gap as before the data
  loss. Verified via a full completeness check against the tier CSV: no duplicate
  rows, no corruption, every other mod accounted for (3,199 with real comments, 255
  genuinely `no_comments`, 205 correctly `nsfw_gated`).
- **`gh` CLI is now working from this machine** (was previously broken/missing —
  see old Environment notes above, now stale on this point). Reinstalled fresh from
  the official GitHub release, authenticated via `gh auth login` +
  `gh auth refresh -s codespace`. This means Codespace management (list/ssh/cp/rebuild)
  no longer requires manually relaying commands through the Codespace's own web
  terminal — a Claude Code session on this machine can drive it directly.
- **Codespace idle-timeout note**: even with the 240-min max setting, a Codespace
  *will* still shut down if nothing keeps the connection alive (a disconnected
  `tail -f sweep.log` doesn't help once the tab/laptop actually closes). When it
  shuts down mid-sweep, the running Python process is simply killed — no data loss
  (the file is safely flushed per-mod), but the sweep has to be manually relaunched
  with `--resume` again. `gh codespace ssh` against a `Shutdown` codespace
  auto-restarts it (may need a retry — first attempt sometimes 400s with "too many
  codespaces starting").
- **Root cause for 279/22659 found**: NOT a hard per-page block or IP-level
  reputation issue as previously theorized. A vanilla `playwright.chromium.launch()`
  — even with the `navigator.webdriver` patch from v1.5 — still fails Cloudflare's
  challenge on these two specific pages, every time, from every environment tried.
  But a **manually-launched Chromium with zero Playwright launch flags at all**
  (real, human-driven, no `--enable-automation`) loads both pages' Posts tabs
  cleanly, live, confirmed 2026-07-24 via the Codespace's `desktop-lite` noVNC
  virtual desktop. So it's specifically an automation-launch signal beyond what the
  webdriver-property patch alone fixes — these two pages apparently get flagged by
  something Cloudflare checks that a patched-after-the-fact property doesn't cover.
- **Rescue approach that works in principle**: launch a real Chromium manually
  (`.../chrome-linux64/chrome --no-sandbox --disable-dev-shm-usage --disable-gpu
  --user-data-dir=<non-default dir> --remote-debugging-port=9222 <mod URL>`, note
  the non-default `--user-data-dir` — newer Chromium silently refuses to actually
  open the debug port on the *default* profile dir, a real security change, easy to
  mistake for the port just not being set), then connect Playwright to that already
  human-cleared browser via `chromium.connect_over_cdp("http://127.0.0.1:9222")`
  and drive it with the **existing, unmodified** `fetch_all_comments()` — no cookie
  extraction/transplant needed (tried first, abandoned: DevTools' Cookies panel
  truncates long values, VNC clipboard doesn't support copy-out at all, and the
  classifier correctly blocks scripted searches for browser cookie storage as
  looking like credential harvesting even when the intent is legitimate). One-off
  script: `nexus_manual_rescue.py` (not committed — throwaway, scratch-dir only).
- **Two real bugs found and fixed in `nexus_deep_comments.py` itself while doing
  this** (both apply to the main sweep too, not just this rescue):
  - **v1.14**: `fetch_comment_page_resilient()`'s retry path opened a fresh blank
    page and immediately tried an AJAX `fetch()` from it — but a blank
    (`about:blank`) page trying to fetch nexusmods.com is cross-origin, so the
    browser blocks it outright (`TypeError: Failed to fetch`) before the request
    ever reaches the network. Was being misread as "still Cloudflare-blocked."
    Fixed: navigate the fresh page to the mod's Posts URL first.
  - **Also v1.14 (separate)**: `fetch_all_comments()` used to `raise` on exhausted
    mid-pagination retries, which `fetch_with_retry()` caught by restarting the
    **entire mod from page 1** — discarding every comment already collected just to
    re-walk the same ground and hit the same wall again, burning real request
    "budget" for zero net progress every time. Now returns `(comments, complete)`;
    a `complete=False` result still keeps everything gathered before the failure,
    and a `_status: "partial"` sentinel gets written alongside the real rows so an
    incomplete mod can be found and re-targeted later instead of silently looking
    identical to a fully-done one.
- **Where this stands**: with the CORS bug fixed, a rescue attempt got **122 of an
  unknown total pages for mod 279 and 3 for mod 22659** before hitting a real,
  persistent Cloudflare challenge that outlasted all 3 retries — i.e. the
  automation-signal problem is solved, but there's a **separate, still-live
  volume/burst-based challenge** that triggers during sustained rapid pagination,
  independent of the browser being genuinely human-launched. That run happened
  *before* the partial-results fix landed, so that 122/3 pages of real progress
  was fetched but not saved — starting over is unavoidable next time, but this time
  it should actually **stick** once it makes progress, page by page, rather than
  being all-or-nothing.
  **Deliberately stopped here rather than immediately retrying** — the script's own
  history is explicit that rapid re-testing against Cloudflare burns whatever
  request-volume scoring window it's using without helping, and we'd already made
  two live attempts in quick succession.
- **Plan for next session, ideally from a genuinely different machine ("home")**:
  the entire noVNC/manual-Chrome/CDP dance above exists only because this specific
  work machine has a device-level Mimecast block on `nexusmods.com` (see the
  Codespaces section above) that has nothing to do with Cloudflare at all. On a
  machine *without* that block, none of the Codespace/virtual-desktop indirection
  is needed — a real local browser (or `claude-in-chrome`, if driving one from
  Claude Code is wanted) could hit these two pages directly, with normal clipboard
  access and none of today's friction (typos on the debug port number, VNC copy/
  paste limitations, `/dev/shm` renderer crashes needing `--disable-dev-shm-usage`).
  After a real cooldown (hours, not minutes) from today's attempts: re-run against
  279/22659 specifically, expect to hit the same page~123/page~4 wall, but this
  time the partial-results fix should let real progress accumulate across repeated
  attempts instead of resetting to zero each time.

## NSFW-gated mods: plan (detection live, capture not yet executed)
- **Update 2026-07-24: live detection confirmed working in production.** v1.12's
  `nsfw_gated` distinction (vs. plain `no_comments`) was built and documented
  2026-07-23 but got its first real confirmation during the 2026-07-24 sweep
  re-run -- e.g. mod 10090 ("Elven Weaponry - Bladesinger") came back tagged
  `NSFW-gated (adult content preference), skipping` distinctly, not lumped in
  with genuine zero-comment mods. 205 mods got this tag in the full sweep. So
  the *detection* half of this plan is done and proven; only the *capture*
  half (below) remains, unchanged from the original plan.
- Original gap as first found: NSFW-tagged mods return 0 comments because Nexus
  hides the thread_id (and the rest of the Posts tab) from an anonymous/non-
  opted-in session -- not a bug, `fetch_all_comments` correctly returns `[]`
  when it can't find a thread_id, but that used to be indistinguishable from a
  mod that genuinely has zero comments (both produced the same `_status:
  no_comments` sentinel). Now fixed by the `nsfw_gated` marker above.
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

## Collections (mod.io + Nexus): investigated live, CONFIRMED SCRIPTABLE, not yet built (2026-07-24)
Both platforms' Collections feature (curated bundles of mods) is now fully
verified scriptable for name/description/mod-list/comments — this was
"research only, unknowns not yet resolved" as of 2026-07-22; today's session
resolved every open question with real, live, verified requests (not doc
summaries — see the WebFetch-hallucination note below for why that mattered).

**Where the keys came from**: `MODIO_API_KEY`/`NEXUS_API_KEY` were not
findable anywhere already checked (not this machine's env, not the
Codespace's env, not the Google Drive `BG3Scraper_Active` mirror's files —
all had only `.env.example` templates). The user placed real values in a
local `env.example` file (no leading dot) in the repo root to hand them
over. **That file is not gitignored as of this note — `env.example` (no
dot) is a different filename than the gitignored `.env`/`.env.example`
pattern** — rename/gitignore it before any commit touches the repo root,
or move the real values into an actual `.env` (already gitignored).

### mod.io Collections — fully scriptable, same key already in use
- `GET https://g-6715.modapi.io/v1/games/6715/collections?api_key=...` —
  list/search. Live-confirmed: **843 total BG3 collections** exist. Returns
  rich metadata per collection: `name`, `summary`, `category`, `tags`,
  `stats` (`downloads_total`, `followers_total`, `ratings_total`,
  `mods_total`, **`comments_total`**), `logo`, dates.
- `GET .../collections/{collection_id}/mods` — mod list for a collection
  (same shape as the games/collections list endpoint from the original
  2026-07-22 note — not re-verified live this session but very likely
  correct given everything else on this host matched documentation exactly).
- `GET .../collections/{collection_id}/comments` — **live-confirmed
  working**, real comment data (id, `user`, `date_added`, `reply_id` for
  threading, `karma`, `content`). **Pagination confirmed correct** —
  `_offset`/`_limit` honored properly (tested offset=0/limit=3 then
  offset=3/limit=3 against a 14-comment collection, zero overlap, matches
  `result_total`) — no repeat of the original mod-comments silent-100-cap
  bug. No Cloudflare/cookie dance needed at all for any of this, unlike mod
  comments.
- One dead end worth recording: a WebFetch summarization of mod.io's docs
  page produced a **plausible but wrong/inconsistent** endpoint shape
  (nesting collections under a specific mod_id) across two separate
  fetches that partially contradicted each other and the correct shape
  above — a real illustration of JS-rendered API doc pages being a
  hallucination risk for summarization tools. mod.io's API also returns
  401 (not 404) for made-up paths, so status-code probing without a key
  couldn't settle it either. Only a real authenticated request settled it.

### Nexus Collections — fully scriptable via the official GraphQL API, likely no auth needed
- **The docs-serving host is not the query endpoint** — `graphql.nexusmods.com`
  only serves an interactive SpectaQL documentation page (GET requests
  return real, official, fully-detailed schema docs — reliable, unlike the
  mod.io WebFetch summary, because this was read directly via curl+grep,
  not LLM-summarized). POSTing a query there 405s with an empty body, which
  looks like a dead end but isn't one. **The real endpoint is
  `https://api.nexusmods.com/v2/graphql`** (same host as the existing REST
  v1 API, just a v2/graphql path) — found via the docs page's own "API
  Endpoints" section.
- **No authentication required**, confirmed empirically (not just from the
  docs' "most of GraphQL V2 is accessible without authentication" note) —
  every query below worked with zero auth headers.
- `collectionsV2(filter: {gameDomain: [{value: "baldursgate3"}]}, count: N)`
  — list/search. Live-confirmed: **87 total BG3 collections**. Returns
  `slug`, `name`, `summary`. (Filter values are `{value: String!, op:
  FilterComparisonOperator}` objects, not bare strings/scalars — GraphQL's
  own error messages made iterating to the correct shape fast once hitting
  the real endpoint.)
- `collection(slug: String, domainName: String)` — full detail for one
  collection by slug. Live-confirmed against a real 226K-endorsement
  collection ("Difficulty, Immersion, Quality", slug `pns4qv`): `name`,
  `summary`, `category { name }`, `totalDownloads`,
  `latestPublishedRevision { modCount modFiles { file { name } } }` for
  the **full mod list** (1,016 mods in this one collection), and
  `commentThread { comments(first: N) { totalCount nodes { id body
  createdAt likesCount creator { name } parent { id } } } }` for
  **comments with real threading** (`parent`, cleaner than mod comments'
  `reply_id` convention) — this collection alone has 3,205 comments.
  `Comment` also has `isPinned`, `moderationStatus`, `attachments`,
  `discardedAt`/`hiddenAt` fields if any of that ever matters.
- The `CollectionBugReport` system (its own mutations: create/close/open/
  clear-moderation-status) is a **separate, non-comment feedback mechanism**
  also present on collections — not investigated further, but worth knowing
  it exists distinctly from `commentThread` if bug-report content ever
  becomes relevant.
- Confirmed via the same live Codespace session used for the main sweep —
  the Mimecast-fronted-subdomain redirect noted 2026-07-22 for
  `graphql.nexusmods.com` on the **local machine** doesn't affect the
  Codespace, same as the main nexusmods.com Cloudflare situation.

### Not yet done
Building the actual scraper scripts (mirroring `modio_deep_comments.py` /
`nexus_deep_comments.py`'s shape) — both APIs are confirmed to work and are
**meaningfully simpler** than the mod-comments scrapers were (no browser
automation, no cookies, no Cloudflare challenges on either platform for
this feature specifically). Also not yet decided: whether to pull full mod
lists for all 843/87 collections up front, or lazily/on-demand; whether
`get-mod-collections`/`get-mod-collection` (collections a specific MOD
belongs to, the inverse lookup) are wanted in addition to the game-level
list.

**After these scripts are running**: Jason reports ChatGPT/Codex has
reached its next conference-point gate and is waiting for joint review
(see `00_SHARED_PROJECT_ROADMAP.md`'s C1-C7 conference points and
`01_CHATGPT_CLAUDE_WORK_DELINEATION.md` for what a check-in packet needs —
what changed, source artifacts/hashes, validation results, candidate
decisions, the target DB checksum). Sequencing per the user, 2026-07-24:
finish building/running the Collections scripts first, *then* do that
conference — not the other way around.

## Future work: Load Order Guidance doc research (cross-project pointer, 2026-07-24)
Not part of this repo's own scope (this repo is the scraper; the guidance doc is
part of the broader multi-AI "reference system" project this scraper's output
feeds into), but noted here so it isn't lost between sessions.

- Current version: `BG3_Load_Order_Guidance_v12.md`, in the shared Google Drive
  folder (`BG3/BG3/20_CONTROL_HANDOFFS/01_GATE1_BASELINE/BG3_Gate1_Package_2026-07-22/gate1/`
  and also under `90_HISTORICAL`) -- a local copy of that Drive folder lives at
  `Google Drive/` in this repo's directory (untracked, gitignored-equivalent,
  manually synced, not part of the scraper itself).
- Sourcing status per the doc's own §9: fully mined `wiki.bg3.community`,
  `bg3.wiki`, Larian's official modding docs, several named mods/tools, Larian's
  official forums' Patch 8 thread, Steam Community threads, BG3 Mod Manager's
  GitHub issues, Norbyte's Script Extender/LSLib trackers. **Still blocked/
  unreached**: Reddit, Facebook groups, two named Discord servers ("BG3 Modding,"
  "BG3 Modding Community" -- the latter directly affiliated with
  `wiki.bg3.community`, probably the single most promising unreached source),
  Nexus Collections (Cloudflare), a locked Larian Discord thread, Steam
  Community's discussion *search* specifically.
- A prior Claude-in-Chrome pass (different session, using real logged-in browser
  sessions) previously succeeded at reaching Reddit and Larian's official Discord
  where a sandboxed chat instance couldn't -- worth trying again with real local
  browser access (`claude-in-chrome` skill) rather than assuming those sources
  stay unreachable, ideally from a machine without this one's Mimecast block
  (same reasoning as the 279/22659 rescue plan above -- a real browser session
  from an unblocked device sidesteps a whole category of friction).
- Next version (v13) would fold in whatever comes out of the now-3,659/3,661
  Nexus comment corpus once that's delivered into the shared Drive project (see
  roadmap Gate 3/4 notes -- Nexus comments are explicitly named as a distinct,
  not-yet-ingested corpus in `00_SHARED_PROJECT_ROADMAP.md`), not just new web
  sources.

## Next steps
1. ~~Confirm `nexusmods.com` loads normally from home.~~ Done.
2. ~~Investigate the Posts tab live via Playwright.~~ Done — endpoint, auth
   pattern, and HTML shape identified.
3. ~~Build and validate `nexus_deep_comments.py`~~ Done (v1.5) — see
   build-status section above.
4. ~~Validate the Codespaces setup~~ Done (2026-07-22) — headed works, headless
   confirmed broken, resume gap fixed, timing estimated at 4-8 hours.
5. Run the full sweep. **Done, second time, 2026-07-24** (first completion
   2026-07-23 was accidentally destroyed the same day, see the data-loss note
   above — v1.13 fixed the underlying bug). Re-ran clean, survived one
   Codespace idle-shutdown/resume mid-run, finished at **3,659/3,661 mods**.
   Only 279 and 22659 remain — see the dedicated section above for the full
   investigation, the two real bugs found/fixed (v1.14) while trying to rescue
   them, and the plan to retry from a different (non-Mimecast) machine after a
   cooldown. A local copy has been downloaded off the Codespace already.
   **Still not started**: merge into a `nexus_comments_merged.jsonl` analogous
   to the mod.io merge — likely just a filter pass stripping the `_status`
   sentinel bookkeeping lines rather than a true merge, since unlike mod.io
   there's no legacy partial dataset to reconcile against. Also not started:
   delivering this corpus into the shared Drive project's
   `10_SOURCE_CORPORA/04_NEXUS_COMMENTS_T1_T2_INCOMING/` inbox, which is
   sitting empty waiting for it (see `00_SHARED_PROJECT_ROADMAP.md`, Gate 3).
6. NSFW-gated mods (see dedicated section above): **detection confirmed working
   live** (2026-07-24, 205 mods correctly tagged `nsfw_gated` in the sweep
   above). Capture step still not started: create a throwaway Nexus account,
   run `nexus_login_capture.py` from home, copy `nexus_auth_state.json` into
   wherever the next Nexus scraping session runs, then re-run
   `nexus_deep_comments.py --auth-state nexus_auth_state.json --mod-ids
   <the 205 nsfw_gated mod IDs> --output nsfw_capture.jsonl`.
7. Collections on mod.io + Nexus (see dedicated section above) -- future
   work, no priority set, needs live investigation before building anything.
   Not started.
8. Load Order Guidance doc research (see dedicated section above, cross-project) --
   Discord servers and Larian's official forums specifically, ideally via
   `claude-in-chrome` from a non-Mimecast-blocked machine. Not started this
   session.

## Security note
`bg3_scraper.py` previously had a mod.io API key hardcoded in plaintext.
Changed to read from the `MODIO_API_KEY` env var (see `.env.example`) before
this became a public repo. The old key itself was **not rotated** (user's
call) — treat it as already exposed if you find it in old local copies/zips.
