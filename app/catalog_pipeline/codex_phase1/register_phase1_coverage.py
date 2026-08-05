#!/usr/bin/env python3
"""One-time, idempotence-safe Phase 1 coverage migration from B25."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sqlite3
import sys
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path


BASE_DB_SHA256 = "27783c9611049c9b34104b806555d15de1b56282cdaffe521bc5fa41abc144e4"
MIGRATION_NAME = "phase1_coverage_browse_labels_and_collections_2026_07_27"
SCHEMA_VERSION = "1.2-phase1-coverage"
ACTOR_SESSION = "codex-phase1-coverage-2026-07-27"
GROUPS = (
    "Frameworks & Utilities",
    "Interface & Accessibility",
    "Character Creation & Appearance",
    "Classes, Subclasses & Progression",
    "Spells, Abilities & Feats",
    "Races, Backgrounds & Deities",
    "Companions, NPCs & Followers",
    "Gameplay, Rules & Quality of Life",
    "Difficulty, Encounters & AI",
    "Equipment, Items, Loot & Vendors",
    "World, Quests & Exploration",
    "Visuals, Audio & Animation",
    "Patches, Compatibility & Translation",
    "Other / Source Detail Limited",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_jsonl(path: Path) -> list[dict[str, object]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def load_taxonomy(path: Path):
    spec = importlib.util.spec_from_file_location("taxonomy_rules", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load taxonomy rule file: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def counted_rows(con: sqlite3.Connection) -> dict[str, int]:
    tables = (
        "platform_listings",
        "catalog_browse_labels",
        "catalog_collections",
        "catalog_collection_memberships",
    )
    present = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return {table: con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] if table in present else 0 for table in tables}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--rules", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()

    db_sha_before = sha256(args.db)
    if db_sha_before != BASE_DB_SHA256:
        raise SystemExit(
            f"Refusing unexpected input DB SHA-256: {db_sha_before}; expected {BASE_DB_SHA256}"
        )

    input_files = {
        "modio_meta": args.source_root / "modio_collections_meta.jsonl",
        "nexus_meta": args.source_root / "nexus_collections_meta.jsonl",
        "modio_members": args.source_root / "modio_collections_mods.jsonl",
        "nexus_members": args.source_root / "nexus_collections_mods.jsonl",
    }
    missing = [str(path) for path in input_files.values() if not path.is_file()]
    if missing:
        raise SystemExit("Missing canonical source inputs: " + ", ".join(missing))
    input_shas = {name: sha256(path) for name, path in input_files.items()}
    expected_shas = {
        "modio_meta": "bdf729efcdd68ca354f6a6e5c3b810606e8b10e4b0904176a33803ab21c80b16",
        "nexus_meta": "5fe5179b3cd383c60d57094f8dae3a712f62059157410b6211c955e9c0844d99",
        "modio_members": "d7849fb67bb05f206f05f17206dcbfa92a2182b50863cec318ba79eb8bf10624",
        "nexus_members": "57f7d3aa74fc93f17301e80e0a1ad5633e5cd14ebb1592a41497fd653bc1dc66",
    }
    if input_shas != expected_shas:
        raise SystemExit(f"Refusing unexpected source checksums: {input_shas}")

    taxonomy = load_taxonomy(args.rules)
    rule_sha = sha256(args.rules)
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    con = sqlite3.connect(args.db)
    con.execute("PRAGMA foreign_keys = ON")
    try:
        existing = con.execute(
            "SELECT 1 FROM migration_history WHERE migration_name = ?", (MIGRATION_NAME,)
        ).fetchone()
        if existing:
            raise SystemExit(f"Migration already applied: {MIGRATION_NAME}")
        before = counted_rows(con)
        con.execute("BEGIN IMMEDIATE")
        con.executescript(
            """
            CREATE TABLE catalog_browse_labels (
                listing_uuid TEXT PRIMARY KEY REFERENCES platform_listings(listing_uuid),
                browse_group TEXT NOT NULL,
                label_basis TEXT NOT NULL CHECK(label_basis IN ('Native platform', 'Listing-derived', 'Curated / checked', 'Broad fallback')),
                basis_detail TEXT NOT NULL,
                taxonomy_rule_sha256 TEXT NOT NULL,
                taxonomy_version TEXT NOT NULL,
                assigned_at TEXT NOT NULL,
                CHECK(browse_group IN (
                    'Frameworks & Utilities', 'Interface & Accessibility',
                    'Character Creation & Appearance', 'Classes, Subclasses & Progression',
                    'Spells, Abilities & Feats', 'Races, Backgrounds & Deities',
                    'Companions, NPCs & Followers', 'Gameplay, Rules & Quality of Life',
                    'Difficulty, Encounters & AI', 'Equipment, Items, Loot & Vendors',
                    'World, Quests & Exploration', 'Visuals, Audio & Animation',
                    'Patches, Compatibility & Translation', 'Other / Source Detail Limited'
                ))
            );
            CREATE INDEX idx_catalog_browse_labels_group
                ON catalog_browse_labels(browse_group, label_basis);

            CREATE TABLE catalog_collections (
                collection_uuid TEXT PRIMARY KEY,
                platform TEXT NOT NULL CHECK(platform IN ('modio', 'nexus')),
                collection_native_id TEXT NOT NULL,
                collection_slug TEXT,
                collection_name TEXT NOT NULL,
                collection_summary TEXT,
                collection_category TEXT,
                collection_author TEXT,
                collection_mod_count INTEGER,
                source_corpus_sha256 TEXT NOT NULL,
                source_line_number INTEGER NOT NULL,
                captured_at TEXT,
                UNIQUE(platform, collection_native_id)
            );
            CREATE INDEX idx_catalog_collections_platform_name
                ON catalog_collections(platform, collection_name);

            CREATE TABLE catalog_collection_memberships (
                membership_uuid TEXT PRIMARY KEY,
                collection_uuid TEXT NOT NULL REFERENCES catalog_collections(collection_uuid),
                platform TEXT NOT NULL CHECK(platform IN ('modio', 'nexus')),
                member_platform_mod_id TEXT NOT NULL,
                member_name TEXT NOT NULL,
                member_version TEXT,
                member_variant_uid TEXT,
                member_optional INTEGER,
                source_corpus_sha256 TEXT NOT NULL,
                source_line_number INTEGER NOT NULL,
                captured_at TEXT,
                mapping_state TEXT NOT NULL CHECK(mapping_state IN ('resolved', 'unmapped')),
                mapped_listing_uuid TEXT REFERENCES platform_listings(listing_uuid),
                mapping_method TEXT NOT NULL CHECK(mapping_method IN ('exact_platform_id', 'none')),
                mapping_note TEXT NOT NULL,
                UNIQUE(platform, source_corpus_sha256, source_line_number),
                CHECK((mapping_state = 'resolved' AND mapped_listing_uuid IS NOT NULL AND mapping_method = 'exact_platform_id')
                   OR (mapping_state = 'unmapped' AND mapped_listing_uuid IS NULL AND mapping_method = 'none'))
            );
            CREATE INDEX idx_catalog_collection_memberships_listing
                ON catalog_collection_memberships(mapped_listing_uuid, mapping_state);
            CREATE INDEX idx_catalog_collection_memberships_collection
                ON catalog_collection_memberships(collection_uuid, mapping_state);
            """
        )

        tag_rows: dict[int, list[str]] = defaultdict(list)
        for listing_id, tag in con.execute("SELECT listing_id, lower(trim(tag)) FROM platform_tags WHERE trim(tag) <> ''"):
            tag_rows[listing_id].append(tag)
        term_rows: dict[str, list[str]] = defaultdict(list)
        for mod_uuid, term in con.execute("SELECT mod_uuid, term FROM mod_classifications WHERE retired_at IS NULL"):
            term_rows[mod_uuid].append(term)
        labels: list[tuple[object, ...]] = []
        for row in con.execute(
            """
            SELECT p.listing_id, p.platform, p.platform_mod_id, p.url, p.author,
                   p.category_name, p.listing_uuid, m.canonical_name, m.description, m.mod_uuid
            FROM platform_listings p JOIN mods m ON m.mod_uid = p.mod_uid
            ORDER BY p.platform, p.listing_id
            """
        ):
            listing_id, platform, platform_mod_id, url, author, category, listing_uuid, name, description, mod_uuid = row
            record = {
                "listing_id": listing_id, "platform": platform, "platform_mod_id": platform_mod_id,
                "url": url, "author": author, "category": category or "", "name": name or "",
                "description": description or "", "tags": sorted(set(tag_rows[listing_id])),
                "terms": sorted(set(term_rows[mod_uuid])),
            }
            browse_group, label_basis, basis_detail = taxonomy.choose_group(record)
            labels.append((listing_uuid, browse_group, label_basis, basis_detail, rule_sha, "phase0-reconciled-2026-07-27", now))
        if len(labels) != 19967:
            raise RuntimeError(f"Unexpected listing count for labels: {len(labels)}")
        con.executemany(
            "INSERT INTO catalog_browse_labels VALUES (?, ?, ?, ?, ?, ?, ?)", labels
        )

        collection_index: dict[tuple[str, str], str] = {}
        collection_rows: list[tuple[object, ...]] = []
        for platform, key, path in (
            ("modio", "id", input_files["modio_meta"]),
            ("nexus", "slug", input_files["nexus_meta"]),
        ):
            for line_no, row in enumerate(load_jsonl(path), start=1):
                native_id = str(row[key])
                collection_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"bg3:collection:{platform}:{native_id}"))
                collection_index[(platform, native_id)] = collection_uuid
                if platform == "modio":
                    author = ((row.get("submitted_by") or {}).get("username") or "")
                    collection_rows.append((collection_uuid, platform, native_id, row.get("name_id"), row.get("name") or native_id,
                        row.get("summary") or row.get("description_plaintext") or "", row.get("category"), author,
                        ((row.get("stats") or {}).get("mods_total")), input_shas["modio_meta"], line_no, row.get("_fetched_at")))
                else:
                    collection_rows.append((collection_uuid, platform, native_id, native_id, row.get("name") or native_id,
                        row.get("summary") or "", row.get("category"), None, row.get("mod_count"),
                        input_shas["nexus_meta"], line_no, row.get("_fetched_at")))
        con.executemany(
            "INSERT INTO catalog_collections VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", collection_rows
        )

        listing_index = {
            (platform, str(platform_mod_id)): listing_uuid
            for platform, platform_mod_id, listing_uuid in con.execute(
                "SELECT platform, platform_mod_id, listing_uuid FROM platform_listings"
            )
        }
        membership_rows: list[tuple[object, ...]] = []
        for platform, source_key, collection_key, name_key, path in (
            ("modio", "modio_members", "collection_id", "name", input_files["modio_members"]),
            ("nexus", "nexus_members", "collection_slug", "mod_name", input_files["nexus_members"]),
        ):
            for line_no, row in enumerate(load_jsonl(path), start=1):
                native_collection_id = str(row[collection_key])
                collection_uuid = collection_index[(platform, native_collection_id)]
                member_id = str(row["mod_id"])
                target = listing_index.get((platform, member_id))
                state = "resolved" if target else "unmapped"
                method = "exact_platform_id" if target else "none"
                note = "Exact same-platform provider ID" if target else "No B25 listing with this same-platform provider ID"
                membership_uuid = str(uuid.uuid5(
                    uuid.NAMESPACE_URL, f"bg3:collection-membership:{platform}:{input_shas[source_key]}:{line_no}"
                ))
                membership_rows.append((membership_uuid, collection_uuid, platform, member_id, row.get(name_key) or member_id,
                    row.get("version"), row.get("uid"), None if "optional" not in row else int(bool(row["optional"])),
                    input_shas[source_key], line_no, row.get("_fetched_at"), state, target, method, note))
        con.executemany(
            "INSERT INTO catalog_collection_memberships VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", membership_rows
        )

        after = counted_rows(con)
        expected_after = {
            "platform_listings": 19967,
            "catalog_browse_labels": 19967,
            "catalog_collections": 930,
            "catalog_collection_memberships": 49907,
        }
        if after != expected_after:
            raise RuntimeError(f"Unexpected post-migration counts: {after}")
        state_counts = dict(con.execute(
            "SELECT mapping_state, COUNT(*) FROM catalog_collection_memberships GROUP BY mapping_state"
        ))
        if state_counts != {"resolved": 48898, "unmapped": 1009}:
            raise RuntimeError(f"Unexpected mapping states: {state_counts}")
        coverage_by_platform = {
            platform: dict(con.execute(
                "SELECT mapping_state, COUNT(*) FROM catalog_collection_memberships WHERE platform = ? GROUP BY mapping_state", (platform,)
            ))
            for platform in ("modio", "nexus")
        }
        label_counts = {
            platform: dict(con.execute(
                """SELECT cbl.browse_group, COUNT(*)
                   FROM catalog_browse_labels cbl JOIN platform_listings p ON p.listing_uuid = cbl.listing_uuid
                   WHERE p.platform = ? GROUP BY cbl.browse_group""", (platform,)
            ))
            for platform in ("modio", "nexus")
        }
        con.execute(
            """INSERT INTO migration_history
               (migration_name, schema_version, applied_at, actor_session, source_db_sha256, row_count_before, row_count_after, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (MIGRATION_NAME, SCHEMA_VERSION, now, ACTOR_SESSION, BASE_DB_SHA256,
             json.dumps(before, sort_keys=True), json.dumps(after, sort_keys=True),
             "Phase 1 coverage: audited browse-label projection plus exact same-platform Collections links; unmatched IDs retained."),
        )
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

    db_sha_after = sha256(args.db)
    readonly = sqlite3.connect(f"file:{args.db}?mode=ro&immutable=1", uri=True)
    try:
        integrity = readonly.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_key_violations = len(readonly.execute("PRAGMA foreign_key_check").fetchall())
        final_counts = counted_rows(readonly)
    finally:
        readonly.close()
    receipt = {
        "migration_name": MIGRATION_NAME,
        "schema_version": SCHEMA_VERSION,
        "actor_session": ACTOR_SESSION,
        "input_db_sha256": BASE_DB_SHA256,
        "output_db_sha256": db_sha_after,
        "taxonomy_rule_sha256": rule_sha,
        "source_input_sha256": input_shas,
        "validation": {"integrity_check": integrity, "foreign_key_violations": foreign_key_violations},
        "row_counts": final_counts,
        "mapping_states": state_counts,
        "mapping_states_by_platform": coverage_by_platform,
        "browse_group_counts_by_platform": label_counts,
        "unmapped_policy": "Retained as unmapped; no fuzzy, title, name, alias, or cross-platform matching applied.",
    }
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
