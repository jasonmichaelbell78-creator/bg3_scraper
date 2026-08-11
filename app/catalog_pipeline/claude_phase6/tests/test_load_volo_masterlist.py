# app/catalog_pipeline/claude_phase6/tests/test_load_volo_masterlist.py
import json
import sqlite3

import pytest

from app.catalog_pipeline.claude_phase6.load_volo_masterlist import (
    normalize_text,
    author_tokens,
    classify_match,
    build_candidate_index,
    find_best_match,
    build_divider_signal_row,
    insert_divider_signals,
)
from app.catalog_pipeline.claude_phase6.tests.fixtures import (
    create_fixture_db,
    insert_mod,
    insert_listing,
)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    create_fixture_db(c)
    yield c
    c.close()


def test_normalize_text_strips_parens_punctuation_and_case():
    assert normalize_text("bibsan (prev. Djmr / AlanaSP)") == "bibsan"
    assert normalize_text(None) == ""


def test_normalize_text_collapses_punctuation_to_single_spaces():
    assert normalize_text("Mod: Configuration, Menu!!") == "mod configuration menu"


def test_author_tokens_splits_on_whitespace():
    assert author_tokens("Astra & Sai") == {"astra", "sai"}
    assert author_tokens(None) == set()


def test_classify_match_exact_name_and_overlapping_author_is_matched():
    status, score = classify_match("ImpUI", "bibsan", "ImpUI", "bibsan (prev. Djmr)")
    assert status == "matched"
    assert score == 1.0


def test_classify_match_exact_name_missing_author_is_needs_review_not_matched():
    status, score = classify_match("ImpUI", None, "ImpUI", "bibsan")
    assert status == "needs_review"
    assert score == 1.0


def test_classify_match_exact_name_non_overlapping_author_is_needs_review():
    status, score = classify_match("Cool Mod", "Alice", "Cool Mod", "Bob")
    assert status == "needs_review"
    assert score == 1.0


def test_classify_match_fuzzy_name_above_threshold_is_needs_review():
    status, score = classify_match(
        "Mod Configuration Menu", "Volitio", "Mod Configuration Menus", "Volitio"
    )
    assert status == "needs_review"
    assert score >= 0.85


def test_classify_match_dissimilar_name_is_unmatched():
    status, score = classify_match(
        "Completely Different Thing", "X", "Totally Unrelated Mod", "Y"
    )
    assert status == "unmatched"
    assert score < 0.85


def test_build_candidate_index_returns_mod_uid_name_author(conn):
    insert_mod(conn, 1, "ImpUI")
    insert_listing(conn, 1, "nexus", "366", "bibsan")
    conn.commit()
    candidates = build_candidate_index(conn)
    assert candidates == [(1, "ImpUI", "bibsan")]


def test_find_best_match_returns_matched_on_exact_hit(conn):
    insert_mod(conn, 1, "ImpUI")
    insert_listing(conn, 1, "nexus", "366", "bibsan")
    conn.commit()
    candidates = build_candidate_index(conn)
    mod_uid, status, score = find_best_match("ImpUI", "bibsan (prev. Djmr)", candidates)
    assert (mod_uid, status) == (1, "matched")
    assert score == 1.0


def test_find_best_match_returns_unmatched_when_no_shared_first_token(conn):
    insert_mod(conn, 1, "Something Else Entirely")
    insert_listing(conn, 1, "nexus", "1", "Someone")
    conn.commit()
    candidates = build_candidate_index(conn)
    mod_uid, status, score = find_best_match("ImpUI", "bibsan", candidates)
    assert (mod_uid, status) == (None, "unmatched")


def test_build_divider_signal_row_extracts_all_fields():
    plugin = {
        "name": "ImpUI (ImprovedUI)",
        "uuid": "26922ba9-6018-5252-075d-7ff2ba6ed879",
        "group": "User Interface",
        "author": "bibsan",
        "divider": 1,
        "evidence": {"source": "curated", "installs": 53, "workingInstalls": 45, "brokenInstalls": 5},
    }
    row = build_divider_signal_row(plugin, 1, "matched", 1.0, "2.0.0", "2026-08-10T23:56:45.072Z")
    assert row == (
        1, "26922ba9-6018-5252-075d-7ff2ba6ed879", "ImpUI (ImprovedUI)", "bibsan",
        "User Interface", 1, "curated", 53, 45, 5, "matched", 1.0,
        "2.0.0", "2026-08-10T23:56:45.072Z",
    )


def test_build_divider_signal_row_handles_missing_evidence_and_author():
    plugin = {"name": "X", "uuid": "u-1", "group": "Misc", "divider": 5}
    row = build_divider_signal_row(plugin, None, "unmatched", 0.2, "2.0.0", "t")
    assert row == (None, "u-1", "X", None, "Misc", 5, None, None, None, None, "unmatched", 0.2, "2.0.0", "t")


def test_insert_divider_signals_only_includes_plugins_with_divider(conn):
    plugins = [
        {"name": "HasDivider", "uuid": "u-1", "group": "Weapons", "divider": 3, "evidence": {}},
        {"name": "NoDivider", "uuid": "u-2", "group": "unsorted"},  # no 'divider' key
    ]
    counts = insert_divider_signals(conn, plugins, [], "2.0.0", "t")
    conn.commit()
    assert counts["divider_rows_inserted"] == 1
    rows = conn.execute("SELECT volo_name FROM catalog_volo_divider_signals").fetchall()
    assert rows == [("HasDivider",)]


def test_insert_divider_signals_classifies_match_status(conn):
    insert_mod(conn, 1, "HasDivider")
    insert_listing(conn, 1, "nexus", "1", "Author")
    conn.commit()
    candidates = build_candidate_index(conn)
    plugins = [
        {
            "name": "HasDivider", "uuid": "u-1", "group": "Weapons", "author": "Author",
            "divider": 3, "evidence": {},
        },
    ]
    counts = insert_divider_signals(conn, plugins, candidates, "2.0.0", "t")
    conn.commit()
    assert counts == {
        "divider_rows_inserted": 1, "divider_matched": 1, "divider_needs_review": 0, "divider_unmatched": 0,
    }
    row = conn.execute("SELECT mod_uid, match_status FROM catalog_volo_divider_signals").fetchone()
    assert row == (1, "matched")
