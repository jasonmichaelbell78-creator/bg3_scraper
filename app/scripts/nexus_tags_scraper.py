#!/usr/bin/env python3
"""
nexus_tags_scraper.py  v1.0  (2026-08-09)
================================================================================
Bulk-fetches every BG3 Nexus mod's full tag list via the unauthenticated
GraphQL API -- the real gap behind Phase 3's patch-8 tag capture workstream
(see docs/superpowers/specs/2026-08-09-phase3-patch8-tag-capture-design.md).

nexus_bg3_scraper.py's v1 REST API calls have NO tags field at all (confirmed
live 2026-08-09 -- the existing has_non_english_tag(mod.get("tags") or [])
filter has always silently operated on an empty list). Tags only exist via
GraphQL's mods() query, under a per-mod `tags { name }` field -- confirmed
live to include e.g. "Patch 8 Compatible".

Query, same host/endpoint as nexus_collections_scraper.py:
  https://api.nexusmods.com/v2/graphql
  mods(filter: {gameId: {value: "3474"}}, count, offset) {
    totalCount
    nodes { modId tags { name } }
  }
-- offset/count paginated (not Relay cursor-based), confirmed live: no auth
needed, ~189 pages at count=100 for ~18,870 current BG3 Nexus mods.

USAGE:
  py nexus_tags_scraper.py           # full sweep
  py nexus_tags_scraper.py --limit 3  # test on first 3 pages (~300 mods)
  py nexus_tags_scraper.py --resume   # continue from last completed offset
================================================================================
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parents[2]
GRAPHQL_URL = "https://api.nexusmods.com/v2/graphql"
GAME_ID = "3474"
PAGE_SIZE = 100
REQUEST_DELAY = 0.3

DATA_DIR = BASE_DIR / "data" / "nexus"
DATA_DIR.mkdir(parents=True, exist_ok=True)
TAGS_FILE = DATA_DIR / "nexus_tags.jsonl"
PROGRESS_FILE = DATA_DIR / "nexus_tags_progress.json"

TAGS_QUERY = """
query($gid: String!, $count: Int!, $offset: Int!) {
  mods(filter: {gameId: {value: $gid}}, count: $count, offset: $offset) {
    totalCount
    nodes { modId tags { name } }
  }
}
"""


def gql(session: requests.Session, variables: dict) -> dict:
    resp = session.post(GRAPHQL_URL, json={"query": TAGS_QUERY, "variables": variables}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(f"GraphQL error: {data['errors']}")
    return data["data"]


def load_progress() -> int:
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text()).get("next_offset", 0)
    return 0


def save_progress(next_offset: int) -> None:
    PROGRESS_FILE.write_text(json.dumps({"next_offset": next_offset}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="Only fetch the first N pages (0 = all)")
    parser.add_argument("--resume", action="store_true", help="Continue from the last completed offset")
    args = parser.parse_args()

    session = requests.Session()
    offset = load_progress() if args.resume else 0
    # Always append if the file already exists, regardless of --resume -- the
    # v1.13 data-loss lesson (CLAUDE.md): a script must never silently
    # truncate prior output just because --resume was forgotten.
    mode = "a" if TAGS_FILE.exists() else "w"

    pages_fetched = 0
    total_mods_written = 0

    with open(TAGS_FILE, mode, encoding="utf-8") as out:
        while True:
            data = gql(session, {"gid": GAME_ID, "count": PAGE_SIZE, "offset": offset})
            page = data["mods"]
            nodes = page["nodes"]
            total_count = page["totalCount"]
            now = datetime.now(timezone.utc).isoformat()

            for node in nodes:
                out.write(json.dumps({
                    "nexus_mod_id": node["modId"],
                    "tags": [t["name"] for t in (node.get("tags") or [])],
                    "_fetched_at": now,
                }, ensure_ascii=False) + "\n")
            out.flush()
            total_mods_written += len(nodes)

            offset += len(nodes)
            pages_fetched += 1
            save_progress(offset)
            print(f"page {pages_fetched}: offset {offset}/{total_count} ({total_mods_written} mods written)")

            if not nodes or offset >= total_count:
                break
            if args.limit and pages_fetched >= args.limit:
                print(f"--limit {args.limit} reached, stopping early")
                break
            time.sleep(REQUEST_DELAY)

    print(f"\nDone. {total_mods_written} mod tag-list rows written to {TAGS_FILE}")


if __name__ == "__main__":
    main()