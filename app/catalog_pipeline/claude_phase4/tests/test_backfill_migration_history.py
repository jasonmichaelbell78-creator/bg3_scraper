from app.catalog_pipeline.claude_phase4.backfill_migration_history import build_migration_history_rows


def test_build_migration_history_rows_from_real_receipt_shapes():
    view_fix_receipt = {
        "migration_name": "b26-phase4-mod-comments-view-fix",
        "run_at": "2026-08-07T11:51:23.901544+00:00",
        "pre_migration_sha256": "cdefc294...",
        "modio_rows_before": 132276,
        "modio_rows_after": 76043,
        "nexus_rows_before": 451885,
        "nexus_rows_after": 451885,
    }
    collection_comments_receipt = {
        "migration_name": "b26-phase4-collection-comments",
        "run_at": "2026-08-07T11:54:22.888626+00:00",
        "pre_migration_sha256": "e31f9cf5...",
        "modio_rows_inserted": 157,
        "nexus_rows_inserted": 4965,
    }

    rows = build_migration_history_rows(view_fix_receipt, collection_comments_receipt)

    assert len(rows) == 2
    view_row, comments_row = rows

    assert view_row["migration_name"] == "b26-phase4-mod-comments-view-fix"
    assert view_row["applied_at"] == "2026-08-07T11:51:23.901544+00:00"
    assert view_row["source_db_sha256"] == "cdefc294..."
    assert view_row["row_count_before"] == str(132276 + 451885)
    assert view_row["row_count_after"] == str(76043 + 451885)

    assert comments_row["migration_name"] == "b26-phase4-collection-comments"
    assert comments_row["applied_at"] == "2026-08-07T11:54:22.888626+00:00"
    assert comments_row["row_count_before"] == "0"
    assert comments_row["row_count_after"] == str(157 + 4965)
