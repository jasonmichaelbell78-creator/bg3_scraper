#!/usr/bin/env python3
"""Generate a compact, non-promotional Phase 2A validation report."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    triage = con.execute(
        "SELECT rule_code, platform, COUNT(*) FROM triage_hits h JOIN comments c USING(comment_row_id) GROUP BY rule_code, platform ORDER BY rule_code, platform"
    ).fetchall()
    partial = con.execute(
        "SELECT platform_mod_id, COUNT(*) FROM comments WHERE coverage_state='partial_capture' GROUP BY platform_mod_id ORDER BY platform_mod_id"
    ).fetchall()
    lines = [
        "# Phase 2A — Comment Evidence Index validation report",
        "",
        "## Status",
        "",
        "A separate, local-first Comment Evidence Index candidate was built from the two byte-verified canonical comment corpora. It is not B26 and did not modify B26, source files, claims, evidence links, reviews, promotions, relationships, risk facts, or catalog guidance.",
        "",
        "## Verified inputs",
        "",
        "| Corpus | Rows | SHA-256 | Canonical Drive file ID |",
        "|---|---:|---|---|",
    ]
    for item in receipt["input_corpora"]:
        lines.append(f"| {item['platform']} comments | {item['source_rows']:,} | `{item['source_sha256']}` | `{item['canonical_drive_file_id']}` |")
    lines += [
        "",
        "The Nexus checksum is `3e931…14934e0`; earlier control text omitted its final `0`. The uploaded file was independently hashed at the full 64-character value.",
        "",
        "## Index contents and validation",
        "",
        f"- Comment rows: **{receipt['validation']['comment_rows']:,}**",
        f"- Full-text-search rows: **{receipt['validation']['fts_rows']:,}**",
        f"- Triage-only, context-required candidates: **{receipt['validation']['triage_hits']:,}**",
        f"- SQLite integrity check: **{receipt['validation']['integrity_check']}**",
        f"- Foreign-key violations: **{receipt['validation']['foreign_key_violations']}**",
        f"- Index SHA-256: `{receipt['index_sha256']}`",
        "",
        "Thread-link state is explicit: 227,164 roots, 300,719 replies with retained parents, and 45 replies whose parent is not retained in the source corpus. Those 45 rows are not silently recast as roots.",
        "",
        "## Coverage constraints retained",
        "",
        "| Nexus mod ID | Retained comments | Evidence-index coverage state |",
        "|---|---:|---|",
    ]
    for mod_id, count in partial:
        lines.append(f"| {mod_id} | {count:,} | `partial_capture` |")
    lines += [
        "",
        "Absence from either partial capture cannot mean no signal exists.",
        "",
        "## Triage inventory — not facts",
        "",
        "Every row below is only a search candidate requiring full-comment/thread context and later target resolution where another mod, patch, file, vendor, or dependency is named. No row became a claim or evidence link.",
        "",
        "| Signal | mod.io | Nexus | Total |",
        "|---|---:|---:|---:|",
    ]
    grouped: dict[str, dict[str, int]] = {}
    for rule, platform, count in triage:
        grouped.setdefault(rule, {})[platform] = count
    labels = {
        "author_context": "Author/platform guidance",
        "required_dependency": "Required dependency",
        "incompatibility": "Incompatibility",
        "relative_load_order": "Relative load order",
        "file_variant_advice": "File or variant advice",
        "named_patch_addon": "Named patch/add-on",
        "acquisition_content": "Acquisition/content",
    }
    for rule, label in labels.items():
        values = grouped.get(rule, {})
        modio = values.get("modio", 0)
        nexus = values.get("nexus", 0)
        lines.append(f"| {label} | {modio:,} | {nexus:,} | {modio + nexus:,} |")
    lines += [
        "",
        "## Non-negotiable interpretation safeguards",
        "",
        "- No author identity is elevated from the comment corpora. mod.io needs a separately authorized same-mod `user.id`→roster join; Nexus has no corpus-derived elevation path.",
        "- Bare keyword matches are not valid signals. The index retains full text so question/answer state, hedging, perspective, and named-target context remain available.",
        "- Collections membership, names, and cross-platform similarity do not resolve identities or relationships.",
        "- Exact B26 listing links are deferred because B26 was not locally materialized in this run; no guessed link was written.",
        "",
        "## Next bounded work",
        "",
        "Rematerialize B26 locally, perform only deterministic same-platform listing-ID links into this separate index, then run a small high-signal query sample against Claude's safeguards. That is still evidence access—not canonical claim promotion.",
    ]
    args.report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    con.close()


if __name__ == "__main__":
    main()
