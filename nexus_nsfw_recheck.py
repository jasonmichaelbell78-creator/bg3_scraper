#!/usr/bin/env python3
"""
nexus_nsfw_recheck.py
================================================================================
One-shot follow-up to the main nexus_deep_comments.py sweep. Finds every mod
currently recorded as `_status: "no_comments"` in nexus_comments_deep_sweep.jsonl
and re-checks it anonymously with the v1.12 NSFW-gate detection (see
nexus_deep_comments.py's docstring / CLAUDE.md) to split that bucket into
"genuinely zero comments" vs. "hidden by Nexus's adult-content preference gate".

Writes results to nsfw_recheck.jsonl -- never touches nexus_comments_deep_sweep.jsonl
-- and prints a tally at the end.

USAGE:
  py nexus_nsfw_recheck.py
================================================================================
"""

import json
from collections import Counter
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright

from nexus_deep_comments import (
    BASE_DIR, CHALLENGE_BACKOFFS, NSFWGatedError, fetch_with_retry, open_browser_context,
)

SWEEP_FILE = BASE_DIR / "nexus_comments_deep_sweep.jsonl"
RECHECK_FILE = BASE_DIR / "nsfw_recheck.jsonl"


def main():
    mod_ids = []
    with open(SWEEP_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            if d.get("_status") == "no_comments":
                mod_ids.append(d["mod_id"])

    print(f"{len(mod_ids)} mods currently recorded as no_comments")
    if not mod_ids:
        return

    tally = Counter()
    with sync_playwright() as p:
        browser, context = open_browser_context(p)
        with open(RECHECK_FILE, "w", encoding="utf-8") as out:
            for i, mod_id in enumerate(mod_ids, 1):
                now = datetime.now(timezone.utc).isoformat()
                count = 0
                try:
                    comments = fetch_with_retry(context, mod_id, CHALLENGE_BACKOFFS)
                except NSFWGatedError:
                    status = "nsfw_gated"
                except FileNotFoundError:
                    status = "not_found"
                except Exception as e:
                    status = "failed"
                    print(f"[{i}/{len(mod_ids)}] {mod_id} FAILED: {e}")
                else:
                    status = "no_comments" if not comments else "has_comments"
                    count = len(comments)

                tally[status] += 1
                out.write(json.dumps(
                    {"mod_id": mod_id, "_fetched_at": now, "_status": status, "_comment_count": count},
                    ensure_ascii=False) + "\n")
                out.flush()
                print(f"[{i}/{len(mod_ids)}] {mod_id}: {status}")

        browser.close()

    print(f"\nTally: {dict(tally)}")
    print(f"Written to {RECHECK_FILE}")


if __name__ == "__main__":
    main()
