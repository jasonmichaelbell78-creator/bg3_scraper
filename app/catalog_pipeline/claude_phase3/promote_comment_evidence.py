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
import shutil
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
