#!/usr/bin/env python3
"""Build the Phase 2A companion Comment Evidence Index from canonical JSONL sources.

This is intentionally separate from B26. It creates a queryable source layer and
triage-only candidates; it cannot create claims, evidence links, reviews, or promotions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path


EXPECTED = {
    "modio": {
        "sha256": "bcd546e99781a0005390e6e3367460d0f34930f0d35a11863a39689d4155893a",
        "rows": 76043,
        "file_id": "14YPOSdyNu97XnzI83mPMKvNckfidNc7j",
    },
    "nexus": {
        "sha256": "3e931c96f6456b044161ef7e7f64cb4b51d9de32d89d1a0c19bd1b89114934e0",
        "rows": 451885,
        "file_id": "1NBiw0ln6JTzt8APcM3uUcIHKn289WH9V",
    },
}

RULES: dict[str, tuple[str, re.Pattern[str]]] = {
    "author_context": (
        "Apparent first-person maintenance/platform guidance; never identity-elevating from comments alone.",
        re.compile(r"\b(?:i|we)\s+(?:updated|fixed|patched|made|maintain(?:ed)?|released|uploaded)\b", re.I),
    ),
    "required_dependency": (
        "Requirement wording; candidate only until a specific named dependency and declarative context are verified.",
        re.compile(r"\b(?:requires?|needs?|won'?t\s+work|does(?:\s+not|n't)\s+work)\s+(?:without|with)\b", re.I),
    ),
    "incompatibility": (
        "Observed conflict wording; hedged or question-form wording is excluded.",
        re.compile(r"\b(?:incompatible\s+with|conflicts?\s+with|breaks?\s+with|does(?:\s+not|n't)\s+work\s+with)\b", re.I),
    ),
    "relative_load_order": (
        "Actionable load-order wording; relative target still requires context and target resolution.",
        re.compile(r"\b(?:load\s+order|loadorder)\b.{0,180}\b(?:before|after|above|below|last|bottom|top)\b", re.I | re.S),
    ),
    "file_variant_advice": (
        "Existing file/variant wording; requests and questions are excluded.",
        re.compile(r"\b(?:optional\s+file|main\s+file|choose\s+(?:the\s+)?(?:file|version|variant)|use\s+(?:the\s+)?(?:file|version|variant))\b", re.I),
    ),
    "named_patch_addon": (
        "Patch/add-on wording; availability and both targets require later verification.",
        re.compile(r"\b(?:compatibility\s+patch|compat\s+patch|patch\s+for|add[- ]on)\b", re.I),
    ),
    "acquisition_content": (
        "Positive acquisition/location wording; questions and missing-item reports are excluded.",
        re.compile(r"\b(?:can\s+be\s+found\s+in|found\s+in|sold\s+by|located\s+in|is\s+in\s+the\s+tutorial\s+chest)\b", re.I),
    ),
}

QUESTION_OR_REQUEST = re.compile(
    r"(?:\?|\b(?:any\s+chance|can\s+you|could\s+you|would\s+like|i'?d\s+like|where\s+can\s+i|where\s+do\s+i|request(?:ing)?|wish)\b)",
    re.I,
)
HEDGE = re.compile(r"\b(?:i\s+(?:suspect|think|wonder)|maybe|perhaps|might|could\s+be)\b", re.I)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def initialize(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        PRAGMA foreign_keys = ON;
        PRAGMA journal_mode = WAL;
        PRAGMA synchronous = NORMAL;

        CREATE TABLE corpus_registry (
            corpus_key TEXT PRIMARY KEY,
            platform TEXT NOT NULL UNIQUE CHECK(platform IN ('modio', 'nexus')),
            canonical_drive_file_id TEXT NOT NULL,
            source_filename TEXT NOT NULL,
            source_sha256 TEXT NOT NULL CHECK(length(source_sha256) = 64),
            source_rows INTEGER NOT NULL,
            coverage_description TEXT NOT NULL,
            author_identity_constraint TEXT NOT NULL,
            registered_at TEXT NOT NULL
        );

        CREATE TABLE comments (
            comment_row_id INTEGER PRIMARY KEY,
            comment_uid TEXT NOT NULL UNIQUE,
            platform TEXT NOT NULL CHECK(platform IN ('modio', 'nexus')),
            platform_mod_id TEXT NOT NULL,
            source_comment_id TEXT NOT NULL,
            parent_source_comment_id TEXT,
            thread_locator TEXT,
            threading_model TEXT NOT NULL CHECK(threading_model IN ('modio_dotted_reply', 'nexus_parent_pointer')),
            thread_depth INTEGER,
            author_display_name TEXT,
            author_user_id TEXT,
            author_url TEXT,
            author_identity_tier TEXT NOT NULL DEFAULT 'unverified_displayed_name_match',
            author_identity_note TEXT NOT NULL,
            is_sticky INTEGER,
            created_epoch INTEGER,
            captured_timestamp TEXT,
            body TEXT NOT NULL,
            source_line_number INTEGER NOT NULL,
            source_corpus_sha256 TEXT NOT NULL,
            coverage_state TEXT NOT NULL CHECK(coverage_state IN ('complete_capture', 'partial_capture')),
            b26_listing_link_state TEXT NOT NULL DEFAULT 'deferred_b26_materialization',
            b26_listing_uuid TEXT,
            UNIQUE(platform, platform_mod_id, source_comment_id)
        );
        CREATE INDEX idx_comments_platform_mod ON comments(platform, platform_mod_id);
        CREATE INDEX idx_comments_parent ON comments(platform, platform_mod_id, parent_source_comment_id);
        CREATE INDEX idx_comments_coverage ON comments(coverage_state, platform, platform_mod_id);
        CREATE INDEX idx_comments_created ON comments(platform, created_epoch);

        CREATE VIRTUAL TABLE comment_fts USING fts5(
            comment_uid UNINDEXED,
            body,
            author_display_name,
            tokenize='unicode61'
        );

        CREATE TABLE triage_rule_catalog (
            rule_code TEXT PRIMARY KEY,
            priority_order INTEGER NOT NULL,
            display_name TEXT NOT NULL,
            operational_limit TEXT NOT NULL,
            author_tier_elevating INTEGER NOT NULL DEFAULT 0 CHECK(author_tier_elevating = 0)
        );

        CREATE TABLE triage_hits (
            hit_id INTEGER PRIMARY KEY,
            comment_row_id INTEGER NOT NULL REFERENCES comments(comment_row_id),
            rule_code TEXT NOT NULL REFERENCES triage_rule_catalog(rule_code),
            pattern_note TEXT NOT NULL,
            disposition_state TEXT NOT NULL DEFAULT 'triage_only_context_required'
                CHECK(disposition_state = 'triage_only_context_required'),
            full_comment_required INTEGER NOT NULL DEFAULT 1 CHECK(full_comment_required = 1),
            created_at TEXT NOT NULL,
            UNIQUE(comment_row_id, rule_code)
        );
        CREATE INDEX idx_triage_hits_rule ON triage_hits(rule_code, comment_row_id);

        CREATE TABLE build_metadata (
            metadata_key TEXT PRIMARY KEY,
            metadata_value TEXT NOT NULL
        );
        """
    )


def should_record(rule_code: str, body: str) -> bool:
    if rule_code in {"file_variant_advice", "named_patch_addon"} and QUESTION_OR_REQUEST.search(body):
        return False
    if rule_code == "acquisition_content" and QUESTION_OR_REQUEST.search(body):
        return False
    if rule_code == "incompatibility" and HEDGE.search(body):
        return False
    return True


def modio_row(record: dict, line_no: int, corpus_sha: str) -> tuple:
    source_id = str(record["id"])
    mod_id = str(record["mod_id"])
    reply_id = int(record["reply_id"])
    thread_position = record["thread_position"]
    user = record.get("user") or {}
    return (
        f"modio:{mod_id}:{source_id}", "modio", mod_id, source_id,
        None if reply_id == 0 else str(reply_id), thread_position,
        "modio_dotted_reply", len(str(thread_position).split(".")),
        user.get("display_name_portal") or user.get("username"),
        str(user["id"]) if user.get("id") is not None else None,
        user.get("profile_url"), "unverified_displayed_name_match",
        "No comment-derived team/author elevation; same-mod user.id→team-roster join is separately required.",
        None, int(record["date_added"]), None, record["content"], line_no,
        corpus_sha, "complete_capture", "deferred_b26_materialization", None,
    )


def nexus_row(record: dict, line_no: int, corpus_sha: str) -> tuple:
    source_id = str(record["comment_id"])
    mod_id = str(record["mod_id"])
    partial = mod_id in {"279", "22659"}
    return (
        f"nexus:{mod_id}:{source_id}", "nexus", mod_id, source_id,
        str(record["parent_comment_id"]) if record.get("parent_comment_id") is not None else None,
        record.get("thread_id"), "nexus_parent_pointer", None,
        record.get("username"), None, record.get("user_url"),
        "unverified_displayed_name_match",
        "No author/role/badge field provides a corpus-derived Nexus identity-elevation path.",
        int(bool(record.get("is_sticky"))), int(record["timestamp_unix"]), record.get("_fetched_at"),
        record["text"], line_no, corpus_sha,
        "partial_capture" if partial else "complete_capture", "deferred_b26_materialization", None,
    )


INSERT_COMMENT = """
INSERT INTO comments (
 comment_uid, platform, platform_mod_id, source_comment_id, parent_source_comment_id,
 thread_locator, threading_model, thread_depth, author_display_name, author_user_id,
 author_url, author_identity_tier, author_identity_note, is_sticky, created_epoch,
 captured_timestamp, body, source_line_number, source_corpus_sha256, coverage_state,
 b26_listing_link_state, b26_listing_uuid
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def populate(con: sqlite3.Connection, platform: str, path: Path, source_sha: str) -> Counter:
    counts: Counter = Counter()
    fts_batch: list[tuple[str, str, str | None]] = []
    hit_batch: list[tuple[int, str, str, str]] = []
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            record = json.loads(line)
            row = modio_row(record, line_no, source_sha) if platform == "modio" else nexus_row(record, line_no, source_sha)
            cursor = con.execute(INSERT_COMMENT, row)
            comment_row_id = cursor.lastrowid
            fts_batch.append((row[0], row[16], row[8]))
            for rule_code, (note, pattern) in RULES.items():
                if pattern.search(row[16]) and should_record(rule_code, row[16]):
                    hit_batch.append((comment_row_id, rule_code, note, datetime.now(UTC).replace(microsecond=0).isoformat()))
                    counts[rule_code] += 1
            counts["rows"] += 1
            if len(fts_batch) >= 5000:
                con.executemany("INSERT INTO comment_fts(comment_uid, body, author_display_name) VALUES (?, ?, ?)", fts_batch)
                fts_batch.clear()
            if len(hit_batch) >= 5000:
                con.executemany("INSERT INTO triage_hits(comment_row_id, rule_code, pattern_note, created_at) VALUES (?, ?, ?, ?)", hit_batch)
                hit_batch.clear()
            if line_no % 20000 == 0:
                con.commit()
    if fts_batch:
        con.executemany("INSERT INTO comment_fts(comment_uid, body, author_display_name) VALUES (?, ?, ?)", fts_batch)
    if hit_batch:
        con.executemany("INSERT INTO triage_hits(comment_row_id, rule_code, pattern_note, created_at) VALUES (?, ?, ?, ?)", hit_batch)
    con.commit()
    return counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--modio", type=Path, required=True)
    parser.add_argument("--nexus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()

    if args.output.exists():
        raise SystemExit(f"Refusing to overwrite existing index: {args.output}")
    inputs = {"modio": args.modio, "nexus": args.nexus}
    verified = {}
    for platform, path in inputs.items():
        actual_sha = sha256(path)
        row_count = sum(1 for _ in path.open(encoding="utf-8"))
        expected = EXPECTED[platform]
        if actual_sha != expected["sha256"] or row_count != expected["rows"]:
            raise SystemExit(f"Unexpected {platform} input: {actual_sha} / {row_count}")
        verified[platform] = {"sha256": actual_sha, "rows": row_count, "path": str(path)}

    con = sqlite3.connect(args.output)
    con.execute("PRAGMA foreign_keys = ON")
    initialize(con)
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    con.executemany(
        "INSERT INTO corpus_registry VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("modio_comments", "modio", EXPECTED["modio"]["file_id"], args.modio.name, EXPECTED["modio"]["sha256"], 76043,
             "Complete final deduplicated capture.",
             "No comment-derived elevation; separately authorized same-mod roster join required.", now),
            ("nexus_comments", "nexus", EXPECTED["nexus"]["file_id"], args.nexus.name, EXPECTED["nexus"]["sha256"], 451885,
             "Complete Tier 1/2 target sweep except permanent partial captures for 279 and 22659.",
             "No author/role/badge field supports corpus-derived identity elevation.", now),
        ],
    )
    labels = [
        ("author_context", 1, "Author/platform guidance"),
        ("required_dependency", 2, "Explicit required dependency"),
        ("incompatibility", 3, "Incompatibility"),
        ("relative_load_order", 4, "Relative load order"),
        ("file_variant_advice", 5, "File or variant advice"),
        ("named_patch_addon", 6, "Named patch or add-on"),
        ("acquisition_content", 7, "Acquisition or content fact"),
    ]
    con.executemany(
        "INSERT INTO triage_rule_catalog(rule_code, priority_order, display_name, operational_limit) VALUES (?, ?, ?, ?)",
        [(code, order, name, RULES[code][0]) for code, order, name in labels],
    )
    con.commit()
    triage_counts = {platform: dict(populate(con, platform, path, verified[platform]["sha256"])) for platform, path in inputs.items()}
    con.execute("INSERT INTO build_metadata VALUES (?, ?)", ("schema_version", "phase2a-comment-evidence-index-1"))
    con.execute("INSERT INTO build_metadata VALUES (?, ?)", ("built_at", now))
    con.execute("INSERT INTO build_metadata VALUES (?, ?)", ("b26_reference_db", "not materialized in this run; no B26 listing links were written"))
    con.commit()

    integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
    fk_violations = len(con.execute("PRAGMA foreign_key_check").fetchall())
    result = {
        "built_at": now,
        "schema_version": "phase2a-comment-evidence-index-1",
        "inputs": verified,
        "index_sha256": sha256(args.output),
        "validation": {
            "integrity_check": integrity,
            "foreign_key_violations": fk_violations,
            "comment_rows": con.execute("SELECT COUNT(*) FROM comments").fetchone()[0],
            "fts_rows": con.execute("SELECT COUNT(*) FROM comment_fts").fetchone()[0],
            "triage_hits": con.execute("SELECT COUNT(*) FROM triage_hits").fetchone()[0],
            "partial_capture_rows": con.execute("SELECT COUNT(*) FROM comments WHERE coverage_state = 'partial_capture'").fetchone()[0],
            "orphan_reply_refs": con.execute("""
              SELECT COUNT(*) FROM comments c
              WHERE c.parent_source_comment_id IS NOT NULL
                AND NOT EXISTS (
                  SELECT 1 FROM comments p
                  WHERE p.platform = c.platform AND p.platform_mod_id = c.platform_mod_id
                    AND p.source_comment_id = c.parent_source_comment_id
                )
            """).fetchone()[0],
            "b26_links_written": con.execute("SELECT COUNT(*) FROM comments WHERE b26_listing_uuid IS NOT NULL").fetchone()[0],
            "fts_smoke": {
                "load_order": con.execute("SELECT COUNT(*) FROM comment_fts WHERE comment_fts MATCH 'load order'").fetchone()[0],
                "tutorial_chest": con.execute("SELECT COUNT(*) FROM comment_fts WHERE comment_fts MATCH 'tutorial chest'").fetchone()[0],
                "requires": con.execute("SELECT COUNT(*) FROM comment_fts WHERE comment_fts MATCH 'requires'").fetchone()[0],
            },
        },
        "triage_counts_by_platform": triage_counts,
        "triage_counts_by_rule": dict(con.execute("SELECT rule_code, COUNT(*) FROM triage_hits GROUP BY rule_code ORDER BY rule_code")),
        "limits": [
            "All triage hits remain context-required candidates; no claims/evidence/reviews/promotions are created.",
            "No author identity is elevated from either comment corpus.",
            "B26 was not materialized in this run; exact listing links remain deferred.",
            "Nexus mods 279 and 22659 are marked partial_capture, never clean zero-signal coverage.",
        ],
    }
    args.receipt.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if integrity != "ok" or fk_violations:
        raise SystemExit("Index validation failed")
    con.close()


if __name__ == "__main__":
    main()
