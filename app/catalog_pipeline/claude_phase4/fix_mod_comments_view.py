"""
fix_mod_comments_view.py v1.0
==============================
B26 Phase 4, part 1: fixes mod_comments to respect evidence_corpora's own
supersedes_corpus_uuid column.

Found 2026-08-07: the corrected mod.io comment corpora
(modio_comments_base_under_page_limit_2026-07-21,
modio_comments_deep_refresh_2026-07-21) correctly declare
supersedes_corpus_uuid pointing at the buggy, ~100-comment-capped
modio_fullsweep_comments_2026-07-10 corpus -- but mod_comments never
filtered on that column, so all three corpora's rows surfaced at once:
132,276 mod.io rows in the view instead of the correct 76,043 (56,231 of
the buggy corpus's 56,233 rows are literal duplicates of rows already
present in the corrected corpora). This rebuilds the view to exclude any
corpus_uuid referenced by another corpus's supersedes_corpus_uuid, which
generalizes to any future supersession, not just this one.
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

NEW_VIEW_SQL = """
CREATE VIEW mod_comments AS
   SELECT
       esr.source_record_uuid AS comment_uuid,
       ec.provider AS platform,
       esr.provider_native_id AS source_comment_id,
       esr.source_listing_uuid AS listing_uuid,
       esr.parent_provider_native_id AS parent_source_comment_id,
       esr.displayed_author AS author,
       esr.observed_at AS observed_at,
       esr.payload_json AS payload_json
   FROM evidence_source_records esr
   JOIN evidence_corpora ec ON ec.corpus_uuid = esr.corpus_uuid
   WHERE esr.provider_object_type = 'comment'
     AND ec.corpus_uuid NOT IN (
         SELECT supersedes_corpus_uuid FROM evidence_corpora
         WHERE supersedes_corpus_uuid IS NOT NULL
     )
"""


def rebuild_mod_comments_view(conn: sqlite3.Connection) -> None:
    conn.execute("DROP VIEW mod_comments")
    conn.execute(NEW_VIEW_SQL)


def run_fix(db_path: Path, expected_sha256: str) -> dict:
    verify_db_hash(db_path, expected_sha256)
    backup_path = backup_database(db_path, suffix=".pre-phase4-backup")

    conn = sqlite3.connect(str(db_path))
    try:
        # Python's sqlite3 module only auto-opens an implicit transaction
        # before DML, not before DDL (CREATE/DROP autocommit individually) --
        # SQLite itself fully supports transactional DDL, so an explicit
        # BEGIN/commit-or-rollback here is what actually makes the DROP VIEW
        # + CREATE VIEW pair atomic (a mid-run failure would otherwise leave
        # the DB with mod_comments dropped and not yet recreated).
        conn.execute("BEGIN")
        try:
            before = dict(
                conn.execute(
                    "SELECT platform, COUNT(*) FROM mod_comments GROUP BY platform"
                ).fetchall()
            )
            rebuild_mod_comments_view(conn)
            after = dict(
                conn.execute(
                    "SELECT platform, COUNT(*) FROM mod_comments GROUP BY platform"
                ).fetchall()
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()

    post_sha256 = sha256_file(db_path)
    receipt = {
        "migration_name": "b26-phase4-mod-comments-view-fix",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "pre_migration_sha256": expected_sha256,
        "backup_path": str(backup_path),
        "modio_rows_before": before.get("modio", 0),
        "modio_rows_after": after.get("modio", 0),
        "nexus_rows_before": before.get("nexus", 0),
        "nexus_rows_after": after.get("nexus", 0),
        "post_migration_sha256": post_sha256,
    }
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--candidate-sha256", required=True)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()

    receipt = run_fix(args.db, args.candidate_sha256)
    args.receipt.write_text(json.dumps(receipt, indent=2))
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
