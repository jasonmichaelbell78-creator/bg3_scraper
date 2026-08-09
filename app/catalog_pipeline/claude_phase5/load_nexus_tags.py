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