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


NEXUS_PLACEHOLDER_CORPUS_UUID = "cc2ea89e-3980-552e-aeb3-4c7e6056a3a1"


def insert_nexus_evidence_corpus(conn: sqlite3.Connection, *, record_count: int) -> str:
    corpus_uuid = str(uuid.uuid5(
        uuid.NAMESPACE_URL, "bg3:evidence-corpus:nexus:phase3_comment_promotion_2026-08"
    ))
    conn.execute(
        """INSERT INTO evidence_corpora
           (corpus_uuid, provider, object_scope, capture_label, coverage_state,
            record_count_raw, record_count_unique, limitation_notes, supersedes_corpus_uuid)
           VALUES (?, 'nexus', 'comments', 'nexus_comments_merged_phase3_promotion_2026-08',
                   'partial', ?, ?, ?, ?)""",
        (
            corpus_uuid, record_count, record_count,
            "Sourced from Phase 2B comment-evidence-index. Two mods have permanent "
            "partial capture: 279 (4,511 comments, page-123 Cloudflare wall) and "
            "22659 (74 comments) -- accepted gaps, see CLAUDE.md.",
            NEXUS_PLACEHOLDER_CORPUS_UUID,
        ),
    )
    return corpus_uuid


def insert_nexus_evidence_source_records(
    candidate_conn: sqlite3.Connection,
    phase2b_conn: sqlite3.Connection,
    corpus_uuid: str,
    *,
    platform_mod_ids: list[str] | None = None,
) -> dict[str, str]:
    phase2b_conn.row_factory = sqlite3.Row
    query = "SELECT * FROM comments WHERE platform = 'nexus'"
    params: tuple = ()
    if platform_mod_ids is not None:
        placeholders = ",".join("?" for _ in platform_mod_ids)
        query += f" AND platform_mod_id IN ({placeholders})"
        params = tuple(platform_mod_ids)

    uuid_by_comment_id: dict[str, str] = {}
    rows_to_insert = []
    for row in phase2b_conn.execute(query, params):
        source_record_uuid = build_source_record_uuid(
            "nexus", row["platform_mod_id"], row["source_comment_id"]
        )
        payload_json = build_comment_payload_json(row)
        content_sha256 = build_content_sha256(payload_json)
        raw_locator = build_raw_locator("nexus", row["source_line_number"])
        rows_to_insert.append((
            source_record_uuid, corpus_uuid, "comment", row["source_comment_id"],
            row["b26_listing_uuid"], row["parent_source_comment_id"],
            row["captured_timestamp"], row["author_display_name"], None,
            content_sha256, payload_json, raw_locator,
        ))
        uuid_by_comment_id[row["source_comment_id"]] = source_record_uuid

    candidate_conn.executemany(
        """INSERT INTO evidence_source_records
           (source_record_uuid, corpus_uuid, provider_object_type, provider_native_id,
            source_listing_uuid, parent_provider_native_id, observed_at, displayed_author,
            version_text, content_sha256, payload_json, raw_locator)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows_to_insert,
    )
    return uuid_by_comment_id


MODIO_CORPUS_UUIDS = (
    "f12290b9-eb19-5c03-86fc-3e2064e4104f",
    "e88d8457-18e1-5f54-8cf1-d0b93a2e6c01",
)


def lookup_existing_modio_evidence_uuids(candidate_conn: sqlite3.Connection) -> dict[str, str]:
    placeholders = ",".join("?" for _ in MODIO_CORPUS_UUIDS)
    rows = candidate_conn.execute(
        f"SELECT provider_native_id, source_record_uuid FROM evidence_source_records "
        f"WHERE corpus_uuid IN ({placeholders})",
        MODIO_CORPUS_UUIDS,
    ).fetchall()
    return {row[0]: row[1] for row in rows}


def promote_triage_hits(
    candidate_conn: sqlite3.Connection,
    phase2b_conn: sqlite3.Connection,
    nexus_uuid_by_comment_id: dict[str, str],
    modio_uuid_by_comment_id: dict[str, str],
    *,
    platform_mod_ids: list[str] | None = None,
) -> int:
    phase2b_conn.row_factory = sqlite3.Row
    query = (
        "SELECT t.hit_id, t.rule_code, t.pattern_note, t.created_at, "
        "c.platform, c.platform_mod_id, c.source_comment_id, "
        "c.author_identity_tier, c.body "
        "FROM triage_hits t JOIN comments c ON c.comment_row_id = t.comment_row_id"
    )
    params: tuple = ()
    if platform_mod_ids is not None:
        placeholders = ",".join("?" for _ in platform_mod_ids)
        query += f" WHERE c.platform_mod_id IN ({placeholders})"
        params = tuple(platform_mod_ids)

    claim_rows = []
    link_rows = []
    skipped = []
    for row in phase2b_conn.execute(query, params):
        if row["platform"] == "nexus":
            source_record_uuid = nexus_uuid_by_comment_id.get(row["source_comment_id"])
        else:
            source_record_uuid = modio_uuid_by_comment_id.get(row["source_comment_id"])
        if source_record_uuid is None:
            skipped.append((row["platform"], row["source_comment_id"], row["hit_id"]))
            continue

        claim_uuid = build_claim_uuid(row["hit_id"])
        claim_type = RULE_TO_CLAIM_TYPE[row["rule_code"]]
        claim_rows.append((
            claim_uuid, row["pattern_note"], claim_type, "triage_only", "proposed",
            row["author_identity_tier"], "single_unvalidated_triage_source", "low",
            "not stated", "not stated", "not stated", "not stated",
            "not resolved -- triage hit only, not yet reviewed",
            f"Phase 3 mechanical promotion of triage rule '{row['rule_code']}'; "
            f"unvalidated, see B26 Phase 3 migration design for precision/recall caveat.",
            row["created_at"],
        ))
        excerpt = (row["body"] or "")[:500]
        link_rows.append((claim_uuid, source_record_uuid, None, "context", excerpt, None))

    if skipped:
        raise RuntimeError(
            f"{len(skipped)} triage_hits had no matching evidence_source_records row "
            f"(should be 0): {skipped[:5]}{'...' if len(skipped) > 5 else ''}"
        )

    candidate_conn.executemany(
        """INSERT INTO evidence_claims
           (claim_uuid, claim_text, claim_type, evidence_state, claim_state,
            source_authority, corroboration_state, confidence, game_patch_scope,
            manager_scope, tool_and_version_scope, deployment_channel_scope,
            target_text, notes, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        claim_rows,
    )
    candidate_conn.executemany(
        """INSERT INTO evidence_claim_links
           (claim_uuid, source_record_uuid, artifact_uuid, link_role, evidence_excerpt, content_sha256)
           VALUES (?, ?, ?, ?, ?, ?)""",
        link_rows,
    )
    return len(claim_rows)
