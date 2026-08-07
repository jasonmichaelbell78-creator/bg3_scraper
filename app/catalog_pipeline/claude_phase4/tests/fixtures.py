"""Shared SQLite fixture schema for B26 Phase 4 tests."""
import sqlite3


def create_fixture_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE evidence_corpora (
          corpus_uuid TEXT PRIMARY KEY,
          provider TEXT NOT NULL,
          object_scope TEXT NOT NULL,
          capture_label TEXT NOT NULL,
          captured_started_at TEXT,
          captured_finished_at TEXT,
          coverage_state TEXT NOT NULL,
          profile_label TEXT,
          record_count_raw INTEGER,
          record_count_unique INTEGER,
          limitation_notes TEXT NOT NULL,
          supersedes_corpus_uuid TEXT REFERENCES evidence_corpora(corpus_uuid)
        );

        CREATE TABLE evidence_source_records (
          source_record_uuid TEXT PRIMARY KEY,
          corpus_uuid TEXT NOT NULL REFERENCES evidence_corpora(corpus_uuid),
          provider_object_type TEXT NOT NULL,
          provider_native_id TEXT NOT NULL,
          source_listing_uuid TEXT,
          parent_provider_native_id TEXT,
          observed_at TEXT,
          displayed_author TEXT,
          version_text TEXT,
          content_sha256 TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          raw_locator TEXT NOT NULL,
          UNIQUE (corpus_uuid, provider_object_type, provider_native_id)
        );

        CREATE VIEW mod_comments AS
           SELECT
               esr.source_record_uuid AS comment_uuid,
               ec.provider AS platform,
               esr.provider_native_id AS source_comment_id,
               esr.source_listing_uuid AS listing_uuid,
               esr.parent_provider_native_id AS parent_source_comment_id,
               esr.displayed_author AS author,
               esr.observed_at AS observed_at,
               esr.payload_json AS payload_json
           FROM evidence_source_records esr
           JOIN evidence_corpora ec ON ec.corpus_uuid = esr.corpus_uuid
           WHERE esr.provider_object_type = 'comment';
        """
    )


def insert_corpus(conn, corpus_uuid, provider, capture_label, supersedes=None):
    conn.execute(
        """INSERT INTO evidence_corpora
           (corpus_uuid, provider, object_scope, capture_label, coverage_state,
            limitation_notes, supersedes_corpus_uuid)
           VALUES (?, ?, 'comments', ?, 'complete', 'test', ?)""",
        (corpus_uuid, provider, capture_label, supersedes),
    )


def insert_comment(conn, source_record_uuid, corpus_uuid, native_id):
    conn.execute(
        """INSERT INTO evidence_source_records
           (source_record_uuid, corpus_uuid, provider_object_type, provider_native_id,
            content_sha256, payload_json, raw_locator)
           VALUES (?, ?, 'comment', ?, 'x', '{}', 'x')""",
        (source_record_uuid, corpus_uuid, native_id),
    )


def add_collections_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE catalog_collections (
            collection_uuid TEXT PRIMARY KEY,
            platform TEXT NOT NULL CHECK(platform IN ('modio', 'nexus')),
            collection_native_id TEXT NOT NULL,
            collection_slug TEXT,
            collection_name TEXT NOT NULL,
            UNIQUE(platform, collection_native_id)
        );

        CREATE TABLE catalog_collection_comments (
            comment_uuid TEXT PRIMARY KEY,
            collection_uuid TEXT NOT NULL REFERENCES catalog_collections(collection_uuid),
            platform TEXT NOT NULL CHECK(platform IN ('modio', 'nexus')),
            source_comment_id TEXT NOT NULL,
            parent_source_comment_id TEXT,
            author_display_name TEXT,
            author_user_id TEXT,
            observed_at TEXT,
            body TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            source_corpus_sha256 TEXT NOT NULL,
            source_line_number INTEGER NOT NULL,
            UNIQUE(platform, source_comment_id)
        );
        CREATE INDEX idx_catalog_collection_comments_collection
            ON catalog_collection_comments(collection_uuid, platform);
        """
    )


def insert_collection(conn, collection_uuid, platform, native_id, name="Test"):
    conn.execute(
        "INSERT INTO catalog_collections (collection_uuid, platform, collection_native_id, collection_slug, collection_name) VALUES (?, ?, ?, ?, ?)",
        (collection_uuid, platform, native_id, native_id, name),
    )
