#!/usr/bin/env python3
"""Idempotently finalize the Phase 2A evidence-index candidate and write a stable receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()

    con = sqlite3.connect(args.db)
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("BEGIN IMMEDIATE")
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS comment_thread_link_audit (
            comment_row_id INTEGER PRIMARY KEY REFERENCES comments(comment_row_id),
            parent_link_state TEXT NOT NULL CHECK(parent_link_state IN ('root', 'retained_parent', 'parent_not_retained'))
        )
        """
    )
    con.execute("DELETE FROM comment_thread_link_audit")
    con.execute(
        """
        INSERT INTO comment_thread_link_audit(comment_row_id, parent_link_state)
        SELECT c.comment_row_id,
            CASE
                WHEN c.parent_source_comment_id IS NULL THEN 'root'
                WHEN EXISTS (
                    SELECT 1 FROM comments p
                    WHERE p.platform = c.platform
                      AND p.platform_mod_id = c.platform_mod_id
                      AND p.source_comment_id = c.parent_source_comment_id
                ) THEN 'retained_parent'
                ELSE 'parent_not_retained'
            END
        FROM comments c
        """
    )
    con.execute(
        "INSERT OR REPLACE INTO build_metadata(metadata_key, metadata_value) VALUES (?, ?)",
        ("thread_link_audit", "parent_not_retained is explicit; it is never treated as a root comment"),
    )
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()

    read = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    read.row_factory = sqlite3.Row
    integrity = read.execute("PRAGMA integrity_check").fetchone()[0]
    fk_violations = len(read.execute("PRAGMA foreign_key_check").fetchall())
    result = {
        "finalized_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "index_sha256": sha256(args.db),
        "validation": {
            "integrity_check": integrity,
            "foreign_key_violations": fk_violations,
            "comment_rows": read.execute("SELECT COUNT(*) FROM comments").fetchone()[0],
            "fts_rows": read.execute("SELECT COUNT(*) FROM comment_fts").fetchone()[0],
            "triage_hits": read.execute("SELECT COUNT(*) FROM triage_hits").fetchone()[0],
            "partial_capture_rows": read.execute("SELECT COUNT(*) FROM comments WHERE coverage_state = 'partial_capture'").fetchone()[0],
            "thread_link_states": dict(read.execute("SELECT parent_link_state, COUNT(*) FROM comment_thread_link_audit GROUP BY parent_link_state")),
            "b26_listing_links_written": read.execute("SELECT COUNT(*) FROM comments WHERE b26_listing_uuid IS NOT NULL").fetchone()[0],
            "fts_smoke": {
                "load_order": read.execute("SELECT COUNT(*) FROM comment_fts WHERE comment_fts MATCH 'load order'").fetchone()[0],
                "tutorial_chest": read.execute("SELECT COUNT(*) FROM comment_fts WHERE comment_fts MATCH 'tutorial chest'").fetchone()[0],
                "requires": read.execute("SELECT COUNT(*) FROM comment_fts WHERE comment_fts MATCH 'requires'").fetchone()[0],
            },
        },
        "input_corpora": [dict(row) for row in read.execute("SELECT * FROM corpus_registry ORDER BY platform")],
        "triage_by_rule": dict(read.execute("SELECT rule_code, COUNT(*) FROM triage_hits GROUP BY rule_code ORDER BY rule_code")),
        "limits": [
            "The index is a separate Phase 2A companion database; B26 was not changed.",
            "Every triage hit is context-required and has no claim/evidence/review/promotion effect.",
            "No author identity is elevated from either corpus.",
            "Nexus 279 and 22659 are partial_capture, not zero-signal coverage.",
            "Exact B26 listing links remain deferred until the B26 snapshot is rematerialized locally.",
        ],
    }
    read.close()
    if integrity != "ok" or fk_violations:
        raise SystemExit("Validation failed")
    args.receipt.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
