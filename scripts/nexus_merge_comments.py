#!/usr/bin/env python3
"""
nexus_merge_comments.py  v1.0  (2026-07-24, see CLAUDE.md "Nexus Mods -- comments
gap" and "Next steps" sections)
================================================================================
Produces nexus_comments_merged.jsonl = nexus_comments_deep_sweep.jsonl with the
per-mod bookkeeping sentinel rows (_status: not_found / nsfw_gated / no_comments
/ partial) stripped out, leaving only real comment rows, deduplicated by
comment_id.

Unlike modio_merge_comments.py, this is a plain filter pass, not a true merge --
there's no legacy partial dataset to reconcile here (the Nexus sweep only ever
had one real full-sweep file; the accidentally-destroyed first pass was fully
re-run from scratch, not patched in place, see CLAUDE.md's data-loss section).

Dedup rule: keep the first occurrence per comment_id in file order, drop the
rest. Duplicates are an expected, benign byproduct of nexus_deep_comments.py
v1.13's append-always file mode (a --mod-ids run without --resume reprocesses
and re-appends a mod's rows rather than erasing prior progress) -- this merge
is what collapses those back down to one row per comment.

A "partial" sentinel row is written ALONGSIDE real comment rows (not instead
of them) for a mod whose pagination hit a persistent Cloudflare challenge --
its real rows are kept here like any other mod's; only the bookkeeping sentinel
line itself is dropped. mods_partial below records which mods that affects, so
it isn't silently lost just because the sentinel line is gone from the merged
file.

Leaves nexus_comments_deep_sweep.jsonl untouched.

USAGE:
  py nexus_merge_comments.py
================================================================================
"""

import json
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data" / "nexus" / "deep_comments"
SOURCE_FILE = DATA_DIR / "nexus_comments_deep_sweep.jsonl"
MERGED_FILE = DATA_DIR / "nexus_comments_merged.jsonl"


def main():
    status_counts = Counter()
    mods_by_status = {"not_found": [], "nsfw_gated": [], "no_comments": [], "partial": []}
    seen_ids = set()
    kept = 0
    dropped_duplicate = 0
    dropped_sentinel = 0
    total_lines = 0

    with open(SOURCE_FILE, encoding="utf-8") as f, open(MERGED_FILE, "w", encoding="utf-8") as out:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            total_lines += 1
            obj = json.loads(stripped)

            status = obj.get("_status")
            if status is not None:
                dropped_sentinel += 1
                status_counts[status] += 1
                if status in mods_by_status:
                    mods_by_status[status].append(obj["mod_id"])
                continue

            comment_id = obj.get("comment_id")
            if comment_id in seen_ids:
                dropped_duplicate += 1
                continue
            seen_ids.add(comment_id)
            out.write(stripped + "\n")
            kept += 1

    print(f"Source lines read: {total_lines}")
    print(f"Real comment rows kept (deduped): {kept}")
    print(f"Duplicate comment_id rows dropped: {dropped_duplicate}")
    print(f"Sentinel bookkeeping rows dropped: {dropped_sentinel}")
    for status, count in status_counts.most_common():
        print(f"  {status}: {count} mods")
    if mods_by_status["partial"]:
        print(f"\nMods with PARTIAL comment coverage (real rows kept, but incomplete "
              f"-- see CLAUDE.md's 279/22659 section): {sorted(mods_by_status['partial'])}")
    print(f"\nMerged file: {MERGED_FILE}")
    print(f"Original file left untouched: {SOURCE_FILE}")


if __name__ == "__main__":
    main()
