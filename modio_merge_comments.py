#!/usr/bin/env python3
"""
modio_merge_comments.py
================================================================================
Produces modio_comments_merged.jsonl = modio_comments_fullsweep.jsonl with the
stale, capped rows for deep-refreshed mods removed and replaced by the
complete data in modio_comments_deep_refresh.jsonl.

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

    kept = 0
    dropped = 0
    with open(OLD_FILE, encoding="utf-8") as f, open(MERGED_FILE, "w", encoding="utf-8") as out:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            obj = json.loads(stripped)
            if obj["mod_id"] in refreshed_mod_ids:
                dropped += 1
                continue
            out.write(stripped + "\n")
            kept += 1
        for line in refreshed_rows:
            out.write(line + "\n")

    print(f"Mods refreshed: {len(refreshed_mod_ids)}")
    print(f"Old rows kept (untouched mods): {kept}")
    print(f"Old stale rows dropped: {dropped}")
    print(f"New fresh rows added: {len(refreshed_rows)}")
    print(f"Merged file: {MERGED_FILE}")
    print(f"Original file left untouched: {OLD_FILE}")


if __name__ == "__main__":
    main()
