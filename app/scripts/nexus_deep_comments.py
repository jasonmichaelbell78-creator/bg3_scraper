#!/usr/bin/env python3
"""
nexus_deep_comments.py  v1.15  (investigation 2026-07-21/22, see CLAUDE.md)
================================================================================
Fetches full comment/Posts threads for BG3 Nexus mods. Nexus's REST v1 API has
no comments endpoint at all (nexus_bg3_scraper.py's comment fetch always 404s).
This script goes after the same data the website itself renders, live.

Auth strategy -- NOT the same as modio_deep_comments.py:
  v1.0 tried the mod.io pattern (mint Cloudflare cookies with one Playwright
  load, then reuse them via plain `requests`) and it failed every time: Nexus
  fronts this with a *full* Cloudflare JS challenge ("Just a moment...",
  `cf_clearance` cookie), not the lighter `__cf_bm`-only bot-management mod.io
  uses. `cf_clearance` is validated against the requesting client's TLS/JS
  fingerprint, not just the cookie value -- Python's `requests` doesn't match
  a real browser's fingerprint, so it gets challenged again and 403s.
  v1.1 tried keeping ONE Playwright page open for the whole run and reusing
  it for every mod's `page.goto()` -- also failed: the FIRST navigation on a
  fresh page always passes, but re-using that same page object for a second,
  third, etc. top-level navigation gets challenged again (looks like a
  behavioral/sequential-navigation heuristic, not a fingerprint check).
  Fix (this version): keep one browser CONTEXT open for the whole run (so
  `cf_clearance`/cookies persist), but open a brand new page (tab) for each
  mod and close it afterward. Empirically reliable across repeated mods.
  AJAX comment-pagination requests (`page.evaluate(fetch(...))`) reuse that
  same per-mod page and don't trigger the issue -- only fresh top-level
  navigations on a stale page do.
  v1.2 also blocked image/font/css/media requests via context.route() to
  speed things up. A same-mod, same-session A/B test strongly implicated
  this as A cause (route-blocking enabled -> 403 "Just a moment...";
  removed, nothing else changed -> 200) -- a browser that never requests
  its own stylesheets/fonts is a plausible automation signal to Cloudflare.
  v1.3 removes it. BUT a follow-up --limit 3 run failed on all 3 mods
  again immediately afterward, including one that had just individually
  succeeded -- so route-blocking is not the *whole* story. The pattern
  across this entire debugging session: isolated single-page tests tend to
  succeed; anything that fires several requests back-to-back (a --limit 3
  run, or a rapid sequence of one-off debug tests) tends to fail partway
  through. That looks like cumulative, volume-based IP scoring layered on
  top of the route-blocking issue -- and critically, every test run (pass
  or fail) adds to that same tally, so aggressive re-testing makes the
  next test *less* likely to succeed, not more.
  UNRESOLVED as of 2026-07-21. Do not debug this by rapid iteration --
  each attempt costs "budget" against whatever scoring window Cloudflare
  is using. Next session: let it sit for a genuinely long cooldown (hours,
  not tens of minutes), then test with exactly ONE page load, not a
  --limit N script run (which is itself several-to-many requests once
  comment pagination is included).
  v1.4 switches launch(headless=True) -> headless=False. Cloudflare's bot
  management is known to fingerprint headless Chrome specifically (missing
  browser internals, navigator.webdriver, etc.), which is a separate signal
  from the volume/IP-scoring theory above -- this doesn't replace the need
  for a long cooldown, it's an additional variable to test once the cooldown
  has actually elapsed. UNTESTED against the live site as of this edit.
  v1.10 (2026-07-23, full 3,661-mod sweep post-mortem): two large/popular
  mods (279, 22659) failed identically -- "Cloudflare challenge persisted
  after 3 attempts" -- across three independent sessions (the main sweep
  plus two separate --mod-ids retries), while every other mod that failed
  once cleared on a later retry. The old fetch_with_retry() restarted a
  failed mod entirely from scratch (fresh thread-id lookup, pagination back
  to page 1) on every attempt, discarding any comments already collected.
  Combined with the v1.3 volume/burst-triggered-challenge finding, that
  means a mod with enough pages to trip the heuristic before finishing one
  full pass could never succeed, no matter how many retries -- every
  attempt re-spends the same budget getting back to the same failure point.
  Fix: fetch_comment_page_resilient() retries an individual failing page in
  place (backoff + fresh page, same page_num) instead of the whole mod, so
  partial pagination progress from earlier pages is never thrown away.
  v1.12 (2026-07-23): live-captured mod 97's anonymous HTML and found an
  unambiguous, site-authored marker for the adult-content preference gate --
  <h3 id="Notice9216-title">Adult content disabled</h3> plus a paragraph
  ("This page is hidden because adult content is turned off in your
  preferences..."). Before this, a mod hidden by that gate and a mod that
  genuinely has zero comments were indistinguishable -- both hit the "no
  thread_id found" branch and returned []. Now that branch checks for
  ADULT_GATE_MARKER first and raises NSFWGatedError, which main() writes as
  a distinct `_status: "nsfw_gated"` sentinel instead of `"no_comments"`.
  Also added --output to redirect the output file, so the existing
  no_comments mods can be re-checked into a separate file (reclassifying
  nsfw_gated ones) without --resume's "already done" skip logic getting in
  the way, and without --resume's absence silently truncating the real
  sweep output (mode defaults to "w" without --resume).
  v1.13 (2026-07-23, costly lesson): the v1.12 "mode defaults to w without
  --resume" behavior above is exactly what destroyed the entire ~3,657-mod
  sweep output. Three separate --mod-ids retry commands were run against
  the main output file without --resume; each one silently truncated it
  before writing, and the last of the three (both target mods failing,
  nothing written back) left the file completely empty. Fix: the output
  file is now opened in append mode whenever it already exists, full stop
  -- --resume no longer controls file mode at all, only whether already-
  recorded mod_ids get skipped from the todo list. Forgetting --resume now
  produces duplicate rows for reprocessed mods at worst, never data loss.
  v1.14 (2026-07-24): 279 and 22659, previously an accepted 2-mod gap, turned
  out to be an automation-signal issue, not a hard per-page or IP-reputation
  block -- confirmed by manually launching Chromium WITHOUT any Playwright
  launch flags (no --enable-automation, real navigator.webdriver=false from
  birth, not just patched post-launch) and loading both mods' Posts tabs
  live via a real, human-driven session: both loaded cleanly, no challenge.
  Rescued via a one-off script (nexus_manual_rescue.py, not part of the main
  sweep) that connects to that already-running, already-cleared browser over
  its --remote-debugging-port via playwright.chromium.connect_over_cdp() and
  drives it with fetch_all_comments() unchanged. That rescue surfaced a real,
  separate bug in fetch_comment_page_resilient(): its retry path opened a
  fresh blank page and immediately tried an AJAX fetch() from it without
  navigating it to the mod's Posts URL first, so the fetch was cross-origin
  from about:blank and the browser blocked it outright ("TypeError: Failed
  to fetch") rather than the request ever reaching Cloudflare. Fixed above.
  This bug was latent in every run to date, not new -- it just requires a
  mid-pagination challenge to trigger, which is rare, and every prior mod
  that failed happened to fail at the whole-mod level (handled by the
  unaffected fetch_with_retry() / fresh-navigation path) rather than mid-
  pagination.
  v1.15 (2026-07-25): folds nexus_manual_rescue.py's approach (previously a
  throwaway, uncommitted one-off) into the main script as --connect-cdp,
  since it's a real, reusable fix rather than a single-incident workaround.
  Also adds --page-delay to override the flat 0.5s REQUEST_DELAY pace
  between pagination requests -- a second, independent lever for 279/22659-
  style mods, since the automation-signal fix (--connect-cdp) and the
  volume/burst-trigger issue (v1.3 finding) are separate mechanisms and both
  may need addressing together on a mod that fails at high page counts.

How the data actually comes back (different from mod.io -- HTML, not JSON):
  - A mod's Posts tab (`?tab=posts`) is server-rendered: the first page of
    comments is already in the normal page HTML, along with the thread_id
    needed for further pagination (not derivable from mod_id alone).
  - Further pages come from a legacy AJAX widget:
      GET /Core/Libs/Common/Widgets/CommentContainer
          ?RH_CommentContainer=search_text:,game_id:3474,object_id:{mod_id},
           object_type:1,thread_id:{thread_id},tabbed:1,skip_opening_post:0,
           display_title:0,user_is_blocked:false,comment_id:0,searchable:true,
           page_size:10,page:{page}
    Note the single query param with an unencoded comma/colon body -- that's
    the site's own literal serialization, not standard query encoding.
  - `page_size` is NOT honored server-side (tested 10/25/50/75/100 -- always
    returns the same ~10 top-level comments per page). Pagination has to walk
    one page at a time.
  - Response is an HTML fragment. Each comment is `<li class="comment" id=
    "comment-{id}">`, with replies nested inside a child `<ol class=
    "comment-kids">` of the same shape (recursive).

USAGE:
  py nexus_deep_comments.py
  py nexus_deep_comments.py --limit 5     # test on first 5 mods
  py nexus_deep_comments.py --resume      # skip mods already in the output file
  py nexus_deep_comments.py --headless    # run headless instead of the default headed window
                                           # (see .devcontainer/ for running this in GitHub Codespaces,
                                           # which has no real network-level path to nexusmods.com --
                                           # a virtual desktop (Xvfb via the desktop-lite devcontainer
                                           # feature) is provided so headed mode also works there)
  py nexus_deep_comments.py --mod-ids 9117,14349,3405   # spot-check specific mods regardless of
                                                         # their position in the tier CSV
  py nexus_deep_comments.py --auth-state nexus_auth_state.json --mod-ids 4752,6045
                                           # re-check specific mods with a logged-in, adult-content-
                                           # enabled session (see nexus_login_capture.py) instead of
                                           # the default anonymous one
  py nexus_deep_comments.py --mod-ids 4752,6045 --output nsfw_recheck.jsonl
                                           # re-check specific mods into a SEPARATE output file --
                                           # needed for the no_comments -> nsfw_gated reclassification
                                           # pass, since --resume against the main sweep file would
                                           # just skip mods that already have any sentinel, and
                                           # omitting --resume against the main file would truncate it
================================================================================
"""

import argparse
import csv
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import BrowserContext, Page, sync_playwright

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent.parent  # repo root -- kept for any future consumers
TIER_CSV = SCRIPT_DIR / "BG3_Nexus_Tier1_Tier2_Mods.csv"
DATA_DIR = BASE_DIR / "data" / "nexus"
DATA_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE = DATA_DIR / "nexus_comments_deep_sweep.jsonl"

GAME_DOMAIN = "baldursgate3"
GAME_ID = 3474
OBJECT_TYPE = 1  # "mod" content type
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36")
REQUEST_DELAY = 0.5

# BG3 Mod Fixer: outdated, no longer necessary or used by the community
# (large historical download count, but superseded since patch 7/8) --
# user's call, 2026-07-21. Excluded from the sweep entirely.
EXCLUDED_MOD_IDS = {141}

THREAD_ID_RE = re.compile(r'thread_id["\s:=]+"?(\d+)"?')
COMMENT_COUNT_RE = re.compile(r'data-comment-count="(\d+)"')
CHALLENGE_MARKERS = ("Just a moment", "cf-mitigated")
# Site-authored copy shown in place of the Posts tab when the viewer's session hasn't
# opted into adult content -- confirmed live on mod 97 (2026-07-23):
#   <h3 id="Notice9216-title">Adult content disabled</h3>
#   <p id="Notice9216-paragraph">This page is hidden because adult content is turned
#   off in your preferences...
# Distinguishes "hidden by the NSFW gate" from "genuinely has zero comments" -- both
# otherwise produce the same "no thread_id found" result with no way to tell them apart.
ADULT_GATE_MARKER = "Adult content disabled"


class NSFWGatedError(Exception):
    """Raised when a mod's Posts tab is hidden by Nexus's adult-content preference gate
    (anonymous/non-opted-in session), not because the mod genuinely has zero comments."""


def load_mod_list() -> list[dict]:
    mods = []
    with open(TIER_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            mod_id = int(row["nexus_mod_id"])
            if mod_id in EXCLUDED_MOD_IDS:
                continue
            mods.append({"mod_id": mod_id, "name": row["mod_name"], "url": row["nexus_url"]})
    return mods


def open_browser_context(playwright, headless: bool = False, auth_state: str | None = None):
    # A vanilla playwright.chromium.launch() reports navigator.webdriver = True
    # -- confirmed locally (2026-07-22) and almost certainly the real cause of
    # the challenges seen in v1.0-v1.4, not headless state or IP/volume scoring:
    # the working Playwright MCP browser used during this whole investigation
    # reports navigator.webdriver = False. Patch it the standard way, before
    # any page script runs.
    browser = playwright.chromium.launch(headless=headless)
    # auth_state (see nexus_login_capture.py) is a logged-in session that can see
    # adult-content-gated mods -- an anonymous context never gets a thread_id for
    # those, so fetch_all_comments() correctly but unhelpfully returns [].
    context = browser.new_context(user_agent=UA, storage_state=auth_state)
    context.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => false });")
    return browser, context


def connect_cdp_context(playwright, cdp_url: str):
    """Attaches to an already-running, manually-launched Chrome (no --enable-automation,
    no Playwright launch() at all) via its --remote-debugging-port, instead of starting a
    new Playwright-controlled browser. For mods 279/22659 (see v1.14 note above): even the
    patched-navigator.webdriver open_browser_context() above still gets challenged on these
    two specific pages, every time -- but a genuinely human-launched Chrome loads them
    cleanly. Reuses whatever profile/cookies that Chrome window already has (e.g. point it
    at nexus_login_capture.py's PROFILE_DIR to inherit that already-authenticated session
    for free, no storage_state injection needed)."""
    browser = playwright.chromium.connect_over_cdp(cdp_url)
    context = browser.contexts[0]
    return browser, context


def new_page(context: BrowserContext) -> Page:
    """A fresh page (tab) per mod -- reusing one page for repeated top-level
    navigations reliably re-triggers Cloudflare's challenge; a new page in the
    same context (so cookies persist) does not."""
    return context.new_page()


def is_challenge_page(html: str) -> bool:
    return any(marker in html for marker in CHALLENGE_MARKERS)


def parse_comments(html: str) -> list[dict]:
    """Extracts every comment (top-level and nested replies) from a page or AJAX fragment."""
    soup = BeautifulSoup(html, "html.parser")
    results = []
    for li in soup.find_all("li", class_="comment"):
        cid = li.get("id", "")
        if not cid.startswith("comment-"):
            continue
        comment_id = cid.split("-", 1)[1]

        parent_li = li.find_parent("li", class_="comment")
        parent_id = parent_li["id"].split("-", 1)[1] if parent_li else None

        user_a = li.select_one(".comment-user")
        user_url = user_a["href"] if user_a and user_a.has_attr("href") else None
        name_a = li.select_one(".comment-name a")
        username = name_a.get_text(strip=True) if name_a else None

        time_el = li.select_one("time.dst-date-adjust")
        ts_unix = int(time_el["data-date"]) if time_el and time_el.has_attr("data-date") else None
        ts_text = time_el.get_text(strip=True) if time_el else None

        content_el = li.select_one(f"#comment-content-{comment_id}") or li.select_one(".comment-content-text")
        text = content_el.get_text(" ", strip=True) if content_el else ""

        results.append({
            "comment_id": comment_id,
            "parent_comment_id": parent_id,
            "username": username,
            "user_url": user_url,
            "is_sticky": "comment-sticky" in li.get("class", []),
            "timestamp_unix": ts_unix,
            "timestamp_text": ts_text,
            "text": text,
        })
    return results


def fetch_mod_posts_page(page: Page, mod_id: int) -> str:
    url = f"https://www.nexusmods.com/{GAME_DOMAIN}/mods/{mod_id}?tab=posts"
    resp = page.goto(url, wait_until="domcontentloaded", timeout=30000)
    if resp is not None and resp.status == 404:
        raise FileNotFoundError("mod not found")
    html = page.content()
    if is_challenge_page(html):
        raise PermissionError("Cloudflare challenge re-triggered")
    return html


def fetch_comment_page(page: Page, mod_id: int, thread_id: str, page_num: int) -> str:
    result = page.evaluate(
        """async ({ gameId, objectType, modId, threadId, pageNum, referer }) => {
            const qs = `RH_CommentContainer=search_text:,game_id:${gameId},object_id:${modId},`
                + `object_type:${objectType},thread_id:${threadId},tabbed:1,skip_opening_post:0,`
                + `display_title:0,user_is_blocked:false,comment_id:0,searchable:true,`
                + `page_size:10,page:${pageNum}`;
            const url = `https://www.nexusmods.com/Core/Libs/Common/Widgets/CommentContainer?${qs}`;
            const resp = await fetch(url, {
                headers: { 'X-Requested-With': 'XMLHttpRequest', 'Referer': referer },
            });
            return { status: resp.status, text: await resp.text() };
        }""",
        {
            "gameId": GAME_ID,
            "objectType": OBJECT_TYPE,
            "modId": mod_id,
            "threadId": thread_id,
            "pageNum": page_num,
            "referer": f"https://www.nexusmods.com/{GAME_DOMAIN}/mods/{mod_id}?tab=posts",
        },
    )
    if result["status"] == 403 or is_challenge_page(result["text"]):
        raise PermissionError("Cloudflare challenge re-triggered")
    return result["text"]


def fetch_comment_page_resilient(context: BrowserContext, page_box: list[Page], mod_id: int,
                                  thread_id: str, page_num: int, backoffs=None) -> str:
    """Fetches one AJAX comment page. On a Cloudflare challenge, backs off and swaps in a
    fresh page (page_box[0]) before retrying the SAME page_num -- unlike fetch_with_retry's
    whole-mod restart, this doesn't discard comments already collected from earlier pages,
    since that accumulator lives in the caller (fetch_all_comments), not here.
    Added after 279 and 22659 (both large, popular mods) failed identically across three
    separate sweep/retry sessions while every other mod eventually cleared -- consistent
    with the v1.3 finding that Cloudflare's challenge is volume/burst-triggered: a mod with
    enough pages to trip that heuristic before finishing a full top-to-bottom pass could
    never succeed under the old scheme, since every retry restarted at page 1 and re-spent
    the same request budget getting back to the same place it failed before."""
    backoffs = backoffs if backoffs is not None else CHALLENGE_BACKOFFS
    for attempt, backoff in enumerate(backoffs, start=1):
        if backoff:
            print(f"    page {page_num}: Cloudflare challenge, backing off {backoff}s (attempt {attempt})...")
            time.sleep(backoff)
        try:
            return fetch_comment_page(page_box[0], mod_id, thread_id, page_num)
        except PermissionError:
            page_box[0].close()
            page_box[0] = new_page(context)
            # The AJAX fetch() below runs from page_box[0]'s own JS context, so a fresh
            # blank page must be navigated to the mod's Posts URL first -- otherwise the
            # fetch is cross-origin from about:blank and the browser blocks it outright
            # ("TypeError: Failed to fetch", not a Cloudflare challenge) rather than ever
            # reaching the network. Found 2026-07-24 rescuing mods 279/22659: both got
            # past the initial-load block on a manually-launched browser but then hit
            # this exact bug on their first mid-pagination retry.
            try:
                fetch_mod_posts_page(page_box[0], mod_id)
            except (PermissionError, FileNotFoundError):
                pass  # the retry loop's next fetch_comment_page attempt will surface this
            continue
    raise PermissionError(f"Cloudflare challenge persisted after {len(backoffs)} attempts on page {page_num}")


def fetch_all_comments(context: BrowserContext, mod_id: int, page_delay: float = None,
                        backoffs=None) -> tuple[list[dict], bool]:
    """Returns (comments, complete). complete=False means pagination hit a Cloudflare
    challenge that outlasted fetch_comment_page_resilient()'s retries -- comments holds
    whatever was successfully gathered before that point, not the mod's full comment set.
    Added 2026-07-24 rescuing mods 279/22659: previously a persistent mid-pagination
    challenge raised PermissionError here, which fetch_with_retry() caught by restarting
    the ENTIRE mod from page 1 -- discarding all comments already collected and re-walking
    the same pages just to hit the same wall again, burning Cloudflare request "budget"
    for zero net progress. Returning partial results instead means at least the pages
    that did succeed aren't thrown away.
    page_delay overrides the module-level REQUEST_DELAY between successful pagination
    fetches -- added for 279/22659 style mods, where the default 0.5s pace between
    requests is a plausible trigger for Cloudflare's volume/burst-based challenge (a
    separate mechanism from the automation-signal issue open_browser_context()/
    connect_cdp_context() address -- see v1.14 note above)."""
    page_delay = page_delay if page_delay is not None else REQUEST_DELAY
    page_box = [new_page(context)]
    try:
        first_page_html = fetch_mod_posts_page(page_box[0], mod_id)

        thread_match = THREAD_ID_RE.search(first_page_html)
        if not thread_match:
            if ADULT_GATE_MARKER in first_page_html:
                raise NSFWGatedError("adult content preference gate")
            return [], True  # no Posts/comments on this mod
        thread_id = thread_match.group(1)

        count_match = COMMENT_COUNT_RE.search(first_page_html)
        reported_count = int(count_match.group(1)) if count_match else 0
        if reported_count == 0:
            return [], True

        seen_ids = set()
        comments = []
        for c in parse_comments(first_page_html):
            if c["comment_id"] not in seen_ids:
                seen_ids.add(c["comment_id"])
                comments.append(c)

        page_num = 2
        # reported_count is total comments+replies, so it's a safe (loose) upper bound
        # on the number of top-level pages -- real stopping signal is an empty page.
        max_pages = reported_count + 1
        complete = True
        while page_num <= max_pages:
            try:
                html = fetch_comment_page_resilient(context, page_box, mod_id, thread_id, page_num,
                                                      backoffs=backoffs)
            except PermissionError:
                complete = False
                break
            batch = parse_comments(html)
            new_ids = [c for c in batch if c["comment_id"] not in seen_ids]
            if not new_ids:
                break
            for c in new_ids:
                seen_ids.add(c["comment_id"])
                comments.append(c)
            time.sleep(page_delay)
            page_num += 1

        for c in comments:
            c["thread_id"] = thread_id
        return comments, complete
    finally:
        page_box[0].close()


CHALLENGE_BACKOFFS = (0, 20, 60)  # seconds before each attempt; first attempt has no wait
# For mods that fail even the short backoffs on the very first page load rather than
# mid-pagination (279, 22659 -- see v1.10 note above): failing at fetch_mod_posts_page()
# on a brand-new page/context means this isn't the mid-pagination burst pattern
# fetch_comment_page_resilient() was built for, and 20s/60s clearly isn't enough room for
# whatever's gating these specific pages. Opt-in via --long-backoff for a dedicated retry
# after a real cooldown -- not for blind immediate re-runs, which the v1.3 note above found
# just burn more of the same budget without helping.
LONG_CHALLENGE_BACKOFFS = (0, 60, 180, 300, 600)


def fetch_with_retry(context: BrowserContext, mod_id: int, backoffs=CHALLENGE_BACKOFFS,
                      page_delay: float = None) -> tuple[list[dict], bool]:
    """Like fetch_all_comments, but retries the WHOLE mod with backoff if the very first
    page load hits a Cloudflare challenge (fetch_all_comments only raises PermissionError
    for that case now -- a mid-pagination challenge is caught internally and returns a
    partial, complete=False result instead, see fetch_all_comments's docstring).
    FileNotFoundError (mod deleted) still propagates immediately, uncaught."""
    for attempt, backoff in enumerate(backoffs, start=1):
        if backoff:
            print(f"  Cloudflare challenge re-triggered, backing off {backoff}s (attempt {attempt})...")
            time.sleep(backoff)
        try:
            return fetch_all_comments(context, mod_id, page_delay=page_delay, backoffs=backoffs)
        except PermissionError:
            continue
    raise PermissionError(f"Cloudflare challenge persisted after {len(backoffs)} attempts")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="Only process the first N mods (0 = all)")
    parser.add_argument("--resume", action="store_true", help="Skip mods already present in the output file")
    parser.add_argument("--headless", action="store_true",
                         help="Launch Chromium headless instead of the default headed window. "
                              "CONFIRMED NOT TO WORK (2026-07-22, Codespaces test): triggers a "
                              "Cloudflare challenge on every retry attempt. Headless Chromium is "
                              "an independent bot-management signal on top of navigator.webdriver -- "
                              "kept as a flag in case Cloudflare's heuristics change, not for real use.")
    parser.add_argument("--mod-ids", type=str, default="",
                         help="Comma-separated list of specific Nexus mod IDs to process, in that "
                              "order, bypassing the tier CSV's file-order slicing --limit normally "
                              "does. For spot-checking mods scattered across the list without having "
                              "to churn through everything ranked ahead of them.")
    parser.add_argument("--auth-state", type=str, default=None,
                         help="Path to a Playwright storage_state JSON from a logged-in session "
                              "with 'Show adult content' enabled (see nexus_login_capture.py). "
                              "Without this, NSFW-gated mods always report 0 comments regardless "
                              "of their real count.")
    parser.add_argument("--long-backoff", action="store_true",
                         help="Use much longer backoffs (up to 10 min) between whole-mod retry "
                              "attempts, up from the default 20s/60s. For mods that keep failing "
                              "on the very first page load rather than mid-pagination (see 279/"
                              "22659 in the v1.10 docstring note) -- makes a run much slower per "
                              "failing mod, so only use it for a small --mod-ids list of known-"
                              "stubborn mods after letting them cool down, not the full sweep.")
    parser.add_argument("--output", type=str, default=None,
                         help="Override the output file path (default: nexus_comments_deep_sweep.jsonl). "
                              "Useful for a targeted re-check pass (e.g. --mod-ids against the mods "
                              "currently recorded as no_comments, to reclassify nsfw_gated ones) "
                              "without touching or clobbering the main sweep's output file.")
    parser.add_argument("--connect-cdp", type=str, default=None,
                         help="Attach to an already-running, manually-launched Chrome (started "
                              "yourself, e.g. `chrome --remote-debugging-port=9222 "
                              "--user-data-dir=<dir>`) via its CDP URL (e.g. http://127.0.0.1:9222), "
                              "instead of having Playwright launch its own browser. For mods like "
                              "279/22659 where even open_browser_context()'s navigator.webdriver "
                              "patch still gets challenged, but a genuinely human-launched browser "
                              "loads the page cleanly (see v1.14 note above). Point --user-data-dir "
                              "at nexus_login_capture.py's profile dir to also inherit that session's "
                              "login/adult-content cookies for free. Ignores --headless and "
                              "--auth-state (the manually-launched browser's own profile/context is "
                              "used as-is).")
    parser.add_argument("--page-delay", type=float, default=None,
                         help="Seconds to sleep between successful pagination requests, overriding "
                              "the default 0.5s (REQUEST_DELAY). For stubborn high-volume mods where "
                              "the default pace itself is a plausible trigger for Cloudflare's "
                              "volume/burst-based challenge, distinct from the automation-signal "
                              "issue --connect-cdp addresses -- e.g. try 5-10s for a slow, careful "
                              "single-mod rescue rather than the default pace used for the full sweep.")
    args = parser.parse_args()

    backoffs = LONG_CHALLENGE_BACKOFFS if args.long_backoff else CHALLENGE_BACKOFFS
    output_file = Path(args.output) if args.output else OUTPUT_FILE

    mod_list = load_mod_list()
    if args.mod_ids:
        wanted = [int(x) for x in args.mod_ids.split(",")]
        by_id = {m["mod_id"]: m for m in mod_list}
        mod_list = [by_id[mid] for mid in wanted if mid in by_id]
    elif args.limit:
        mod_list = mod_list[: args.limit]

    # Always append if the output file already exists -- only a brand-new file gets
    # "w". Forgetting --resume on a later --mod-ids run used to silently truncate the
    # whole file back to empty (lost the entire ~3,657-mod sweep this way, 2026-07-23,
    # see CLAUDE.md); now the worst a forgotten --resume can do is duplicate rows for
    # whatever mods get reprocessed, not destroy everything else.
    mode = "a" if output_file.exists() else "w"

    done_ids: set[int] = set()
    if args.resume and output_file.exists():
        with open(output_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    done_ids.add(json.loads(line)["mod_id"])

    todo = [m for m in mod_list if m["mod_id"] not in done_ids]
    print(f"Mods in tier list (excluding Mod Fixer): {len(mod_list)}")
    print(f"Already done (resume): {len(done_ids)}")
    print(f"Processing: {len(todo)}")

    written = 0
    consecutive_failures = 0
    CONSECUTIVE_FAILURE_LIMIT = 5  # a real per-mod hiccup already gets 3 internal retries;
                                    # this many in a row back-to-back means something systemic
                                    # broke (persistent Cloudflare block, network loss, etc.) --
                                    # better to stop loudly than silently grind through the rest
                                    # of an unattended multi-hour run collecting nothing.
    with sync_playwright() as p:
        if args.connect_cdp:
            browser, context = connect_cdp_context(p, args.connect_cdp)
        else:
            browser, context = open_browser_context(p, headless=args.headless, auth_state=args.auth_state)

        with open(output_file, mode, encoding="utf-8") as out:
            for i, mod in enumerate(todo, 1):
                mod_id, name = mod["mod_id"], mod["name"]
                now = datetime.now(timezone.utc).isoformat()
                try:
                    comments, complete = fetch_with_retry(context, mod_id, backoffs, page_delay=args.page_delay)
                except FileNotFoundError:
                    print(f"[{i}/{len(todo)}] {name} ({mod_id}): mod not found, skipping")
                    # Sentinel line so --resume treats this mod as done, not "never tried" --
                    # otherwise a 404'd mod gets re-fetched (and re-404s) on every future resume.
                    out.write(json.dumps({"mod_id": mod_id, "_fetched_at": now, "_status": "not_found"},
                                          ensure_ascii=False) + "\n")
                    out.flush()
                    continue
                except NSFWGatedError:
                    print(f"[{i}/{len(todo)}] {name} ({mod_id}): NSFW-gated (adult content preference), skipping")
                    out.write(json.dumps({"mod_id": mod_id, "_fetched_at": now, "_status": "nsfw_gated"},
                                          ensure_ascii=False) + "\n")
                    out.flush()
                    continue
                except Exception as e:
                    consecutive_failures += 1
                    print(f"[{i}/{len(todo)}] {name} ({mod_id}) FAILED: {e}")
                    if consecutive_failures >= CONSECUTIVE_FAILURE_LIMIT:
                        print(f"\n{consecutive_failures} consecutive failures -- stopping early, "
                              f"this looks systemic rather than per-mod noise. Re-run with --resume "
                              f"once whatever broke is resolved.")
                        break
                    continue

                consecutive_failures = 0
                if comments:
                    for c in comments:
                        out.write(json.dumps({"mod_id": mod_id, "_fetched_at": now, **c}, ensure_ascii=False) + "\n")
                    if not complete:
                        # Pagination hit a persistent Cloudflare challenge partway through --
                        # comments holds everything gathered up to that point, not the full set.
                        # Marker written alongside the real rows (not instead of them) so a
                        # future pass can find and specifically re-target incomplete mods.
                        out.write(json.dumps({"mod_id": mod_id, "_fetched_at": now, "_status": "partial",
                                               "_comments_captured": len(comments)}, ensure_ascii=False) + "\n")
                else:
                    # Same problem as the not_found case: a genuine zero-comment result (e.g. the
                    # NSFW preference gate) writes nothing, so --resume can't tell "done, confirmed
                    # empty" apart from "never attempted" and re-fetches it -- with real Cloudflare
                    # exposure -- on every future resume. One sentinel line fixes that.
                    out.write(json.dumps({"mod_id": mod_id, "_fetched_at": now, "_status": "no_comments"},
                                          ensure_ascii=False) + "\n")
                out.flush()
                written += len(comments)
                status_note = "" if complete else " (PARTIAL -- Cloudflare challenge mid-pagination)"
                print(f"[{i}/{len(todo)}] {name} ({mod_id}): {len(comments)} comments{status_note}")
                time.sleep(args.page_delay if args.page_delay is not None else REQUEST_DELAY)

        if args.connect_cdp:
            print("Leaving the manually-launched Chrome window open -- close it yourself when done.")
        else:
            browser.close()

    print(f"\nDone. {written} comments written to {output_file}")


if __name__ == "__main__":
    main()
