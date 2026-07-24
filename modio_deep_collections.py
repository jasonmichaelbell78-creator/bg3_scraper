#!/usr/bin/env python3
"""
modio_deep_collections.py  v1.0  (2026-07-24, see CLAUDE.md "Collections" section)
================================================================================
Collections (curated mod bundles) on mod.io -- a distinct, previously-unscraped
feature: bg3_scraper.py only ever walked individual mods, never Collections.
Confirmed live 2026-07-24: fully scriptable via the same official *.modapi.io
REST API already in use elsewhere in this project -- no browser automation, no
Cloudflare, no cookies, just MODIO_API_KEY (same key bg3_scraper.py uses).
843 total BG3 collections confirmed live.

Three sub-resources per collection, all under the same api_key auth:
  GET /v1/games/6715/collections                -- list/search. Paginated via
                                                     _offset/_limit; _limit=100
                                                     confirmed as the effective
                                                     max (500 errors out).
  GET /v1/games/6715/collections/{id}/mods       -- mod list for one collection
                                                     (full raw mod objects).
  GET /v1/games/6715/collections/{id}/comments   -- threaded comments.
                                                     _offset/_limit pagination
                                                     confirmed correct live
                                                     (tested offset=0/limit=3
                                                     then offset=3/limit=3
                                                     against a 15-comment
                                                     collection -- zero overlap,
                                                     matches result_total). NOT
                                                     a repeat of the original
                                                     mod-comments silent-100-cap
                                                     bug.

A collection only counts as "done" (for --resume) once ITS mods AND comments
have both been fetched successfully -- the meta row is written last, after
both sub-fetches succeed, so a mid-collection failure doesn't leave a false
"done" marker. Output files always open in append mode when they already
exist, regardless of --resume (see nexus_deep_comments.py's v1.13 changelog
for why this matters -- forgetting --resume should never be able to truncate
prior progress, only produce duplicate rows for reprocessed collections).

USAGE:
  py modio_deep_collections.py
  py modio_deep_collections.py --limit 5      # test on first 5 collections
  py modio_deep_collections.py --resume       # skip collections already fully done
================================================================================
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# Windows' default console codepage (cp1252) can't encode some collection names
# (emoji, etc.) -- crashed a live run at collection 31/843 on an otherwise-benign
# print(). File writes were already safe (opened with encoding="utf-8"); only
# stdout needed this. errors="replace" so a print never crashes the whole sweep
# over a display-only issue again.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).parent
GAME_ID = 6715
BASE_URL = f"https://g-{GAME_ID}.modapi.io/v1"
HEADERS = {"X-Modio-Platform": "windows", "Accept-Language": "en", "Accept": "application/json"}
REQUEST_DELAY = 0.4
PAGE_SIZE = 100  # confirmed max effective _limit -- 500 errors out

META_FILE = BASE_DIR / "modio_collections_meta.jsonl"
MODS_FILE = BASE_DIR / "modio_collections_mods.jsonl"
COMMENTS_FILE = BASE_DIR / "modio_collections_comments.jsonl"


def api_key() -> str:
    key = os.environ.get("MODIO_API_KEY")
    if not key:
        raise SystemExit("Set the MODIO_API_KEY environment variable (see .env.example)")
    return key


def safe_get(session: requests.Session, url: str, params: dict) -> dict:
    """Robust GET with retry-on-transient-error / rate-limit backoff, mirroring
    bg3_scraper.py's safe_api_request()."""
    while True:
        resp = session.get(url, headers=HEADERS, params=params, timeout=20)
        if resp.status_code == 429:
            backoff = int(resp.headers.get("Retry-After", 15) or 15)
            print(f"    [rate limit] sleeping {backoff}s...")
            time.sleep(backoff)
            continue
        resp.raise_for_status()
        return resp.json()


def paginate(session: requests.Session, url: str, key: str) -> list[dict]:
    items = []
    offset = 0
    while True:
        data = safe_get(session, url, {"api_key": key, "_limit": PAGE_SIZE, "_offset": offset})
        batch = data.get("data", [])
        items.extend(batch)
        offset += len(batch)
        time.sleep(REQUEST_DELAY)
        if not batch or offset >= data.get("result_total", offset):
            break
    return items


def list_all_collections(session: requests.Session, key: str) -> list[dict]:
    return paginate(session, f"{BASE_URL}/games/{GAME_ID}/collections", key)


def fetch_all_mods(session: requests.Session, key: str, collection_id: int) -> list[dict]:
    return paginate(session, f"{BASE_URL}/games/{GAME_ID}/collections/{collection_id}/mods", key)


def fetch_all_comments(session: requests.Session, key: str, collection_id: int) -> list[dict]:
    return paginate(session, f"{BASE_URL}/games/{GAME_ID}/collections/{collection_id}/comments", key)


def load_done_ids() -> set[int]:
    done = set()
    if META_FILE.exists():
        with open(META_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    done.add(json.loads(line)["id"])
    return done


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="Only process the first N collections (0 = all)")
    parser.add_argument("--resume", action="store_true", help="Skip collections already fully recorded")
    args = parser.parse_args()

    key = api_key()
    session = requests.Session()

    print("Listing all BG3 collections...")
    collections = list_all_collections(session, key)
    print(f"Found {len(collections)} collections")

    done_ids = load_done_ids() if args.resume else set()
    todo = [c for c in collections if c["id"] not in done_ids]
    if args.limit:
        todo = todo[: args.limit]
    print(f"Already done (resume): {len(done_ids)}")
    print(f"Processing: {len(todo)}")

    mods_mode = "a" if MODS_FILE.exists() else "w"
    comments_mode = "a" if COMMENTS_FILE.exists() else "w"
    meta_mode = "a" if META_FILE.exists() else "w"

    written_mods = written_comments = 0
    consecutive_failures = 0
    CONSECUTIVE_FAILURE_LIMIT = 5

    with open(MODS_FILE, mods_mode, encoding="utf-8") as mods_out, \
         open(COMMENTS_FILE, comments_mode, encoding="utf-8") as comments_out, \
         open(META_FILE, meta_mode, encoding="utf-8") as meta_out:

        for i, coll in enumerate(todo, 1):
            cid, name = coll["id"], coll.get("name", "?")
            now = datetime.now(timezone.utc).isoformat()
            try:
                mods = fetch_all_mods(session, key, cid)
                comments = fetch_all_comments(session, key, cid)
            except Exception as e:
                consecutive_failures += 1
                print(f"[{i}/{len(todo)}] {name} ({cid}) FAILED: {e}")
                if consecutive_failures >= CONSECUTIVE_FAILURE_LIMIT:
                    print(f"\n{consecutive_failures} consecutive failures -- stopping early. "
                          f"Re-run with --resume once whatever broke is resolved.")
                    break
                continue

            consecutive_failures = 0

            for m in mods:
                mods_out.write(json.dumps({
                    "collection_id": cid,
                    "mod_id": m.get("id"),
                    "name_id": m.get("name_id"),
                    "name": m.get("name"),
                    "_fetched_at": now,
                }, ensure_ascii=False) + "\n")
            mods_out.flush()
            written_mods += len(mods)

            if comments:
                for c in comments:
                    comments_out.write(json.dumps({"collection_id": cid, "_fetched_at": now, **c},
                                                    ensure_ascii=False) + "\n")
            else:
                comments_out.write(json.dumps({"collection_id": cid, "_fetched_at": now, "_status": "no_comments"},
                                                ensure_ascii=False) + "\n")
            comments_out.flush()
            written_comments += len(comments)

            meta_out.write(json.dumps({**coll, "_fetched_at": now}, ensure_ascii=False) + "\n")
            meta_out.flush()

            print(f"[{i}/{len(todo)}] {name} ({cid}): {len(mods)} mods, {len(comments)} comments")

    print(f"\nDone. {written_mods} mod rows, {written_comments} comment rows written.")
    print(f"  {META_FILE}\n  {MODS_FILE}\n  {COMMENTS_FILE}")


if __name__ == "__main__":
    main()
