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
import argparse
import json
import sqlite3
from datetime import datetime, timezone
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


def run_migration(db_path: Path, expected_sha256: str, tags_path: Path) -> dict:
    verify_db_hash(db_path, expected_sha256)
    backup_path = backup_database(db_path, suffix=".pre-phase5-nexus-tags-backup")
    tags_sha256 = sha256_file(tags_path)

    conn = sqlite3.connect(str(db_path))
    try:
        # Foreign keys are connection-local and off by default in SQLite --
        # matches the pattern claude_phase3/promote_comment_evidence.py
        # already establishes for this project's migrations.
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN")
        try:
            before = conn.execute("SELECT COUNT(*) FROM platform_tags").fetchone()[0]

            # Claim the migration slot first: migration_history.migration_name
            # is UNIQUE, so a rerun raises IntegrityError right here, before
            # any tag row is touched -- the clean, deterministic failure this
            # project's migrations require (matches claude_phase4's pattern).
            conn.execute(
                """INSERT INTO migration_history
                   (migration_name, schema_version, applied_at, actor_session,
                    source_db_sha256, row_count_before, row_count_after, notes)
                   VALUES (?, 'phase5', ?, 'claude-code-phase5', ?, ?, ?, 'pending')""",
                (
                    "b26-phase5-nexus-tags",
                    datetime.now(timezone.utc).isoformat(),
                    expected_sha256,
                    str(before),
                    str(before),
                ),
            )

            listing_lookup = load_nexus_listing_lookup(conn)
            counts = insert_nexus_tags(conn, tags_path, listing_lookup)
            after = before + counts["tags_inserted"]

            conn.execute(
                """UPDATE migration_history SET row_count_after = ?, notes = ?
                   WHERE migration_name = ?""",
                (
                    str(after),
                    f"+{counts['tags_inserted']} nexus tags "
                    f"(skipped {counts['skipped_unmapped_mods']} unmapped mods, "
                    f"{counts['skipped_duplicate_tags']} duplicate tags), "
                    f"{counts['mods_seen']} mods seen",
                    "b26-phase5-nexus-tags",
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()

    post_sha256 = sha256_file(db_path)
    return {
        "migration_name": "b26-phase5-nexus-tags",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "pre_migration_sha256": expected_sha256,
        "backup_path": str(backup_path),
        "tags_source_sha256": tags_sha256,
        "platform_tags_rows_before": before,
        "platform_tags_rows_after": after,
        **counts,
        "post_migration_sha256": post_sha256,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--candidate-sha256", required=True)
    parser.add_argument("--tags", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()

    receipt = run_migration(args.db, args.candidate_sha256, args.tags)
    args.receipt.write_text(json.dumps(receipt, indent=2))
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
