#!/usr/bin/env python3
"""
nexus_deep_comments.py  v1.6  (investigation 2026-07-21/22, see CLAUDE.md)
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

BASE_DIR = Path(__file__).parent
TIER_CSV = BASE_DIR / "BG3_Nexus_Tier1_Tier2_Mods.csv"
OUTPUT_FILE = BASE_DIR / "nexus_comments_deep_sweep.jsonl"

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


def load_mod_list() -> list[dict]:
    mods = []
    with open(TIER_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            mod_id = int(row["nexus_mod_id"])
            if mod_id in EXCLUDED_MOD_IDS:
                continue
            mods.append({"mod_id": mod_id, "name": row["mod_name"], "url": row["nexus_url"]})
    return mods


def open_browser_context(playwright, headless: bool = False):
    # A vanilla playwright.chromium.launch() reports navigator.webdriver = True
    # -- confirmed locally (2026-07-22) and almost certainly the real cause of
    # the challenges seen in v1.0-v1.4, not headless state or IP/volume scoring:
    # the working Playwright MCP browser used during this whole investigation
    # reports navigator.webdriver = False. Patch it the standard way, before
    # any page script runs.
    browser = playwright.chromium.launch(headless=headless)
    context = browser.new_context(user_agent=UA)
    context.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => false });")
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


def fetch_all_comments(context: BrowserContext, mod_id: int) -> list[dict]:
    page = new_page(context)
    try:
        first_page_html = fetch_mod_posts_page(page, mod_id)

        thread_match = THREAD_ID_RE.search(first_page_html)
        if not thread_match:
            return []  # no Posts/comments on this mod
        thread_id = thread_match.group(1)

        count_match = COMMENT_COUNT_RE.search(first_page_html)
        reported_count = int(count_match.group(1)) if count_match else 0
        if reported_count == 0:
            return []

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
        while page_num <= max_pages:
            html = fetch_comment_page(page, mod_id, thread_id, page_num)
            batch = parse_comments(html)
            new_ids = [c for c in batch if c["comment_id"] not in seen_ids]
            if not new_ids:
                break
            for c in new_ids:
                seen_ids.add(c["comment_id"])
                comments.append(c)
            time.sleep(REQUEST_DELAY)
            page_num += 1

        for c in comments:
            c["thread_id"] = thread_id
        return comments
    finally:
        page.close()


CHALLENGE_BACKOFFS = (0, 20, 60)  # seconds before each attempt; first attempt has no wait


def fetch_with_retry(context: BrowserContext, mod_id: int) -> list[dict]:
    """Like fetch_all_comments, but retries with backoff on a Cloudflare challenge.
    FileNotFoundError (mod deleted) still propagates immediately, uncaught."""
    for attempt, backoff in enumerate(CHALLENGE_BACKOFFS, start=1):
        if backoff:
            print(f"  Cloudflare challenge re-triggered, backing off {backoff}s (attempt {attempt})...")
            time.sleep(backoff)
        try:
            return fetch_all_comments(context, mod_id)
        except PermissionError:
            continue
    raise PermissionError(f"Cloudflare challenge persisted after {len(CHALLENGE_BACKOFFS)} attempts")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="Only process the first N mods (0 = all)")
    parser.add_argument("--resume", action="store_true", help="Skip mods already present in the output file")
    parser.add_argument("--headless", action="store_true",
                         help="Launch Chromium headless instead of the default headed window "
                              "(untested against live Cloudflare as of v1.5 -- the navigator.webdriver "
                              "patch is believed to be the real fix, not headed state, but this has "
                              "never actually been run headless against the live site)")
    args = parser.parse_args()

    mod_list = load_mod_list()
    if args.limit:
        mod_list = mod_list[: args.limit]

    done_ids: set[int] = set()
    mode = "w"
    if args.resume and OUTPUT_FILE.exists():
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    done_ids.add(json.loads(line)["mod_id"])
        mode = "a"

    todo = [m for m in mod_list if m["mod_id"] not in done_ids]
    print(f"Mods in tier list (excluding Mod Fixer): {len(mod_list)}")
    print(f"Already done (resume): {len(done_ids)}")
    print(f"Processing: {len(todo)}")

    written = 0
    with sync_playwright() as p:
        browser, context = open_browser_context(p, headless=args.headless)

        with open(OUTPUT_FILE, mode, encoding="utf-8") as out:
            for i, mod in enumerate(todo, 1):
                mod_id, name = mod["mod_id"], mod["name"]
                now = datetime.now(timezone.utc).isoformat()
                try:
                    comments = fetch_with_retry(context, mod_id)
                except FileNotFoundError:
                    print(f"[{i}/{len(todo)}] {name} ({mod_id}): mod not found, skipping")
                    continue
                except Exception as e:
                    print(f"[{i}/{len(todo)}] {name} ({mod_id}) FAILED: {e}")
                    continue

                for c in comments:
                    out.write(json.dumps({"mod_id": mod_id, "_fetched_at": now, **c}, ensure_ascii=False) + "\n")
                out.flush()
                written += len(comments)
                print(f"[{i}/{len(todo)}] {name} ({mod_id}): {len(comments)} comments")
                time.sleep(REQUEST_DELAY)

        browser.close()

    print(f"\nDone. {written} comments written to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
