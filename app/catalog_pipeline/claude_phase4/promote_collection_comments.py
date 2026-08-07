"""
promote_collection_comments.py v1.0
====================================
B26 Phase 4, part 2: migrates the mod.io and Nexus Collections comment
corpora (captured 2026-07-24, never previously loaded into the DB) into a
new catalog_collection_comments table, keyed to catalog_collections rather
than platform_listings -- collection comments aren't about a single mod.

Real counts (verified 2026-08-07 against the source files directly, not
assumed from prior documentation): data/collections/modio/
modio_collections_comments.jsonl has 968 lines, 811 of them "_status":
"no_comments" sentinels, leaving 157 real comments across 843 collections
(the 2026-07-24 CLAUDE.md entry's "968 real comment rows" figure was
actually the file's total line count, not the real-comment count --
corrected here). data/collections/nexus/nexus_collections_comments.jsonl
has 4999 lines, 34 sentinels, 4965 real comments across 87 collections.
"""
import argparse
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.catalog_pipeline.claude_phase3.promote_comment_evidence import (
    sha256_file,
    verify_db_hash,
    backup_database,
)


def build_collection_comment_uuid(platform: str, collection_native_id: str, source_comment_id: str) -> str:
    seed = f"bg3:phase4-collection-comment:{platform}:{collection_native_id}:{source_comment_id}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))


def parse_modio_comment_line(line: str):
    row = json.loads(line)
    if "_status" in row:
        return None
    user = row.get("user") or {}
    observed_at = None
    if row.get("date_added") is not None:
        observed_at = datetime.fromtimestamp(row["date_added"], tz=timezone.utc).isoformat()
    return {
        "collection_native_id": str(row["collection_id"]),
        "source_comment_id": str(row["id"]),
        "parent_source_comment_id": (
            str(row["reply_id"]) if row.get("reply_id") not in (None, 0) else None
        ),
        "author_display_name": user.get("username"),
        "author_user_id": str(user["id"]) if user.get("id") is not None else None,
        "observed_at": observed_at,
        "body": row.get("content") or "",
        "payload_json": json.dumps(row),
    }


def parse_nexus_comment_line(line: str):
    row = json.loads(line)
    if "_status" in row:
        return None
    return {
        "collection_native_id": row["collection_slug"],
        "source_comment_id": str(row["comment_id"]),
        "parent_source_comment_id": (
            str(row["parent_comment_id"]) if row.get("parent_comment_id") is not None else None
        ),
        "author_display_name": row.get("creator_name"),
        "author_user_id": None,
        "observed_at": row.get("created_at"),
        "body": row.get("body") or "",
        "payload_json": json.dumps(row),
    }


PARSERS = {"modio": parse_modio_comment_line, "nexus": parse_nexus_comment_line}


def load_collection_lookup(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        "SELECT platform, collection_native_id, collection_uuid FROM catalog_collections"
    ).fetchall()
    return {(platform, native_id): uid for platform, native_id, uid in rows}


def insert_collection_comments(
    conn: sqlite3.Connection,
    platform: str,
    filepath: Path,
    corpus_sha256: str,
    collection_lookup: dict,
) -> tuple[int, int]:
    parser = PARSERS[platform]
    inserted = 0
    skipped_unmapped = 0
    with open(filepath, "r", encoding="utf-8") as fh:
        for line_number, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            parsed = parser(line)
            if parsed is None:
                continue
            collection_uuid = collection_lookup.get((platform, parsed["collection_native_id"]))
            if collection_uuid is None:
                skipped_unmapped += 1
                continue
            comment_uuid = build_collection_comment_uuid(
                platform, parsed["collection_native_id"], parsed["source_comment_id"]
            )
            conn.execute(
                """INSERT INTO catalog_collection_comments
                   (comment_uuid, collection_uuid, platform, source_comment_id,
                    parent_source_comment_id, author_display_name, author_user_id,
                    observed_at, body, payload_json, source_corpus_sha256, source_line_number)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    comment_uuid,
                    collection_uuid,
                    platform,
                    parsed["source_comment_id"],
                    parsed["parent_source_comment_id"],
                    parsed["author_display_name"],
                    parsed["author_user_id"],
                    parsed["observed_at"],
                    parsed["body"],
                    parsed["payload_json"],
                    corpus_sha256,
                    line_number,
                ),
            )
            inserted += 1
    return inserted, skipped_unmapped


def run_migration(db_path: Path, expected_sha256: str, modio_path: Path, nexus_path: Path) -> dict:
    verify_db_hash(db_path, expected_sha256)
    backup_path = backup_database(db_path, suffix=".pre-phase4-backup")
    modio_sha256 = sha256_file(modio_path)
    nexus_sha256 = sha256_file(nexus_path)

    conn = sqlite3.connect(str(db_path))
    try:
        # Foreign keys are connection-local and off by default in SQLite --
        # matches the pattern claude_phase3/promote_comment_evidence.py
        # already establishes for this project's migrations.
        conn.execute("PRAGMA foreign_keys = ON")
        # Python's sqlite3 module only auto-opens an implicit transaction
        # before DML, not before DDL (CREATE TABLE/INDEX autocommit
        # individually) -- SQLite itself fully supports transactional DDL,
        # so an explicit BEGIN/commit-or-rollback here is what actually
        # makes the table creation + both platforms' inserts atomic (a
        # mid-run failure would otherwise leave the table created but only
        # partially populated).
        conn.execute("BEGIN")
        try:
            # Claim the migration slot first: migration_history.migration_name
            # is UNIQUE, so a rerun raises IntegrityError right here -- before
            # CREATE TABLE ever runs, which would otherwise fail with a
            # confusing "table already exists" OperationalError instead of
            # the clean, deterministic failure this project's migrations
            # require. Also matches promote_comment_evidence.py's own
            # migration_history bookkeeping, which this script previously
            # skipped entirely.
            conn.execute(
                """INSERT INTO migration_history
                   (migration_name, schema_version, applied_at, actor_session,
                    source_db_sha256, row_count_before, row_count_after, notes)
                   VALUES (?, 'phase4', ?, 'claude-code-phase4', ?, '0', '0', 'pending')""",
                (
                    "b26-phase4-collection-comments",
                    datetime.now(timezone.utc).isoformat(),
                    expected_sha256,
                ),
            )

            conn.execute(
                """
                CREATE TABLE catalog_collection_comments (
                    comment_uuid TEXT PRIMARY KEY,
                    collection_uuid TEXT NOT NULL REFERENCES catalog_collections(collection_uuid),
                    platform TEXT NOT NULL CHECK(platform IN ('modio', 'nexus')),
                    source_comment_id TEXT NOT NULL,
                    parent_source_comment_id TEXT,
                    author_display_name TEXT,
                    author_user_id TEXT,
                    observed_at TEXT,
                    body TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    source_corpus_sha256 TEXT NOT NULL,
                    source_line_number INTEGER NOT NULL,
                    UNIQUE(platform, source_comment_id)
                )
                """
            )
            conn.execute(
                """CREATE INDEX idx_catalog_collection_comments_collection
                   ON catalog_collection_comments(collection_uuid, platform)"""
            )

            lookup = load_collection_lookup(conn)
            modio_inserted, modio_skipped_unmapped = insert_collection_comments(
                conn, "modio", modio_path, modio_sha256, lookup
            )
            nexus_inserted, nexus_skipped_unmapped = insert_collection_comments(
                conn, "nexus", nexus_path, nexus_sha256, lookup
            )

            conn.execute(
                """UPDATE migration_history SET row_count_after = ?, notes = ?
                   WHERE migration_name = ?""",
                (
                    str(modio_inserted + nexus_inserted),
                    f"modio +{modio_inserted} (skipped {modio_skipped_unmapped} unmapped), "
                    f"nexus +{nexus_inserted} (skipped {nexus_skipped_unmapped} unmapped)",
                    "b26-phase4-collection-comments",
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
        "migration_name": "b26-phase4-collection-comments",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "pre_migration_sha256": expected_sha256,
        "backup_path": str(backup_path),
        "modio_source_sha256": modio_sha256,
        "nexus_source_sha256": nexus_sha256,
        "modio_rows_inserted": modio_inserted,
        "nexus_rows_inserted": nexus_inserted,
        "modio_rows_skipped_unmapped": modio_skipped_unmapped,
        "nexus_rows_skipped_unmapped": nexus_skipped_unmapped,
        "post_migration_sha256": post_sha256,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--candidate-sha256", required=True)
    parser.add_argument(
        "--modio-comments", type=Path,
        default=Path("data/collections/modio/modio_collections_comments.jsonl"),
    )
    parser.add_argument(
        "--nexus-comments", type=Path,
        default=Path("data/collections/nexus/nexus_collections_comments.jsonl"),
    )
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()

    receipt = run_migration(args.db, args.candidate_sha256, args.modio_comments, args.nexus_comments)
    args.receipt.write_text(json.dumps(receipt, indent=2))
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
