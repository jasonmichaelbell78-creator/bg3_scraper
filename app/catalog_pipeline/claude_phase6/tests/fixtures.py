# app/catalog_pipeline/claude_phase6/tests/fixtures.py
"""Shared SQLite fixture schema for B26 Phase 6 (VOLO masterlist ingestion) tests."""
import sqlite3

from app.catalog_pipeline.claude_phase6.load_volo_masterlist import (
    CREATE_DIVIDER_TABLE_SQL,
    CREATE_DEPLOYMENT_TABLE_SQL,
)


def create_fixture_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE mods (
            mod_uid INTEGER PRIMARY KEY,
            canonical_name TEXT
        );

        CREATE TABLE platform_listings (
            listing_id INTEGER PRIMARY KEY AUTOINCREMENT,
            mod_uid INTEGER REFERENCES mods(mod_uid),
            platform TEXT,
            platform_mod_id TEXT,
            author TEXT
        );

        CREATE TABLE load_order_hints (
            hint_id INTEGER PRIMARY KEY AUTOINCREMENT,
            mod_uid INTEGER,
            relation_type TEXT,
            relative_to_mod_uid INTEGER,
            relative_to_text TEXT,
            source TEXT,
            source_platform TEXT,
            confidence TEXT,
            supporting_text TEXT
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
    conn.execute(CREATE_DIVIDER_TABLE_SQL)
    conn.execute(CREATE_DEPLOYMENT_TABLE_SQL)


def insert_mod(conn: sqlite3.Connection, mod_uid: int, canonical_name: str) -> None:
    conn.execute("INSERT INTO mods (mod_uid, canonical_name) VALUES (?, ?)", (mod_uid, canonical_name))


def insert_listing(conn: sqlite3.Connection, mod_uid: int, platform: str, platform_mod_id: str, author: str | None) -> None:
    conn.execute(
        "INSERT INTO platform_listings (mod_uid, platform, platform_mod_id, author) VALUES (?, ?, ?, ?)",
        (mod_uid, platform, platform_mod_id, author),
    )
