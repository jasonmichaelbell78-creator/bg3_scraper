# app/catalog_pipeline/claude_phase5/tests/fixtures.py
"""Shared SQLite fixture schema for B26 Phase 5 (patch-8 tag capture) tests."""
import sqlite3


def create_fixture_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE mods (
            mod_uid INTEGER PRIMARY KEY
        );

        CREATE TABLE platform_listings (
            listing_id INTEGER PRIMARY KEY AUTOINCREMENT,
            mod_uid INTEGER REFERENCES mods(mod_uid),
            platform TEXT,
            platform_mod_id TEXT,
            url TEXT,
            author TEXT,
            category_id INTEGER,
            category_name TEXT,
            category_validated TEXT DEFAULT 'unchecked',
            version TEXT,
            last_updated TEXT,
            endorsements_or_downloads INTEGER,
            status TEXT,
            category_check_basis TEXT,
            listing_uuid TEXT
        );

        CREATE TABLE platform_tags (
            tag_id INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_id INTEGER REFERENCES platform_listings(listing_id),
            tag TEXT
        );

        CREATE TABLE migration_history (
            migration_id INTEGER PRIMARY KEY AUTOINCREMENT,
            migration_name TEXT UNIQUE NOT NULL,
            schema_version TEXT NOT NULL,
            applied_at TEXT NOT NULL,
            actor_session TEXT NOT NULL,
            source_db_sha256 TEXT NOT NULL,
            row_count_before TEXT NOT NULL,
            row_count_after TEXT NOT NULL,
            notes TEXT
        );
        """
    )


def insert_listing(conn: sqlite3.Connection, listing_id: int, platform: str, platform_mod_id: str) -> None:
    conn.execute(
        "INSERT INTO platform_listings (listing_id, platform, platform_mod_id) VALUES (?, ?, ?)",
        (listing_id, platform, platform_mod_id),
    )


def insert_existing_tag(conn: sqlite3.Connection, listing_id: int, tag: str) -> None:
    conn.execute(
        "INSERT INTO platform_tags (listing_id, tag) VALUES (?, ?)",
        (listing_id, tag),
    )