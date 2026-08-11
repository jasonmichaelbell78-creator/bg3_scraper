# app/catalog_pipeline/claude_phase6/load_volo_masterlist.py
"""
load_volo_masterlist.py v1.0
==============================
B26 Phase 3, workstream 2: ingests VOLO's public CC0-licensed masterlist
(load-order divider/group signal, explicit dependency pairs, and
Script-Extender/deployment-type signal) into catalog_volo_divider_signals,
catalog_volo_deployment_signals (both new), and load_order_hints (existing
table, source='volo'). See
docs/superpowers/specs/2026-08-10-volo-masterlist-ingestion-design.md for
the full design, including the corrections found there to the prior
research docs' VOLO coverage figures.
"""
import argparse
import difflib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.catalog_pipeline.claude_phase3.promote_comment_evidence import (
    sha256_file,
    verify_db_hash,
    backup_database,
)

FUZZY_MATCH_THRESHOLD = 0.85

CREATE_DIVIDER_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS catalog_volo_divider_signals (
    signal_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mod_uid INTEGER,
    volo_uuid TEXT NOT NULL,
    volo_name TEXT NOT NULL,
    volo_author TEXT,
    group_name TEXT,
    divider_position INTEGER,
    evidence_source TEXT,
    evidence_installs INTEGER,
    evidence_working_installs INTEGER,
    evidence_broken_installs INTEGER,
    match_status TEXT NOT NULL,
    match_score REAL,
    source_version TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    FOREIGN KEY (mod_uid) REFERENCES mods(mod_uid)
)
"""

CREATE_DEPLOYMENT_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS catalog_volo_deployment_signals (
    signal_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mod_uid INTEGER,
    volo_uuid TEXT NOT NULL,
    volo_name TEXT NOT NULL,
    volo_author TEXT,
    uses_script_extender INTEGER NOT NULL DEFAULT 0,
    feature_flags TEXT,
    match_status TEXT NOT NULL,
    match_score REAL,
    source_version TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    FOREIGN KEY (mod_uid) REFERENCES mods(mod_uid)
)
"""


def normalize_text(s: str | None) -> str:
    if not s:
        return ""
    s = re.sub(r"\([^)]*\)", " ", s)  # strip parenthetical aliases, e.g. "(prev. Djmr)"
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return s.strip()


def author_tokens(s: str | None) -> set[str]:
    return set(normalize_text(s).split())


def classify_match(
    volo_name: str, volo_author: str | None,
    candidate_name: str, candidate_author: str | None,
) -> tuple[str, float]:
    norm_volo_name = normalize_text(volo_name)
    norm_candidate_name = normalize_text(candidate_name)
    name_ratio = difflib.SequenceMatcher(None, norm_volo_name, norm_candidate_name).ratio()

    if norm_volo_name == norm_candidate_name:
        volo_tok = author_tokens(volo_author)
        candidate_tok = author_tokens(candidate_author)
        # Only auto-accept when BOTH sides carry a corroborating author --
        # VOLO's author field is missing on ~88% of its plugins (confirmed
        # during design), so an exact name match with no author on either
        # side is not enough to auto-trust; it's flagged for review instead.
        if volo_tok and candidate_tok and (volo_tok & candidate_tok):
            return "matched", 1.0

    if name_ratio >= FUZZY_MATCH_THRESHOLD:
        return "needs_review", name_ratio

    return "unmatched", name_ratio


def build_candidate_index(conn: sqlite3.Connection) -> list[tuple[int, str, str]]:
    rows = conn.execute(
        """SELECT m.mod_uid, m.canonical_name, pl.author
           FROM mods m JOIN platform_listings pl ON pl.mod_uid = m.mod_uid
           WHERE m.canonical_name IS NOT NULL"""
    ).fetchall()
    return [(mod_uid, name, author) for mod_uid, name, author in rows]


def find_best_match(
    volo_name: str, volo_author: str | None,
    candidates: list[tuple[int, str, str]],
) -> tuple[int | None, str, float]:
    norm_volo_name = normalize_text(volo_name)
    volo_first_token = norm_volo_name.split(" ")[0] if norm_volo_name else ""

    best_mod_uid = None
    best_status = "unmatched"
    best_score = 0.0

    for mod_uid, candidate_name, candidate_author in candidates:
        norm_candidate_name = normalize_text(candidate_name)
        candidate_first_token = norm_candidate_name.split(" ")[0] if norm_candidate_name else ""
        # Cheap prefilter: skip candidates sharing no leading normalized word
        # with the VOLO name -- keeps a full-corpus fuzzy scan tractable
        # (~20k candidates x ~7-8k VOLO plugins). A genuine match with a
        # different leading word is missed (falls to "unmatched" rather than
        # a wrong match) -- the safer failure direction per the design's
        # "don't guess" matching rule.
        if norm_volo_name != norm_candidate_name and volo_first_token != candidate_first_token:
            continue

        status, score = classify_match(volo_name, volo_author, candidate_name, candidate_author)
        if status == "matched":
            return mod_uid, "matched", score
        if status == "needs_review" and score > best_score:
            best_mod_uid, best_status, best_score = mod_uid, "needs_review", score

    return best_mod_uid, best_status, best_score


def build_divider_signal_row(
    plugin: dict, mod_uid: int | None, match_status: str, match_score: float,
    source_version: str, captured_at: str,
) -> tuple:
    evidence = plugin.get("evidence") or {}
    return (
        mod_uid,
        plugin["uuid"],
        plugin["name"],
        plugin.get("author"),
        plugin.get("group"),
        plugin.get("divider"),
        evidence.get("source"),
        evidence.get("installs"),
        evidence.get("workingInstalls"),
        evidence.get("brokenInstalls"),
        match_status,
        match_score,
        source_version,
        captured_at,
    )


def insert_divider_signals(
    conn: sqlite3.Connection, plugins: list[dict], candidates: list[tuple[int, str, str]],
    source_version: str, captured_at: str,
) -> dict:
    counts = {"divider_rows_inserted": 0, "divider_matched": 0, "divider_needs_review": 0, "divider_unmatched": 0}
    for plugin in plugins:
        if "divider" not in plugin:
            continue
        mod_uid, status, score = find_best_match(plugin["name"], plugin.get("author"), candidates)
        row = build_divider_signal_row(plugin, mod_uid, status, score, source_version, captured_at)
        conn.execute(
            """INSERT INTO catalog_volo_divider_signals
               (mod_uid, volo_uuid, volo_name, volo_author, group_name, divider_position,
                evidence_source, evidence_installs, evidence_working_installs,
                evidence_broken_installs, match_status, match_score, source_version, captured_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            row,
        )
        counts["divider_rows_inserted"] += 1
        counts[f"divider_{status}"] += 1
    return counts
