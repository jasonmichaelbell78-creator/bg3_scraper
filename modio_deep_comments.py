#!/usr/bin/env python3
"""
modio_deep_comments.py  v1.0  (run 2026-07-21, see manifest_modio_comments.md)
================================================================================
Re-fetches FULL comment threads for mod.io BG3 mods whose last sweep hit the
~100-comment ceiling (a pagination gap in the old scraper, not a real API
limit -- verified empirically: the site's own frontend pages past offset=100
fine).

Auth strategy:
  mod.io's public *.modapi.io API needs an api_key. Its own website instead
  calls https://mod.io/v1/... with custom headers (x-modio-game, x-modio-mod,
  x-modio-origin: web) plus Cloudflare bot-management cookies (__cf_bm,
  __cflb, _cfuvid) obtained by loading the page in a real browser. This
  script does ONE Playwright page load to mint those cookies, then reuses
  them across plain `requests` calls for every mod -- fast, and avoids
  spinning up a browser per mod.

USAGE:
  py modio_deep_comments.py
  py modio_deep_comments.py --limit 5       # test on first 5 truncated mods
================================================================================
"""

import argparse
import json
import time
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "bg3_modio_data" / "bg3_modio_data"
MODS_FILE = DATA_DIR / "modio_mods_full_sweep.jsonl"
COMMENTS_FILE = DATA_DIR / "modio_comments_fullsweep.jsonl"
OUTPUT_FILE = DATA_DIR / "modio_comments_deep_refresh.jsonl"

GAME_ID = 6715
GAME_SLUG = "baldursgate3"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
TRUNCATION_THRESHOLD = 100  # mods with >= this many captured comments get refreshed
REQUEST_DELAY = 0.4


def find_truncated_mods() -> set[int]:
    counts = {}
    with open(COMMENTS_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            mod_id = obj.get("mod_id")
            counts[mod_id] = counts.get(mod_id, 0) + 1
    return {mid for mid, c in counts.items() if c >= TRUNCATION_THRESHOLD}


def load_mod_slugs(mod_ids: set[int]) -> dict[int, dict]:
    slugs = {}
    with open(MODS_FILE, encoding="utf-8") as f:
        for line in f:
            obj = json.loads(line)
            mid = obj.get("id")
            if mid in mod_ids:
                slugs[mid] = {"name_id": obj.get("name_id"), "name": obj.get("name")}
            if len(slugs) == len(mod_ids):
                break
    return slugs


def warm_up_session() -> dict:
    """Loads one mod page in a real browser to mint Cloudflare bot-management cookies."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=UA)
        page.goto(f"https://mod.io/g/{GAME_SLUG}", wait_until="networkidle", timeout=45000)
        try:
            page.click("text=Allow All", timeout=3000)
        except Exception:
            pass
        cookies = page.context.cookies()
        browser.close()
        return {c["name"]: c["value"] for c in cookies}


def build_session(cookie_jar: dict) -> requests.Session:
    session = requests.Session()
    for name, value in cookie_jar.items():
        session.cookies.set(name, value, domain="mod.io")
    return session


def fetch_all_comments(session: requests.Session, mod_id: int, name_id: str) -> list[dict]:
    url = f"https://mod.io/v1/games/@{GAME_SLUG}/mods/@{name_id}/comments"
    headers = {
        "User-Agent": UA,
        "Accept": "application/json",
        "Referer": f"https://mod.io/g/{GAME_SLUG}/m/{name_id}",
        "x-modio-game": str(GAME_ID),
        "x-modio-mod": str(mod_id),
        "x-modio-origin": "web",
    }
    comments = []
    offset = 0
    while True:
        resp = session.get(url, headers=headers, params={"_offset": offset, "_sort": "-id"}, timeout=20)
        if resp.status_code == 401:
            raise PermissionError("cookie session expired")
        resp.raise_for_status()
        data = resp.json()
        batch = data.get("data", [])
        comments.extend(batch)
        total = data.get("result_total", len(comments))
        offset += len(batch)
        time.sleep(REQUEST_DELAY)
        if not batch or offset >= total:
            break
    return comments


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="Only process the first N truncated mods (0 = all)")
    args = parser.parse_args()

    truncated = find_truncated_mods()
    slugs = load_mod_slugs(truncated)
    mod_list = sorted(slugs.items())
    if args.limit:
        mod_list = mod_list[: args.limit]

    print(f"Truncated mods found: {len(truncated)}")
    print(f"Processing: {len(mod_list)}")

    cookie_jar = warm_up_session()
    session = build_session(cookie_jar)

    written = 0
    with open(OUTPUT_FILE, "w", encoding="utf-8") as out:
        for i, (mod_id, info) in enumerate(mod_list, 1):
            name_id = info["name_id"]
            try:
                comments = fetch_all_comments(session, mod_id, name_id)
            except PermissionError:
                print("  session expired, re-warming...")
                cookie_jar = warm_up_session()
                session = build_session(cookie_jar)
                comments = fetch_all_comments(session, mod_id, name_id)
            except Exception as e:
                print(f"[{i}/{len(mod_list)}] {info['name']} ({mod_id}) FAILED: {e}")
                continue

            for c in comments:
                out.write(json.dumps(c, ensure_ascii=False) + "\n")
            written += len(comments)
            print(f"[{i}/{len(mod_list)}] {info['name']} ({mod_id}): {len(comments)} comments")

    print(f"\nDone. {written} comments written to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
