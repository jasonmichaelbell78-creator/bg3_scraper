import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.catalog_pipeline.claude_phase3.promote_comment_evidence import (
    sha256_file,
    verify_db_hash,
    backup_database,
    build_source_record_uuid,
    build_claim_uuid,
    build_comment_payload_json,
    build_content_sha256,
    build_raw_locator,
    RULE_TO_CLAIM_TYPE,
)


class TestHashUtilities(unittest.TestCase):
    def test_sha256_file_matches_hashlib(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"hello world")
            path = Path(f.name)
        try:
            expected = hashlib.sha256(b"hello world").hexdigest()
            self.assertEqual(sha256_file(path), expected)
        finally:
            path.unlink()

    def test_verify_db_hash_passes_on_match(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"content")
            path = Path(f.name)
        try:
            expected = hashlib.sha256(b"content").hexdigest()
            verify_db_hash(path, expected)  # should not raise
        finally:
            path.unlink()

    def test_verify_db_hash_raises_on_mismatch(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"content")
            path = Path(f.name)
        try:
            with self.assertRaises(ValueError):
                verify_db_hash(path, "0" * 64)
        finally:
            path.unlink()


class TestBackup(unittest.TestCase):
    def test_backup_creates_identical_copy_with_suffix(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "candidate.db"
            db_path.write_bytes(b"fake db content")
            backup_path = backup_database(db_path)
            self.assertEqual(backup_path.name, "candidate.db.pre-phase3-backup")
            self.assertEqual(backup_path.read_bytes(), db_path.read_bytes())


class TestBuilders(unittest.TestCase):
    def test_source_record_uuid_is_deterministic(self):
        u1 = build_source_record_uuid("nexus", "899", "12345")
        u2 = build_source_record_uuid("nexus", "899", "12345")
        self.assertEqual(u1, u2)

    def test_source_record_uuid_differs_by_platform(self):
        u_nexus = build_source_record_uuid("nexus", "899", "12345")
        u_modio = build_source_record_uuid("modio", "899", "12345")
        self.assertNotEqual(u_nexus, u_modio)

    def test_claim_uuid_is_deterministic(self):
        self.assertEqual(build_claim_uuid(42), build_claim_uuid(42))
        self.assertNotEqual(build_claim_uuid(42), build_claim_uuid(43))

    def test_comment_payload_json_roundtrips_and_is_sorted(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.execute(
            """CREATE TABLE comments (
                comment_uid TEXT, platform TEXT, platform_mod_id TEXT,
                source_comment_id TEXT, parent_source_comment_id TEXT,
                thread_locator TEXT, threading_model TEXT, thread_depth INTEGER,
                author_display_name TEXT, author_user_id TEXT, author_url TEXT,
                author_identity_tier TEXT, is_sticky INTEGER, created_epoch INTEGER,
                captured_timestamp TEXT, body TEXT, coverage_state TEXT)"""
        )
        con.execute(
            "INSERT INTO comments VALUES ('u1','nexus','899','555',NULL,'t1',"
            "'nexus_parent_pointer',0,'Alice','a1','http://x','unverified',0,"
            "1700000000,'2023-11-14T00:00:00Z','test body','complete_capture')"
        )
        row = con.execute("SELECT * FROM comments").fetchone()
        payload_json = build_comment_payload_json(row)
        payload = json.loads(payload_json)
        self.assertEqual(payload["body"], "test body")
        self.assertEqual(payload["platform"], "nexus")
        # sorted keys => re-serializing with sort_keys gives back the same string
        self.assertEqual(payload_json, json.dumps(payload, sort_keys=True))

    def test_content_sha256_is_deterministic_and_sensitive_to_content(self):
        h1 = build_content_sha256('{"a": 1}')
        h2 = build_content_sha256('{"a": 1}')
        h3 = build_content_sha256('{"a": 2}')
        self.assertEqual(h1, h2)
        self.assertNotEqual(h1, h3)
        self.assertEqual(len(h1), 64)

    def test_raw_locator_format(self):
        self.assertEqual(
            build_raw_locator("nexus", 42), "nexus_comments_merged.jsonl#L42"
        )
        self.assertEqual(
            build_raw_locator("modio", 1), "modio_comments_merged.jsonl#L1"
        )

    def test_rule_to_claim_type_covers_all_seven_rules(self):
        expected_rules = {
            "required_dependency", "incompatibility", "relative_load_order",
            "file_variant_advice", "named_patch_addon", "acquisition_content",
            "author_context",
        }
        self.assertEqual(set(RULE_TO_CLAIM_TYPE.keys()), expected_rules)
        self.assertEqual(RULE_TO_CLAIM_TYPE["required_dependency"], "dependency_requirement")
        self.assertEqual(RULE_TO_CLAIM_TYPE["incompatibility"], "incompatibility")
        self.assertEqual(RULE_TO_CLAIM_TYPE["relative_load_order"], "load_order")
        for rule in ("file_variant_advice", "named_patch_addon", "acquisition_content", "author_context"):
            self.assertEqual(RULE_TO_CLAIM_TYPE[rule], "compatibility")
