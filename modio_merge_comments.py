#!/usr/bin/env python3
"""
modio_merge_comments.py  v1.1  (run 2026-07-21, see manifest_modio_comments.md)
================================================================================
Produces modio_comments_merged.jsonl = modio_comments_fullsweep.jsonl with the
stale, capped rows for deep-refreshed mods removed and replaced by the
complete data in modio_comments_deep_refresh.jsonl, then deduplicated by
comment `id`.

The old fullsweep file has 184 duplicate-id groups (368 rows), a repeated-
write artifact from the original scraper's non-idempotent resume logic --
verified byte-identical content across each pair, not conflicting revisions.
Dedup rule: keep the first occurrence per `id` in file order, drop the rest.

Leaves modio_comments_fullsweep.jsonl untouched.
================================================================================
"""

import json
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "bg3_modio_data" / "bg3_modio_data"
OLD_FILE = DATA_DIR / "modio_comments_fullsweep.jsonl"
REFRESH_FILE = DATA_DIR / "modio_comments_deep_refresh.jsonl"
MERGED_FILE = DATA_DIR / "modio_comments_merged.jsonl"


def main():
    refreshed_mod_ids = set()
    refreshed_rows = []
    with open(REFRESH_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            refreshed_mod_ids.add(obj["mod_id"])
            refreshed_rows.append(line)

    seen_ids = set()
    kept = 0
    dropped_replaced = 0
    dropped_duplicate = 0
    with open(OLD_FILE, encoding="utf-8") as f, open(MERGED_FILE, "w", encoding="utf-8") as out:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            obj = json.loads(stripped)
            if obj["mod_id"] in refreshed_mod_ids:
                dropped_replaced += 1
                continue
            if obj["id"] in seen_ids:
                dropped_duplicate += 1
                continue
            seen_ids.add(obj["id"])
            out.write(stripped + "\n")
            kept += 1
        refreshed_written = 0
        for line in refreshed_rows:
            obj = json.loads(line)
            if obj["id"] in seen_ids:
                dropped_duplicate += 1
                continue
            seen_ids.add(obj["id"])
            out.write(line + "\n")
            refreshed_written += 1

    total_written = kept + refreshed_written
    print(f"Mods refreshed: {len(refreshed_mod_ids)}")
    print(f"Old rows kept (untouched mods, deduped): {kept}")
    print(f"Old stale rows dropped (superseded by refresh): {dropped_replaced}")
    print(f"Duplicate-id rows dropped: {dropped_duplicate}")
    print(f"New fresh rows written: {refreshed_written}")
    print(f"Total unique rows written: {total_written}")
    print(f"Merged file: {MERGED_FILE}")
    print(f"Original file left untouched: {OLD_FILE}")


if __name__ == "__main__":
    main()
