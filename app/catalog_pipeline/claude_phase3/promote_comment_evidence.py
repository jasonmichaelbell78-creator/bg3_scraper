"""
promote_comment_evidence.py v1.0
=================================
B26 Phase 3: promotes comment-derived evidence into the active B26 baseline.

Inserts the 451,885 Nexus comments from the Phase 2B comment-evidence-index
into evidence_source_records (mod.io's 76,043 comments already exist there --
never re-inserted, confirmed via set-membership check during design).
Promotes all 16,996 triage_hits (both platforms) into evidence_claims,
tagged evidence_state='triage_only' -- explicitly unvalidated. Retires
mod_comments (drops the table, replaces it with a view).

See docs/superpowers/specs/2026-08-05-b26-phase3-comment-evidence-migration-design.md
for the full design and rationale.
"""
import hashlib
import json
import shutil
import sqlite3
import uuid
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_db_hash(db_path: Path, expected_sha256: str) -> None:
    actual = sha256_file(db_path)
    if actual != expected_sha256:
        raise ValueError(
            f"{db_path} hash mismatch: expected {expected_sha256}, got {actual}"
        )


def backup_database(db_path: Path) -> Path:
    backup_path = db_path.with_name(db_path.name + ".pre-phase3-backup")
    shutil.copy2(db_path, backup_path)
    return backup_path


RULE_TO_CLAIM_TYPE = {
    "required_dependency": "dependency_requirement",
    "incompatibility": "incompatibility",
    "relative_load_order": "load_order",
    "file_variant_advice": "compatibility",
    "named_patch_addon": "compatibility",
    "acquisition_content": "compatibility",
    "author_context": "compatibility",
}


def build_source_record_uuid(platform: str, platform_mod_id: str, source_comment_id: str) -> str:
    seed = f"bg3:phase3-evidence-source-record:comment:{platform}:{platform_mod_id}:{source_comment_id}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))


def build_claim_uuid(hit_id: int) -> str:
    seed = f"bg3:phase3-evidence-claim:triage-hit:{hit_id}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))


def build_comment_payload_json(comment_row: sqlite3.Row) -> str:
    payload = {
        "comment_uid": comment_row["comment_uid"],
        "platform": comment_row["platform"],
        "platform_mod_id": comment_row["platform_mod_id"],
        "source_comment_id": comment_row["source_comment_id"],
        "parent_source_comment_id": comment_row["parent_source_comment_id"],
        "thread_locator": comment_row["thread_locator"],
        "threading_model": comment_row["threading_model"],
        "thread_depth": comment_row["thread_depth"],
        "author_display_name": comment_row["author_display_name"],
        "author_user_id": comment_row["author_user_id"],
        "author_url": comment_row["author_url"],
        "author_identity_tier": comment_row["author_identity_tier"],
        "is_sticky": comment_row["is_sticky"],
        "created_epoch": comment_row["created_epoch"],
        "captured_timestamp": comment_row["captured_timestamp"],
        "body": comment_row["body"],
        "coverage_state": comment_row["coverage_state"],
    }
    return json.dumps(payload, sort_keys=True)


def build_content_sha256(payload_json: str) -> str:
    return hashlib.sha256(payload_json.encode("utf-8")).hexdigest()


def build_raw_locator(platform: str, source_line_number: int) -> str:
    return f"{platform}_comments_merged.jsonl#L{source_line_number}"
