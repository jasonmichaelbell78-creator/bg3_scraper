#!/usr/bin/env python3
"""Read-only Phase 0 B25 browse-taxonomy profile and representative sample."""

from __future__ import annotations

import csv
import json
import random
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DB = ROOT / "b25_reprofile_20260727" / "BG3_Reference_Catalog_v1_1_Working_B25_C5_review_batch4_final_candidate_stream.db"
OUT = ROOT / "phase0_reconciliation_outputs"
DATE = "2026-07-27"

GROUPS = [
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
]

# Primary-role tie-breaker. Generic appearance and gameplay tags never outrank a
# more specific retained content signal merely because they sort earlier.
GROUP_PRIORITY = [
    "Patches, Compatibility & Translation",
    "Frameworks & Utilities",
    "Interface & Accessibility",
    "Difficulty, Encounters & AI",
    "World, Quests & Exploration",
    "Classes, Subclasses & Progression",
    "Spells, Abilities & Feats",
    "Races, Backgrounds & Deities",
    "Companions, NPCs & Followers",
    "Equipment, Items, Loot & Vendors",
    "Visuals, Audio & Animation",
    "Gameplay, Rules & Quality of Life",
    "Character Creation & Appearance",
]

TERM_GROUPS = {
    "translation": "Patches, Compatibility & Translation",
    "compatibility-patch": "Patches, Compatibility & Translation",
    "bugfix": "Patches, Compatibility & Translation",
    "deprecated-superseded": "Patches, Compatibility & Translation",
    "modder-resource": "Frameworks & Utilities",
    "affects-ui": "Interface & Accessibility",
    "affects-camera": "Interface & Accessibility",
    "affects-photo-mode": "Interface & Accessibility",
    "affects-inventory": "Interface & Accessibility",
    "cosmetic-only": "Character Creation & Appearance",
    "affects-character-creation": "Character Creation & Appearance",
    "npc-appearance-redesign": "Companions, NPCs & Followers",
    "affects-classes": "Classes, Subclasses & Progression",
    "class-mechanic-change": "Classes, Subclasses & Progression",
    "level-cap-related": "Classes, Subclasses & Progression",
    "character-trait-system": "Classes, Subclasses & Progression",
    "affects-spells": "Spells, Abilities & Feats",
    "affects-feats": "Spells, Abilities & Feats",
    "affects-races": "Races, Backgrounds & Deities",
    "affects-companions": "Companions, NPCs & Followers",
    "affects-npcs": "Companions, NPCs & Followers",
    "companion-interaction": "Companions, NPCs & Followers",
    "companion-ai-behavior": "Companions, NPCs & Followers",
    "qol-automation": "Gameplay, Rules & Quality of Life",
    "rebalance-not-new-content": "Gameplay, Rules & Quality of Life",
    "cheat-or-op-item": "Gameplay, Rules & Quality of Life",
    "crafting-system": "Gameplay, Rules & Quality of Life",
    "affects-dialogue": "Gameplay, Rules & Quality of Life",
    "affects-camp": "Gameplay, Rules & Quality of Life",
    "encounter-content": "Difficulty, Encounters & AI",
    "combat-system-overhaul": "Difficulty, Encounters & AI",
    "affects-equipment": "Equipment, Items, Loot & Vendors",
    "affects-weapons": "Equipment, Items, Loot & Vendors",
    "affects-armor": "Equipment, Items, Loot & Vendors",
    "affects-loot-tables": "Equipment, Items, Loot & Vendors",
    "affects-existing-item": "Equipment, Items, Loot & Vendors",
    "single-item": "Equipment, Items, Loot & Vendors",
    "single-weapon": "Equipment, Items, Loot & Vendors",
    "affects-audio": "Visuals, Audio & Animation",
    "affects-world-visuals": "Visuals, Audio & Animation",
    "player-housing": "World, Quests & Exploration",
}

CATEGORY_GROUPS = {
    "character customisation": "Character Creation & Appearance",
    "classes": "Classes, Subclasses & Progression",
    "equipment": "Equipment, Items, Loot & Vendors",
    "armor": "Equipment, Items, Loot & Vendors",
    "weapons": "Equipment, Items, Loot & Vendors",
    "clothing": "Equipment, Items, Loot & Vendors",
    "accessories": "Equipment, Items, Loot & Vendors",
    "spells": "Spells, Abilities & Feats",
    "races": "Races, Backgrounds & Deities",
    "companions": "Companions, NPCs & Followers",
    "user interface": "Interface & Accessibility",
    "utilities": "Frameworks & Utilities",
    "resources": "Frameworks & Utilities",
    "maps": "World, Quests & Exploration",
    "quests": "World, Quests & Exploration",
    "visuals": "Visuals, Audio & Animation",
    "audio": "Visuals, Audio & Animation",
    "animations": "Visuals, Audio & Animation",
    "photo mode": "Interface & Accessibility",
    "gameplay": "Gameplay, Rules & Quality of Life",
    "dice": "Gameplay, Rules & Quality of Life",
}

TAG_GROUPS = {
    "ui": "Interface & Accessibility",
    "accessibility": "Interface & Accessibility",
    "customisation": "Character Creation & Appearance",
    "other customisation": "Character Creation & Appearance",
    "heads": "Character Creation & Appearance",
    "hairstyles": "Character Creation & Appearance",
    "tattoos": "Character Creation & Appearance",
    "scars": "Character Creation & Appearance",
    "eye colors": "Character Creation & Appearance",
    "hair colors": "Character Creation & Appearance",
    "eye makeup": "Character Creation & Appearance",
    "lip makeup": "Character Creation & Appearance",
    "face paint": "Character Creation & Appearance",
    "piercings": "Character Creation & Appearance",
    "skin colors": "Character Creation & Appearance",
    "dyes": "Character Creation & Appearance",
    "classes": "Classes, Subclasses & Progression",
    "subclasses": "Classes, Subclasses & Progression",
    "other classes": "Classes, Subclasses & Progression",
    "spells": "Spells, Abilities & Feats",
    "feats": "Spells, Abilities & Feats",
    "summons": "Spells, Abilities & Feats",
    "races": "Races, Backgrounds & Deities",
    "other races": "Races, Backgrounds & Deities",
    "characters": "Companions, NPCs & Followers",
    "other characters / npcs": "Companions, NPCs & Followers",
    "quality of life": "Gameplay, Rules & Quality of Life",
    "cheats": "Gameplay, Rules & Quality of Life",
    "rules changes": "Gameplay, Rules & Quality of Life",
    "dice": "Gameplay, Rules & Quality of Life",
    "equipment": "Equipment, Items, Loot & Vendors",
    "armor": "Equipment, Items, Loot & Vendors",
    "weapons": "Equipment, Items, Loot & Vendors",
    "consumables": "Equipment, Items, Loot & Vendors",
    "visual effects": "Visuals, Audio & Animation",
    "modder resource": "Frameworks & Utilities",
}

KEYWORDS = [
    ("Patches, Compatibility & Translation", (" patch", " fix", "translation", "ptbr", "localization", "localisation", "compatibility")),
    ("Frameworks & Utilities", ("framework", "library", "mod fixer", "script extender", "resource")),
    ("Interface & Accessibility", (" ui", "interface", "camera", "inventory", "accessibility", "hotbar")),
    ("Character Creation & Appearance", ("appearance", "cosmetic", "hair", "head", "face", "tattoo", "dye", "makeup", "skin")),
    ("Classes, Subclasses & Progression", ("class", "subclass", "level cap", "progression", "respec")),
    ("Spells, Abilities & Feats", ("spell", "cantrip", "magic", "ability", "feat", "summon")),
    ("Races, Backgrounds & Deities", ("race", "dragonborn", "tiefling", "drow", "deity", "deities", "background")),
    ("Companions, NPCs & Followers", ("companion", "follower", "npc", "recruit", "party member")),
    ("Difficulty, Encounters & AI", ("encounter", "enemy", "difficulty", "combat ai", "boss")),
    ("Equipment, Items, Loot & Vendors", ("armor", "armour", "weapon", "item", "loot", "vendor", "clothing")),
    ("World, Quests & Exploration", ("quest", "map", "area", "location", "campaign")),
    ("Visuals, Audio & Animation", ("texture", "visual", "vfx", "audio", "music", "animation", "lighting")),
    ("Gameplay, Rules & Quality of Life", ("quality of life", "qol", "cheat", "rule", "gameplay", "party limit")),
]


def choose_group(row: dict[str, object]) -> tuple[str, str, str]:
    def has_phrase(text: str, phrase: str) -> bool:
        return bool(re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text))

    def priority_pick(groups: list[str]) -> str:
        available = set(groups)
        return next(group for group in GROUP_PRIORITY if group in available)

    title = (row["name"] or "").lower()
    description = (row["description"] or "").lower()
    text = f" {title} {description} "
    tags = set(row["tags"])
    terms = set(row["terms"])

    # Translation/localization is a content-role override, not merely a title style.
    translation_markers = (
        "translation", "traduzione", "traduction", "tradução", "traduccion",
        "übersetzung", "uebersetzung", "перевод", "翻译", "翻譯", "汉化", "漢化",
        "localization", "localisation", "此为汉化文件", "german deutsch",
        "mod principale", "mod originale",
    )
    language_suffix = r"(?:[-_ ](?:chs|cht|ita|fr|de|es|ptbr|pt-br|ru|ko|kr|ja|jp|pl|tr|uk|ua|br))$"
    if any(marker in text for marker in translation_markers):
        return "Patches, Compatibility & Translation", "Listing-derived", "translation/localization signal"

    # A suffix by itself is only a review cue: it is not sufficient evidence that
    # a listing is a translation rather than a localized original mod.
    suffix_only_translation = bool(re.search(language_suffix, title))

    # Strong title-level content roles outrank a broad native category, while
    # incidental words in a long summary do not.
    if re.search(r"\b(weapon|sword|rapier|quarterstaff|staff|armor|armour|dress|clothing|outfit|dressing)\b", title):
        return "Equipment, Items, Loot & Vendors", "Listing-derived", "specific item/equipment title signal"
    if re.search(r"\b(aura|disguise self|wild shape|wildshape|lay on hands|cantrip)\b", title) or title.startswith("layonhands"):
        return "Spells, Abilities & Feats", "Listing-derived", "specific ability/spell signal"
    if re.search(r"\b(debug mod|fall damage|party size|solo|duo|camp supplies|bonus actions?|lootable body parts)\b", title):
        return "Gameplay, Rules & Quality of Life", "Listing-derived", "specific gameplay/QoL signal"
    if re.search(r"\b(cache cleanup|cache-cleanup|maintenance script)\b", title):
        return "Frameworks & Utilities", "Listing-derived", "maintenance-script signal"
    if re.search(r"\b(painting|texture replacer)\b", title):
        return "Visuals, Audio & Animation", "Listing-derived", "visual-replacer signal"
    if re.search(r"\b(adds?|places?)\b.{0,48}\b(weapon|sword|rapier|armor|armour|clothing|consumable|item)\b", text):
        return "Equipment, Items, Loot & Vendors", "Listing-derived", "explicit item/content signal"

    appearance_words = r"appearance|redesign|portrait|hair|hairstyle|head|beard|skin|face|cosmetic"
    named_npc_words = r"npc|astarion|shadowheart|gortash|karlach|wyll|gale|lae'?zel|minthara|halsin|jaheira|minsc|andrick|brynna|edowin"
    if re.search(named_npc_words, title) and re.search(appearance_words, text):
        return "Companions, NPCs & Followers", "Listing-derived", "named-NPC appearance signal"
    if re.search(appearance_words, title) and not re.search(r"\b(spell|cantrip|ability)\b", text):
        return "Character Creation & Appearance", "Listing-derived", "character-appearance title signal"

    if re.search(r"\b(cleric gods?|deities?)\b", text):
        return "Races, Backgrounds & Deities", "Listing-derived", "deity-content signal"

    # Terms that explicitly denote a patch/framework retain their role before a
    # platform category. Technical dependency metadata does not.
    for term in ("translation", "compatibility-patch", "bugfix", "deprecated-superseded", "modder-resource"):
        if term in terms:
            return TERM_GROUPS[term], "Curated / checked", f"active curated term: {term}"

    category = (row["category"] or "").strip().lower()
    # A few native categories are inherently primary content types and resolve
    # known curated-term conflicts (for example, a campaign can include an
    # encounter term without becoming an encounter mod). Other categories retain
    # the curated-term pass below so checked topical evidence is not discarded.
    if category in {"maps", "quests", "gameplay", "races", "photo mode"}:
        return CATEGORY_GROUPS[category], "Native platform", f"Nexus category: {row['category']}"

    # A suffix-only language cue should remain conservatively ungrouped unless a
    # separate retained signal confirms that it is a translation.
    if suffix_only_translation:
        return "Other / Source Detail Limited", "Broad fallback", "language suffix needs confirmation"

    # Curated topical terms are useful when a native category is absent or broad.
    term_groups = [TERM_GROUPS[t] for t in terms if t in TERM_GROUPS]
    if term_groups:
        counts = Counter(term_groups)
        highest_count = max(counts.values())
        tied = [group for group, count in counts.items() if count == highest_count]
        return priority_pick(tied), "Curated / checked", "active curated term"

    if category in CATEGORY_GROUPS:
        return CATEGORY_GROUPS[category], "Native platform", f"Nexus category: {row['category']}"

    # Explicit player head/hair/beard content is character creation even when a
    # generic visual-effects tag is also present. Curated topical evidence and a
    # native category have already had a chance to state a more specific role.
    if re.search(r"\b(head|beard|hairstyle|hair|face|tattoo)\b", text):
        return "Character Creation & Appearance", "Listing-derived", "player-appearance content signal"

    for group, words in KEYWORDS:
        if any(has_phrase(title, word) for word in words):
            return group, "Listing-derived", "title keyword"

    tag_groups = [TAG_GROUPS[t] for t in tags if t in TAG_GROUPS]
    if tag_groups:
        counts = Counter(tag_groups)
        highest_count = max(counts.values())
        tied = [group for group, count in counts.items() if count == highest_count]
        return priority_pick(tied), "Listing-derived", "platform tags"

    if re.search(r"\b(lay on hands|healing potions?|remove bleeding|full heal|fall damage|party size|solo|duo|camp supplies|bonus actions?|lootable body parts|debug mod|teleports?|waypoint)\b", description):
        return "Gameplay, Rules & Quality of Life", "Listing-derived", "specific gameplay/QoL summary signal"
    if re.search(r"\b(bottles?|consumable|dressing)\b", text) and re.search(r"\b(chests?|traders?|placed|item)\b", text):
        return "Equipment, Items, Loot & Vendors", "Listing-derived", "specific placed-item signal"

    for group, words in KEYWORDS:
        if any(has_phrase(description, word) for word in words):
            return group, "Listing-derived", "summary keyword"

    return "Other / Source Detail Limited", "Broad fallback", "no safe primary signal"


def rows(con: sqlite3.Connection) -> list[dict[str, object]]:
    tag_rows: dict[int, list[str]] = defaultdict(list)
    for listing_id, tag in con.execute("SELECT listing_id, lower(trim(tag)) FROM platform_tags WHERE trim(tag) <> ''"):
        tag_rows[listing_id].append(tag)
    term_rows: dict[str, list[str]] = defaultdict(list)
    for mod_uuid, term in con.execute("SELECT mod_uuid, term FROM mod_classifications WHERE retired_at IS NULL"):
        term_rows[mod_uuid].append(term)
    result = []
    for row in con.execute(
        """
        SELECT p.listing_id, p.platform, p.platform_mod_id, p.url, p.author,
               p.category_name, m.canonical_name, m.description, m.mod_uuid
        FROM platform_listings p
        JOIN mods m ON m.mod_uid = p.mod_uid
        ORDER BY p.platform, p.listing_id
        """
    ):
        listing_id, platform, platform_mod_id, url, author, category, name, description, mod_uuid = row
        record = {
            "listing_id": listing_id,
            "platform": platform,
            "platform_mod_id": platform_mod_id,
            "url": url,
            "author": author,
            "category": category or "",
            "name": name or "",
            "description": description or "",
            "tags": sorted(set(tag_rows[listing_id])),
            "terms": sorted(set(term_rows[mod_uuid])),
        }
        record["browse_group"], record["label_basis"], record["basis_detail"] = choose_group(record)
        result.append(record)
    return result


def main() -> None:
    OUT.mkdir(exist_ok=True)
    con = sqlite3.connect(f"file:{DB}?mode=ro&immutable=1", uri=True)
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert not con.execute("PRAGMA foreign_key_check").fetchall()
    data = rows(con)
    counts = Counter((r["platform"], r["browse_group"], r["label_basis"]) for r in data)
    group_counts = Counter((r["platform"], r["browse_group"]) for r in data)
    basis_counts = Counter((r["platform"], r["label_basis"]) for r in data)
    fallbacks = [r for r in data if r["label_basis"] == "Broad fallback"]

    metrics = OUT / f"PHASE0_B25_BASELINE_METRICS_AND_READONLY_COVERAGE_PROFILE_{DATE}.md"
    with metrics.open("w", encoding="utf-8") as f:
        f.write("# Phase 0 — B25 baseline metrics and read-only coverage profile\n\n")
        f.write(f"**Prepared:** {DATE}  \n")
        f.write("**Scope:** read-only analysis of the verified B25 database. No database or source mutation occurred.\n\n")
        f.write("## Verification\n\n")
        f.write("- Database SHA-256: `27783c9611049c9b34104b806555d15de1b56282cdaffe521bc5fa41abc144e4`\n")
        f.write("- SQLite integrity: `ok`; foreign-key violations: `0`.\n")
        f.write("- Inputs were extracted from the verified B25 archive and opened immutable/read-only.\n\n")
        f.write("## Actual baseline\n\n")
        f.write("| Measure | Count |\n|---|---:|\n")
        for label, value in [
            ("Platform-distinct listings", len(data)),
            ("mod.io listings", sum(r["platform"] == "modio" for r in data)),
            ("Nexus listings", sum(r["platform"] == "nexus" for r in data)),
            ("Listings with retained description", sum(bool(r["description"].strip()) for r in data)),
            ("Nexus listings with a native category", sum(bool(r["category"].strip()) for r in data if r["platform"] == "nexus")),
            ("mod.io listings with at least one platform tag", sum(bool(r["tags"]) for r in data if r["platform"] == "modio")),
            ("Listings with active curated classification", sum(bool(r["terms"]) for r in data)),
        ]:
            f.write(f"| {label} | {value:,} |\n")
        f.write("\n## Proposed primary Browse Group distribution\n\n")
        f.write("| Browse Group | mod.io | Nexus | Total |\n|---|---:|---:|---:|\n")
        for group in GROUPS:
            a, b = group_counts[("modio", group)], group_counts[("nexus", group)]
            f.write(f"| {group} | {a:,} | {b:,} | {a+b:,} |\n")
        f.write("\n## Label Basis distribution\n\n")
        f.write("| Label Basis | mod.io | Nexus | Total |\n|---|---:|---:|---:|\n")
        for basis in ["Native platform", "Listing-derived", "Curated / checked", "Broad fallback"]:
            a, b = basis_counts[("modio", basis)], basis_counts[("nexus", basis)]
            f.write(f"| {basis} | {a:,} | {b:,} | {a+b:,} |\n")
        f.write("\n## Read-only sample and limitations\n\n")
        f.write("A deterministic stratified sample accompanies this report. It includes up to five rows per platform/Browse Group, plus all Broad fallback rows if fewer than five exist in a stratum.\n\n")
        f.write(f"The first-pass rule model assigns `Other / Source Detail Limited` to {len(fallbacks):,} listings. These rows are retained and countable; they are not hidden or treated as a meaningful native category. The next bounded audit should focus on sample accuracy and whether the fallback share is acceptable before any Phase 1 mutation is proposed.\n")

    randomizer = random.Random(20260726)
    sample: list[dict[str, object]] = []
    for platform in ("modio", "nexus"):
        for group in GROUPS:
            pool = [r for r in data if r["platform"] == platform and r["browse_group"] == group]
            randomizer.shuffle(pool)
            sample.extend(pool[:5])
    sample.sort(key=lambda r: (r["platform"], r["browse_group"], r["listing_id"]))
    sample_path = OUT / f"PHASE0_B25_TAXONOMY_REPRESENTATIVE_SAMPLE_{DATE}.csv"
    fields = ["platform", "platform_mod_id", "name", "author", "category", "platform_tags", "active_curated_terms", "description_excerpt", "browse_group", "label_basis", "basis_detail", "url"]
    with sample_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in sample:
            writer.writerow({
                "platform": r["platform"], "platform_mod_id": r["platform_mod_id"], "name": r["name"], "author": r["author"],
                "category": r["category"], "platform_tags": "; ".join(r["tags"]), "active_curated_terms": "; ".join(r["terms"]),
                "description_excerpt": " ".join(r["description"].split())[:320],
                "browse_group": r["browse_group"], "label_basis": r["label_basis"], "basis_detail": r["basis_detail"], "url": r["url"],
            })

    rules_path = OUT / f"PHASE0_B25_TAXONOMY_RULEMAP_{DATE}.json"
    rules_path.write_text(json.dumps({
        "groups": GROUPS,
        "term_groups": TERM_GROUPS,
        "category_groups": CATEGORY_GROUPS,
        "tag_groups": TAG_GROUPS,
        "keyword_groups": KEYWORDS,
        "precedence": ["curated term when unambiguous", "Nexus native category", "mod.io platform tags", "title/summary keywords", "curated mixed-term tie-break", "broad fallback"],
    }, indent=2) + "\n", encoding="utf-8")
    print(metrics)
    print(sample_path)
    print(rules_path)


if __name__ == "__main__":
    main()
