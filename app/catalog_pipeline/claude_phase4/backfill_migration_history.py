"""
backfill_migration_history.py v1.0
===================================
B26 Phase 4, one-off backfill: records migration_history rows for the two
real Phase 4 migrations (mod_comments view fix, collection comments) that
already ran successfully against the live candidate DB on 2026-08-07 --
before f0404b6 added the migration_history gate those scripts now write on
every run. Without this backfill, the live DB has no record of either
migration in migration_history (unlike Phase 3, which always had one), and
a future accidental rerun of either script wouldn't be blocked cleanly by
the new IntegrityError gate -- fix_mod_comments_view.py would silently
no-op (its view rebuild is idempotent), and promote_collection_comments.py
would still fail, but via the old confusing OperationalError rather than
the new clean IntegrityError, since no migration_history row exists yet to
collide with.

Reads the two real receipts already on disk
(catalog/B26/phase4_view_fix_receipt.json,
catalog/B26/phase4_collection_comments_receipt.json) as the source of
truth for applied_at/row-counts/hashes -- this script inserts rows that
describe what already happened, it does not re-derive or guess at them.
"""
import argparse
import json
import sqlite3
from pathlib import Path

from app.catalog_pipeline.claude_phase3.promote_comment_evidence import (
    sha256_file,
    verify_db_hash,
    backup_database,
)


def build_migration_history_rows(view_fix_receipt: dict, collection_comments_receipt: dict) -> list[dict]:
    return [
        {
            "migration_name": view_fix_receipt["migration_name"],
            "schema_version": "phase4",
            "applied_at": view_fix_receipt["run_at"],
            "actor_session": "claude-code-phase4",
            "source_db_sha256": view_fix_receipt["pre_migration_sha256"],
            "row_count_before": str(
                view_fix_receipt["modio_rows_before"] + view_fix_receipt["nexus_rows_before"]
            ),
            "row_count_after": str(
                view_fix_receipt["modio_rows_after"] + view_fix_receipt["nexus_rows_after"]
            ),
            "notes": (
                f"Backfilled 2026-08-07 from phase4_view_fix_receipt.json (real run "
                f"2026-08-07T11:51:23Z, predates the migration_history gate). "
                f"modio {view_fix_receipt['modio_rows_before']}->{view_fix_receipt['modio_rows_after']}, "
                f"nexus {view_fix_receipt['nexus_rows_before']}->{view_fix_receipt['nexus_rows_after']}."
            ),
        },
        {
            "migration_name": collection_comments_receipt["migration_name"],
            "schema_version": "phase4",
            "applied_at": collection_comments_receipt["run_at"],
            "actor_session": "claude-code-phase4",
            "source_db_sha256": collection_comments_receipt["pre_migration_sha256"],
            "row_count_before": "0",
            "row_count_after": str(
                collection_comments_receipt["modio_rows_inserted"]
                + collection_comments_receipt["nexus_rows_inserted"]
            ),
            "notes": (
                f"Backfilled 2026-08-07 from phase4_collection_comments_receipt.json (real run "
                f"2026-08-07T11:54:22Z, predates the migration_history gate). "
                f"modio +{collection_comments_receipt['modio_rows_inserted']}, "
                f"nexus +{collection_comments_receipt['nexus_rows_inserted']}."
            ),
        },
    ]


def run_backfill(db_path: Path, expected_sha256: str, view_fix_receipt_path: Path, collection_comments_receipt_path: Path) -> dict:
    verify_db_hash(db_path, expected_sha256)
    backup_path = backup_database(db_path, suffix=".pre-phase4-migration-history-backfill-backup")

    view_fix_receipt = json.loads(view_fix_receipt_path.read_text())
    collection_comments_receipt = json.loads(collection_comments_receipt_path.read_text())
    rows = build_migration_history_rows(view_fix_receipt, collection_comments_receipt)

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN")
        try:
            for row in rows:
                conn.execute(
                    """INSERT INTO migration_history
                       (migration_name, schema_version, applied_at, actor_session,
                        source_db_sha256, row_count_before, row_count_after, notes)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        row["migration_name"],
                        row["schema_version"],
                        row["applied_at"],
                        row["actor_session"],
                        row["source_db_sha256"],
                        row["row_count_before"],
                        row["row_count_after"],
                        row["notes"],
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
        "migration_name": "b26-phase4-migration-history-backfill",
        "pre_migration_sha256": expected_sha256,
        "backup_path": str(backup_path),
        "rows_inserted": [row["migration_name"] for row in rows],
        "post_migration_sha256": post_sha256,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--candidate-sha256", required=True)
    parser.add_argument(
        "--view-fix-receipt", type=Path,
        default=Path("catalog/B26/phase4_view_fix_receipt.json"),
    )
    parser.add_argument(
        "--collection-comments-receipt", type=Path,
        default=Path("catalog/B26/phase4_collection_comments_receipt.json"),
    )
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()

    receipt = run_backfill(
        args.db, args.candidate_sha256, args.view_fix_receipt, args.collection_comments_receipt
    )
    args.receipt.write_text(json.dumps(receipt, indent=2))
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
