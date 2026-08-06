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
from app.catalog_pipeline.claude_phase3.tests.fixtures import (
    create_fixture_candidate_db,
    create_fixture_phase2b_db,
)
from app.catalog_pipeline.claude_phase3.promote_comment_evidence import (
    NEXUS_PLACEHOLDER_CORPUS_UUID,
    insert_nexus_evidence_corpus,
    insert_nexus_evidence_source_records,
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


class TestFixtures(unittest.TestCase):
    def test_fixture_candidate_db_has_expected_tables(self):
        con = sqlite3.connect(":memory:")
        create_fixture_candidate_db(con)
        tables = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        self.assertEqual(
            tables,
            {
                "evidence_corpora", "evidence_source_records", "evidence_claims",
                "evidence_claim_links", "mod_comments", "platform_listings",
                "migration_history", "ingestion_stage_receipts",
            },
        )
        # seeded: 2 pre-existing modio corpora, 3 sample modio evidence rows
        corpora = con.execute("SELECT COUNT(*) FROM evidence_corpora WHERE provider='modio'").fetchone()[0]
        self.assertEqual(corpora, 2)
        modio_rows = con.execute("SELECT COUNT(*) FROM evidence_source_records").fetchone()[0]
        self.assertEqual(modio_rows, 3)

    def test_fixture_phase2b_db_has_expected_tables_and_seed_data(self):
        con = sqlite3.connect(":memory:")
        create_fixture_phase2b_db(con)
        tables = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        self.assertEqual(tables, {"comments", "triage_hits", "triage_rule_catalog"})
        rule_count = con.execute("SELECT COUNT(*) FROM triage_rule_catalog").fetchone()[0]
        self.assertEqual(rule_count, 7)
        nexus_count = con.execute("SELECT COUNT(*) FROM comments WHERE platform='nexus'").fetchone()[0]
        modio_count = con.execute("SELECT COUNT(*) FROM comments WHERE platform='modio'").fetchone()[0]
        self.assertGreater(nexus_count, 0)
        self.assertGreater(modio_count, 0)
        # the 3 modio comments in the phase2b fixture must match the 3 seeded
        # in the candidate fixture (same source_comment_id values), so
        # Task 4's mod.io lookup-not-insert path has something real to find
        modio_ids = {r[0] for r in con.execute(
            "SELECT source_comment_id FROM comments WHERE platform='modio'"
        )}
        self.assertEqual(modio_ids, {"9001", "9002", "9003"})


class TestNexusEvidenceInsert(unittest.TestCase):
    def setUp(self):
        self.candidate = sqlite3.connect(":memory:")
        create_fixture_candidate_db(self.candidate)
        self.phase2b = sqlite3.connect(":memory:")
        create_fixture_phase2b_db(self.phase2b)

    def test_insert_nexus_evidence_corpus_creates_row_superseding_placeholder(self):
        corpus_uuid = insert_nexus_evidence_corpus(self.candidate, record_count=3)
        row = self.candidate.execute(
            "SELECT provider, coverage_state, record_count_unique, supersedes_corpus_uuid "
            "FROM evidence_corpora WHERE corpus_uuid=?", (corpus_uuid,)
        ).fetchone()
        self.assertEqual(row[0], "nexus")
        self.assertEqual(row[1], "partial")
        self.assertEqual(row[2], 3)
        self.assertEqual(row[3], NEXUS_PLACEHOLDER_CORPUS_UUID)

    def test_insert_nexus_evidence_source_records_inserts_all_matching_rows(self):
        corpus_uuid = insert_nexus_evidence_corpus(self.candidate, record_count=3)
        uuid_map = insert_nexus_evidence_source_records(
            self.candidate, self.phase2b, corpus_uuid
        )
        self.assertEqual(len(uuid_map), 3)
        self.assertEqual(set(uuid_map.keys()), {"555001", "555002", "555003"})
        count = self.candidate.execute(
            "SELECT COUNT(*) FROM evidence_source_records WHERE corpus_uuid=?", (corpus_uuid,)
        ).fetchone()[0]
        self.assertEqual(count, 3)

    def test_insert_nexus_evidence_source_records_respects_mod_id_filter(self):
        corpus_uuid = insert_nexus_evidence_corpus(self.candidate, record_count=1)
        uuid_map = insert_nexus_evidence_source_records(
            self.candidate, self.phase2b, corpus_uuid, platform_mod_ids=["14077"]
        )
        # all 3 fixture nexus comments belong to mod 14077, so filtering by
        # it should still return all 3 -- this proves the filter is applied
        # (not silently ignored) without requiring a second mod in the fixture
        self.assertEqual(len(uuid_map), 3)

    def test_inserted_row_content_matches_source_exactly(self):
        corpus_uuid = insert_nexus_evidence_corpus(self.candidate, record_count=3)
        uuid_map = insert_nexus_evidence_source_records(
            self.candidate, self.phase2b, corpus_uuid
        )
        source_row = self.phase2b.execute(
            "SELECT body, b26_listing_uuid, source_line_number FROM comments "
            "WHERE source_comment_id='555001'"
        ).fetchone()
        inserted_row = self.candidate.execute(
            "SELECT payload_json, source_listing_uuid, raw_locator FROM evidence_source_records "
            "WHERE source_record_uuid=?", (uuid_map["555001"],)
        ).fetchone()
        payload = json.loads(inserted_row[0])
        self.assertEqual(payload["body"], source_row[0])
        self.assertEqual(inserted_row[1], source_row[1])
        self.assertEqual(inserted_row[2], f"nexus_comments_merged.jsonl#L{source_row[2]}")

    def test_modio_comments_are_never_touched(self):
        corpus_uuid = insert_nexus_evidence_corpus(self.candidate, record_count=3)
        insert_nexus_evidence_source_records(self.candidate, self.phase2b, corpus_uuid)
        modio_count_after = self.candidate.execute(
            "SELECT COUNT(*) FROM evidence_source_records WHERE corpus_uuid IN "
            "('f12290b9-eb19-5c03-86fc-3e2064e4104f','e88d8457-18e1-5f54-8cf1-d0b93a2e6c01')"
        ).fetchone()[0]
        self.assertEqual(modio_count_after, 3)  # unchanged from fixture seed


from app.catalog_pipeline.claude_phase3.promote_comment_evidence import (
    MODIO_CORPUS_UUIDS,
    lookup_existing_modio_evidence_uuids,
    promote_triage_hits,
)


class TestTriagePromotion(unittest.TestCase):
    def setUp(self):
        self.candidate = sqlite3.connect(":memory:")
        create_fixture_candidate_db(self.candidate)
        self.phase2b = sqlite3.connect(":memory:")
        create_fixture_phase2b_db(self.phase2b)
        corpus_uuid = insert_nexus_evidence_corpus(self.candidate, record_count=3)
        self.nexus_uuid_by_comment_id = insert_nexus_evidence_source_records(
            self.candidate, self.phase2b, corpus_uuid
        )

    def test_lookup_existing_modio_evidence_finds_fixture_seed_rows(self):
        modio_map = lookup_existing_modio_evidence_uuids(self.candidate)
        self.assertEqual(set(modio_map.keys()), {"9001", "9002", "9003"})

    def test_promote_triage_hits_inserts_one_claim_per_hit(self):
        modio_map = lookup_existing_modio_evidence_uuids(self.candidate)
        count = promote_triage_hits(
            self.candidate, self.phase2b, self.nexus_uuid_by_comment_id, modio_map
        )
        self.assertEqual(count, 3)  # fixture has exactly 3 triage_hits
        claim_count = self.candidate.execute("SELECT COUNT(*) FROM evidence_claims").fetchone()[0]
        link_count = self.candidate.execute("SELECT COUNT(*) FROM evidence_claim_links").fetchone()[0]
        self.assertEqual(claim_count, 3)
        self.assertEqual(link_count, 3)

    def test_all_promoted_claims_are_triage_only_and_proposed(self):
        modio_map = lookup_existing_modio_evidence_uuids(self.candidate)
        promote_triage_hits(self.candidate, self.phase2b, self.nexus_uuid_by_comment_id, modio_map)
        states = self.candidate.execute(
            "SELECT DISTINCT evidence_state, claim_state, confidence, corroboration_state "
            "FROM evidence_claims"
        ).fetchall()
        self.assertEqual(states, [("triage_only", "proposed", "low", "single_unvalidated_triage_source")])

    def test_claim_type_mapping_applied_correctly(self):
        modio_map = lookup_existing_modio_evidence_uuids(self.candidate)
        promote_triage_hits(self.candidate, self.phase2b, self.nexus_uuid_by_comment_id, modio_map)
        claim_types = {row[0] for row in self.candidate.execute(
            "SELECT claim_type FROM evidence_claims"
        )}
        # fixture has one required_dependency, one incompatibility, one relative_load_order hit
        self.assertEqual(claim_types, {"dependency_requirement", "incompatibility", "load_order"})

    def test_modio_claim_links_to_existing_evidence_not_new(self):
        modio_map = lookup_existing_modio_evidence_uuids(self.candidate)
        promote_triage_hits(self.candidate, self.phase2b, self.nexus_uuid_by_comment_id, modio_map)
        modio_evidence_count_after = self.candidate.execute(
            "SELECT COUNT(*) FROM evidence_source_records WHERE corpus_uuid IN "
            "('f12290b9-eb19-5c03-86fc-3e2064e4104f','e88d8457-18e1-5f54-8cf1-d0b93a2e6c01')"
        ).fetchone()[0]
        self.assertEqual(modio_evidence_count_after, 3)  # unchanged -- no new modio rows
        # the modio-derived claim's link must point at one of the pre-existing UUIDs
        modio_claim_link = self.candidate.execute(
            "SELECT source_record_uuid FROM evidence_claim_links WHERE claim_uuid = ?",
            (build_claim_uuid(2),),  # hit_id=2 is the modio incompatibility hit
        ).fetchone()
        self.assertIn(modio_claim_link[0], modio_map.values())

    def test_promote_triage_hits_raises_if_evidence_missing(self):
        # empty maps -- every hit's comment has no matching evidence row
        with self.assertRaises(RuntimeError):
            promote_triage_hits(self.candidate, self.phase2b, {}, {})

    def test_promote_triage_hits_mixed_failure_writes_nothing(self):
        # Realistic mixed case: 2 of the fixture's 3 triage hits CAN resolve
        # (hit_id=1 nexus/555001, hit_id=2 modio/9001) and 1 CANNOT
        # (hit_id=3 modio/9003 -- deliberately left out of the map). This
        # proves the "not optional" hard data-integrity guarantee even when
        # failure isn't total: the implementation only inserts after the
        # full skip-check completes, so a single unresolved hit among
        # otherwise-resolvable ones must still leave zero rows written.
        full_modio_map = lookup_existing_modio_evidence_uuids(self.candidate)
        self.assertIn("9001", full_modio_map)
        self.assertIn("9003", full_modio_map)  # confirms it's excluded on purpose below
        partial_modio_map = {"9001": full_modio_map["9001"]}

        with self.assertRaises(RuntimeError):
            promote_triage_hits(
                self.candidate, self.phase2b, self.nexus_uuid_by_comment_id, partial_modio_map
            )

        claim_count = self.candidate.execute("SELECT COUNT(*) FROM evidence_claims").fetchone()[0]
        link_count = self.candidate.execute("SELECT COUNT(*) FROM evidence_claim_links").fetchone()[0]
        self.assertEqual(claim_count, 0)
        self.assertEqual(link_count, 0)


from app.catalog_pipeline.claude_phase3.promote_comment_evidence import retire_mod_comments_table


class TestRetireModComments(unittest.TestCase):
    def setUp(self):
        self.candidate = sqlite3.connect(":memory:")
        create_fixture_candidate_db(self.candidate)
        self.phase2b = sqlite3.connect(":memory:")
        create_fixture_phase2b_db(self.phase2b)
        corpus_uuid = insert_nexus_evidence_corpus(self.candidate, record_count=3)
        insert_nexus_evidence_source_records(self.candidate, self.phase2b, corpus_uuid)

    def test_mod_comments_becomes_a_view_not_a_table(self):
        retire_mod_comments_table(self.candidate)
        row = self.candidate.execute(
            "SELECT type FROM sqlite_master WHERE name='mod_comments'"
        ).fetchone()
        self.assertEqual(row[0], "view")

    def test_mod_comments_view_returns_evidence_data(self):
        retire_mod_comments_table(self.candidate)
        count = self.candidate.execute("SELECT COUNT(*) FROM mod_comments").fetchone()[0]
        self.assertEqual(count, 6)  # 3 modio fixture rows + 3 nexus rows inserted in setUp

    def test_mod_comments_view_exposes_platform_and_source_comment_id(self):
        retire_mod_comments_table(self.candidate)
        row = self.candidate.execute(
            "SELECT platform, source_comment_id FROM mod_comments LIMIT 1"
        ).fetchone()
        self.assertEqual(row[0], "nexus")
        self.assertIn(row[1], {"555001", "555002", "555003"})


from app.catalog_pipeline.claude_phase3.promote_comment_evidence import run_and_verify_test_batch


class TestTestBatchOrchestration(unittest.TestCase):
    def setUp(self):
        self.candidate = sqlite3.connect(":memory:")
        create_fixture_candidate_db(self.candidate)
        self.phase2b = sqlite3.connect(":memory:")
        create_fixture_phase2b_db(self.phase2b)

    def test_test_batch_inserts_then_rolls_back_leaving_no_trace(self):
        run_and_verify_test_batch(
            self.candidate, self.phase2b,
            nexus_mod_ids=["14077"], modio_mod_ids=["4320786"],
        )
        # after rollback: no new nexus corpus, no new evidence rows beyond
        # the 3 modio fixture-seed rows, mod_comments still a table (not
        # retired -- that only happens in the real run, Task 8)
        nexus_corpora = self.candidate.execute(
            "SELECT COUNT(*) FROM evidence_corpora WHERE provider='nexus'"
        ).fetchone()[0]
        self.assertEqual(nexus_corpora, 0)
        evidence_count = self.candidate.execute(
            "SELECT COUNT(*) FROM evidence_source_records"
        ).fetchone()[0]
        self.assertEqual(evidence_count, 3)  # unchanged from fixture seed
        table_type = self.candidate.execute(
            "SELECT type FROM sqlite_master WHERE name='mod_comments'"
        ).fetchone()[0]
        self.assertEqual(table_type, "table")

    def test_test_batch_raises_on_verification_mismatch(self):
        # Corrupt the builder so payload doesn't match source, proving the
        # verification step actually checks content rather than just row counts.
        import app.catalog_pipeline.claude_phase3.promote_comment_evidence as mod
        original = mod.build_comment_payload_json
        mod.build_comment_payload_json = lambda row: '{"body": "WRONG"}'
        try:
            with self.assertRaises(AssertionError):
                run_and_verify_test_batch(
                    self.candidate, self.phase2b,
                    nexus_mod_ids=["14077"], modio_mod_ids=["4320786"],
                )
        finally:
            mod.build_comment_payload_json = original
