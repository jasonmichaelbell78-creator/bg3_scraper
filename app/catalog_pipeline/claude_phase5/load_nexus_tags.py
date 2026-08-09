# app/catalog_pipeline/claude_phase5/load_nexus_tags.py
"""
load_nexus_tags.py v1.0
========================
B26 Phase 5, workstream 1: loads the bulk Nexus tag capture (from
nexus_tags_scraper.py) into the existing platform_tags table. mod.io's side
of this table is already populated (B25-era, 7,921/8,158 listings) --
Nexus has zero rows before this migration. See
docs/superpowers/specs/2026-08-09-phase3-patch8-tag-capture-design.md for
the full design and the correction to the original research doc's "already
fetched" claim (Nexus's v1 REST API has no tags field at all; only GraphQL
exposes them).
"""
import json
import sqlite3
from pathlib import Path

from app.catalog_pipeline.claude_phase3.promote_comment_evidence import (
    sha256_file,
    verify_db_hash,
    backup_database,
)


def parse_tags_line(line: str) -> dict:
    row = json.loads(line)
    return {
        "nexus_mod_id": str(row["nexus_mod_id"]),
        "tags": row.get("tags") or [],
    }


def load_nexus_listing_lookup(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        "SELECT platform_mod_id, listing_id FROM platform_listings WHERE platform = 'nexus'"
    ).fetchall()
    return {platform_mod_id: listing_id for platform_mod_id, listing_id in rows}


def insert_nexus_tags(conn: sqlite3.Connection, filepath: Path, listing_lookup: dict) -> dict:
    mods_seen = 0
    tags_inserted = 0
    skipped_unmapped_mods = 0
    skipped_duplicate_tags = 0
    seen_pairs = set()

    with open(filepath, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            parsed = parse_tags_line(line)
            mods_seen += 1
            listing_id = listing_lookup.get(parsed["nexus_mod_id"])
            if listing_id is None:
                skipped_unmapped_mods += 1
                continue
            for tag in parsed["tags"]:
                key = (listing_id, tag)
                if key in seen_pairs:
                    skipped_duplicate_tags += 1
                    continue
                seen_pairs.add(key)
                conn.execute(
                    "INSERT INTO platform_tags (listing_id, tag) VALUES (?, ?)",
                    (listing_id, tag),
                )
                tags_inserted += 1

    return {
        "mods_seen": mods_seen,
        "tags_inserted": tags_inserted,
        "skipped_unmapped_mods": skipped_unmapped_mods,
        "skipped_duplicate_tags": skipped_duplicate_tags,
    }
