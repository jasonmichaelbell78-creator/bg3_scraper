#!/usr/bin/env python3
"""
volo_masterlist_fetch.py  v1.0  (2026-08-10)
================================================================================
Downloads VOLO's public, CC0-licensed BG3 load-order/deployment-type
masterlist in one shot -- see
docs/superpowers/specs/2026-08-10-volo-masterlist-ingestion-design.md.

Source (verbatim CC0 1.0 Universal, confirmed via masterlist/LICENSE in the
VOLO repo): https://raw.githubusercontent.com/Moonie8t7/VOLO/main/masterlist/bg3-masterlist.json

No pagination, no auth, no Cloudflare -- a plain GitHub raw-content GET.

USAGE:
  py app/scripts/volo_masterlist_fetch.py
================================================================================
"""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parents[2]
MASTERLIST_URL = "https://raw.githubusercontent.com/Moonie8t7/VOLO/main/masterlist/bg3-masterlist.json"

DATA_DIR = BASE_DIR / "data" / "volo"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def fetch_masterlist() -> bytes:
    resp = requests.get(MASTERLIST_URL, timeout=30)
    resp.raise_for_status()
    return resp.content


def build_manifest(raw_bytes: bytes, masterlist: dict, fetched_at: str) -> dict:
    return {
        "source_url": MASTERLIST_URL,
        "fetched_at": fetched_at,
        "file_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "masterlist_version": masterlist.get("version"),
        "masterlist_generated": masterlist.get("generated"),
        "masterlist_gameBuild": masterlist.get("gameBuild"),
        "masterlist_gamePatch": masterlist.get("gamePatch"),
        "plugin_count": len(masterlist.get("plugins") or []),
    }


def main():
    fetched_at = datetime.now(timezone.utc).isoformat()
    date_stamp = fetched_at[:10]

    raw_bytes = fetch_masterlist()
    masterlist = json.loads(raw_bytes)

    out_path = DATA_DIR / f"bg3-masterlist_{date_stamp}.json"
    out_path.write_bytes(raw_bytes)

    manifest = build_manifest(raw_bytes, masterlist, fetched_at)
    manifest_path = DATA_DIR / f"bg3-masterlist_{date_stamp}.manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"Downloaded {manifest['plugin_count']} plugins (masterlist version {manifest['masterlist_version']})")
    print(f"  -> {out_path}")
    print(f"  -> {manifest_path}")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
