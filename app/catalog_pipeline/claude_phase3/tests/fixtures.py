"""Shared SQLite fixture schemas for B26 Phase 3 migration tests.

Mirrors the real column/constraint definitions of catalog/B26/
BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db and
catalog/B26/BG3_Comment_Evidence_Index_Phase2B_B26ExactLinks_candidate.db,
confirmed via `.schema` against the live databases on 2026-08-05 (see the
B26 Phase 3 design doc). Not the full real schema -- only the tables this
migration touches.
"""
import sqlite3


def create_fixture_candidate_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE evidence_corpora (
          corpus_uuid TEXT PRIMARY KEY,
          provider TEXT NOT NULL,
          object_scope TEXT NOT NULL,
          capture_label TEXT NOT NULL,
          captured_started_at TEXT,
          captured_finished_at TEXT,
          coverage_state TEXT NOT NULL CHECK(coverage_state IN
              ('not_available','not_collected','partial','complete','zero',
               'analyzed_no_match','signal_present')),
          profile_label TEXT,
          record_count_raw INTEGER,
          record_count_unique INTEGER,
          limitation_notes TEXT NOT NULL,
          supersedes_corpus_uuid TEXT REFERENCES evidence_corpora(corpus_uuid)
        );

        CREATE TABLE platform_listings (
            listing_id INTEGER PRIMARY KEY,
            mod_uid INTEGER,
            platform TEXT,
            platform_mod_id TEXT,
            listing_uuid TEXT
        );
        CREATE UNIQUE INDEX uq_platform_listings_listing_uuid ON platform_listings(listing_uuid);

        CREATE TABLE evidence_source_records (
          source_record_uuid TEXT PRIMARY KEY,
          corpus_uuid TEXT NOT NULL REFERENCES evidence_corpora(corpus_uuid),
          provider_object_type TEXT NOT NULL,
          provider_native_id TEXT NOT NULL,
          source_listing_uuid TEXT REFERENCES platform_listings(listing_uuid),
          parent_provider_native_id TEXT,
          observed_at TEXT,
          displayed_author TEXT,
          version_text TEXT,
          content_sha256 TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          raw_locator TEXT NOT NULL,
          UNIQUE (corpus_uuid, provider_object_type, provider_native_id)
        );

        CREATE TABLE evidence_claims (
          claim_uuid TEXT PRIMARY KEY,
          claim_text TEXT NOT NULL,
          claim_type TEXT NOT NULL,
          evidence_state TEXT NOT NULL CHECK(evidence_state IN
              ('retained_primary','retained_secondary','triage_only','unverifiable_session_summary')),
          claim_state TEXT NOT NULL CHECK(claim_state IN
              ('proposed','reviewed_supported','reviewed_insufficient','contradicted','promoted')),
          source_authority TEXT NOT NULL,
          corroboration_state TEXT NOT NULL,
          confidence TEXT NOT NULL,
          game_patch_scope TEXT NOT NULL,
          manager_scope TEXT NOT NULL,
          tool_and_version_scope TEXT NOT NULL,
          deployment_channel_scope TEXT NOT NULL,
          target_text TEXT NOT NULL,
          notes TEXT NOT NULL,
          created_at TEXT NOT NULL
        );

        CREATE TABLE evidence_claim_links (
          claim_uuid TEXT NOT NULL REFERENCES evidence_claims(claim_uuid),
          source_record_uuid TEXT REFERENCES evidence_source_records(source_record_uuid),
          artifact_uuid TEXT,
          link_role TEXT NOT NULL CHECK(link_role IN ('supports','contradicts','context')),
          evidence_excerpt TEXT NOT NULL,
          content_sha256 TEXT,
          CHECK(source_record_uuid IS NOT NULL OR artifact_uuid IS NOT NULL),
          PRIMARY KEY (claim_uuid, source_record_uuid, artifact_uuid, link_role)
        );

        CREATE TABLE mod_comments (
            comment_id INTEGER PRIMARY KEY,
            mod_uid INTEGER,
            author TEXT,
            date_added TEXT,
            karma INTEGER,
            reply_to_comment_id INTEGER,
            thread_position TEXT,
            options INTEGER,
            content TEXT
        );

        CREATE TABLE migration_history (
            migration_id INTEGER PRIMARY KEY,
            migration_name TEXT UNIQUE NOT NULL,
            schema_version TEXT NOT NULL,
            applied_at TEXT NOT NULL,
            actor_session TEXT NOT NULL,
            source_db_sha256 TEXT NOT NULL,
            row_count_before TEXT NOT NULL,
            row_count_after TEXT NOT NULL,
            notes TEXT
        );

        CREATE TABLE ingestion_stage_receipts (
          stage_receipt_uuid TEXT PRIMARY KEY,
          ingestion_run_id INTEGER,
          stage_label TEXT NOT NULL,
          source_artifact_sha256 TEXT NOT NULL,
          started_at TEXT NOT NULL,
          completed_at TEXT,
          records_seen INTEGER NOT NULL DEFAULT 0,
          records_written INTEGER NOT NULL DEFAULT 0,
          records_skipped INTEGER NOT NULL DEFAULT 0,
          validation_json TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('started','committed','rolled_back','failed')),
          notes TEXT
        );
        """
    )

    # Seed: the two pre-existing mod.io comment corpora and one
    # platform_listings row + 3 evidence_source_records rows, so Task 4's
    # "look up existing mod.io evidence, don't re-insert" path has real
    # data to find. source_comment_id values (9001-9003) must match the
    # mod.io comments seeded in create_fixture_phase2b_db below.
    conn.execute(
        "INSERT INTO evidence_corpora VALUES "
        "('f12290b9-eb19-5c03-86fc-3e2064e4104f','modio','comments',"
        "'modio_comments_base_under_page_limit_2026-07-21',NULL,NULL,"
        "'complete',NULL,2,2,'fixture seed',NULL)"
    )
    conn.execute(
        "INSERT INTO evidence_corpora VALUES "
        "('e88d8457-18e1-5f54-8cf1-d0b93a2e6c01','modio','comments',"
        "'modio_comments_deep_refresh_2026-07-21',NULL,NULL,"
        "'complete',NULL,1,1,'fixture seed',"
        "'f12290b9-eb19-5c03-86fc-3e2064e4104f')"
    )
    conn.execute(
        "INSERT INTO platform_listings (mod_uid, platform, platform_mod_id, listing_uuid) "
        "VALUES (1, 'modio', '4320786', 'fixture-listing-uuid-modio-4320786')"
    )
    # Nexus counterpart -- the phase2b fixture's nexus comments (mod 14077,
    # below) carry b26_listing_uuid='fixture-listing-uuid-nexus-14077', which
    # insert_nexus_evidence_source_records copies straight into
    # evidence_source_records.source_listing_uuid (an FK to this table). No
    # existing test asserts an exact platform_listings row count, so adding
    # this is safe for every already-passing test that uses this fixture;
    # it was missing purely because no test before Task 8's run_migration
    # ever ran with PRAGMA foreign_keys = ON, so the gap never surfaced.
    conn.execute(
        "INSERT INTO platform_listings (mod_uid, platform, platform_mod_id, listing_uuid) "
        "VALUES (2, 'nexus', '14077', 'fixture-listing-uuid-nexus-14077')"
    )
    for i, comment_id in enumerate(("9001", "9002"), start=1):
        conn.execute(
            "INSERT INTO evidence_source_records VALUES "
            "(?, 'f12290b9-eb19-5c03-86fc-3e2064e4104f', 'comment', ?, "
            "'fixture-listing-uuid-modio-4320786', NULL, '2023-01-01', 'author', "
            "NULL, 'deadbeef', '{}', 'modio_comments_merged.jsonl#L1')",
            (f"fixture-existing-modio-{i}", comment_id),
        )
    conn.execute(
        "INSERT INTO evidence_source_records VALUES "
        "('fixture-existing-modio-3', 'e88d8457-18e1-5f54-8cf1-d0b93a2e6c01', "
        "'comment', '9003', 'fixture-listing-uuid-modio-4320786', NULL, "
        "'2023-01-01', 'author', NULL, 'deadbeef', '{}', "
        "'modio_comments_merged.jsonl#L2')"
    )
    conn.commit()


def create_fixture_phase2b_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE comments (
            comment_row_id INTEGER PRIMARY KEY,
            comment_uid TEXT NOT NULL UNIQUE,
            platform TEXT NOT NULL CHECK(platform IN ('modio', 'nexus')),
            platform_mod_id TEXT NOT NULL,
            source_comment_id TEXT NOT NULL,
            parent_source_comment_id TEXT,
            thread_locator TEXT,
            threading_model TEXT NOT NULL,
            thread_depth INTEGER,
            author_display_name TEXT,
            author_user_id TEXT,
            author_url TEXT,
            author_identity_tier TEXT NOT NULL,
            is_sticky INTEGER,
            created_epoch INTEGER,
            captured_timestamp TEXT,
            body TEXT NOT NULL,
            source_line_number INTEGER NOT NULL,
            source_corpus_sha256 TEXT NOT NULL,
            coverage_state TEXT NOT NULL,
            b26_listing_link_state TEXT NOT NULL,
            b26_listing_uuid TEXT,
            UNIQUE(platform, platform_mod_id, source_comment_id)
        );

        CREATE TABLE triage_rule_catalog (
            rule_code TEXT PRIMARY KEY,
            priority_order INTEGER NOT NULL,
            display_name TEXT NOT NULL,
            operational_limit TEXT NOT NULL,
            author_tier_elevating INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE triage_hits (
            hit_id INTEGER PRIMARY KEY,
            comment_row_id INTEGER NOT NULL REFERENCES comments(comment_row_id),
            rule_code TEXT NOT NULL REFERENCES triage_rule_catalog(rule_code),
            pattern_note TEXT NOT NULL,
            disposition_state TEXT NOT NULL DEFAULT 'triage_only_context_required',
            full_comment_required INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            UNIQUE(comment_row_id, rule_code)
        );
        """
    )

    for rule_code, priority in (
        ("author_context", 1), ("required_dependency", 2), ("incompatibility", 3),
        ("relative_load_order", 4), ("file_variant_advice", 5),
        ("named_patch_addon", 6), ("acquisition_content", 7),
    ):
        conn.execute(
            "INSERT INTO triage_rule_catalog VALUES (?, ?, ?, 'fixture limit', 0)",
            (rule_code, priority, rule_code),
        )

    # 3 Nexus comments for mod 14077 (1 top-level, 2 replies -- exercises
    # threading), 1 gets a triage hit
    nexus_rows = [
        ("nx-1", "nexus", "14077", "555001", None, "t1", "nexus_parent_pointer",
         0, "Alice", "u1", "http://nexusmods.com/u1", "unverified_displayed_name_match",
         0, 1700000000, "2023-11-14T00:00:00Z",
         "This mod requires AnimationUnlocker to work correctly.",
         1, "fixturehash", "complete_capture", "linked_exact_platform_id",
         "fixture-listing-uuid-nexus-14077"),
        ("nx-2", "nexus", "14077", "555002", "555001", "t1.1", "nexus_parent_pointer",
         1, "Bob", "u2", "http://nexusmods.com/u2", "unverified_displayed_name_match",
         0, 1700000100, "2023-11-14T00:05:00Z", "Thanks, can confirm it works.",
         2, "fixturehash", "complete_capture", "linked_exact_platform_id",
         "fixture-listing-uuid-nexus-14077"),
        ("nx-3", "nexus", "14077", "555003", "555001", "t1.2", "nexus_parent_pointer",
         1, "Carol", "u3", "http://nexusmods.com/u3", "unverified_displayed_name_match",
         0, 1700000200, "2023-11-14T00:10:00Z", "Same here, great mod.",
         3, "fixturehash", "complete_capture", "linked_exact_platform_id",
         "fixture-listing-uuid-nexus-14077"),
    ]
    # 3 modio comments for mod 4320786, source_comment_id 9001-9003 --
    # MUST match create_fixture_candidate_db's seeded evidence rows above,
    # so Task 4's mod.io lookup path resolves for real
    modio_rows = [
        ("mo-1", "modio", "4320786", "9001", None, "0", "modio_dotted_reply",
         0, "Dave", "m1", "https://mod.io/u/m1", "unverified_displayed_name_match",
         0, 1700001000, "2023-11-15T00:00:00Z",
         "This is incompatible with the Reshade mod.",
         1, "fixturehash2", "complete_capture", "linked_exact_platform_id",
         "fixture-listing-uuid-modio-4320786"),
        ("mo-2", "modio", "4320786", "9002", "9001", "0.1", "modio_dotted_reply",
         1, "Eve", "m2", "https://mod.io/u/m2", "unverified_displayed_name_match",
         0, 1700001100, "2023-11-15T00:05:00Z", "Good to know, thanks!",
         2, "fixturehash2", "complete_capture", "linked_exact_platform_id",
         "fixture-listing-uuid-modio-4320786"),
        ("mo-3", "modio", "4320786", "9003", None, "1", "modio_dotted_reply",
         0, "Frank", "m3", "https://mod.io/u/m3", "unverified_displayed_name_match",
         0, 1700001200, "2023-11-15T00:10:00Z", "Load this one after the base mod.",
         3, "fixturehash2", "complete_capture", "linked_exact_platform_id",
         "fixture-listing-uuid-modio-4320786"),
    ]
    for row in nexus_rows + modio_rows:
        conn.execute(
            "INSERT INTO comments VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            row,
        )

    # Triage hits: one on the first Nexus comment (required_dependency),
    # one on the first modio comment (incompatibility), one on the third
    # modio comment (relative_load_order) -- covers 3 of the 7 rule types
    conn.execute(
        "INSERT INTO triage_hits VALUES (1, "
        "(SELECT comment_row_id FROM comments WHERE comment_uid='nx-1'), "
        "'required_dependency', 'requires AnimationUnlocker', "
        "'triage_only_context_required', 1, '2023-11-14T00:00:01Z')"
    )
    conn.execute(
        "INSERT INTO triage_hits VALUES (2, "
        "(SELECT comment_row_id FROM comments WHERE comment_uid='mo-1'), "
        "'incompatibility', 'incompatible with Reshade', "
        "'triage_only_context_required', 1, '2023-11-15T00:00:01Z')"
    )
    conn.execute(
        "INSERT INTO triage_hits VALUES (3, "
        "(SELECT comment_row_id FROM comments WHERE comment_uid='mo-3'), "
        "'relative_load_order', 'load this one after', "
        "'triage_only_context_required', 1, '2023-11-15T00:10:01Z')"
    )
    conn.commit()
