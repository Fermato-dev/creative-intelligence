#!/usr/bin/env python3
"""
Load precise archetype tagger JSON output into creative_analysis.db.
Runs after the tagger script produces new JSON. No API calls, no cost.

Usage:
    python scripts/update_creative_tags.py                        # find latest JSON
    python scripts/update_creative_tags.py --file path/to.json    # specific file
"""

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
DATA_DIR = REPO_ROOT / "data"
DB_PATH = DATA_DIR / "creative_analysis.db"

# Paths to search for tagger output
SEARCH_PATHS = [
    DATA_DIR,
    REPO_ROOT.parent / "Chief-of-Staff" / "scripts" / "analysis",
    Path.home() / "Chief-of-Staff" / "scripts" / "analysis",
]


def find_latest_json():
    """Find the most recent precise_tags_output.json."""
    candidates = []
    for search_dir in SEARCH_PATHS:
        if search_dir.exists():
            for f in search_dir.glob("*precise_tags_output*.json"):
                candidates.append(f)
    if not candidates:
        return None
    return max(candidates, key=lambda f: f.stat().st_mtime)


def load_tags(json_path):
    """Load and validate tagger JSON."""
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    print(f"Loaded {len(data)} ads from {json_path}")
    return data


def _map_archetype_to_visual_format(archetype):
    """Map v2 archetype names to v3.5 visual_format names."""
    _map = {
        "product_demo": "Product_Demo",
        "founder_story": "Founder_Story",
        "ugc_social_proof": "UGC_Testimonial",
        "lifestyle": "Lifestyle_InUse",
        "problem_solution": "Text_Overlay",
        "educational": "Text_Overlay",
    }
    return _map.get(archetype, archetype)


def _map_hook_to_hook_type(hook_strategy):
    """Map v2 hook_strategy to v3.5 hook_type."""
    _map = {
        "curiosity_gap": "Curiosity_Gap", "visual_reveal": "Visual_Reveal",
        "question": "Question", "ugc_reaction": "UGC_Reaction",
        "statement": "Statement", "product_hero": "Product_Hero",
        "contradiction": "Contradiction", "problem_opening": "Problem_Opening",
    }
    return _map.get(hook_strategy, hook_strategy)


def insert_tags(data, source_file):
    """Insert tags into creative_analysis.db (supports both v2 JSON and v3.5 schema)."""
    conn = sqlite3.connect(str(DB_PATH))
    tagged_at = datetime.now().strftime("%Y-%m-%d")

    inserted = 0
    for ad in data:
        if not ad.get("ad_id"):
            continue
        # Support both v2 (archetype) and v3.5 (visual_format) JSON input
        visual_format = ad.get("visual_format") or _map_archetype_to_visual_format(ad.get("archetype", ""))
        hook_type = ad.get("hook_type") or _map_hook_to_hook_type(ad.get("hook_strategy", ""))
        has_person = ad.get("has_person")
        if has_person is None:
            pp = ad.get("person_present", "")
            has_person = 1 if pp == "yes" else 0 if pp == "no" else None

        try:
            conn.execute("""
                INSERT OR REPLACE INTO creative_tags
                (ad_id, ad_name, campaign_name, visual_format, visual_format_confidence,
                 messaging_angle, messaging_confidence, ad_type, hook_type,
                 production_quality, has_text_overlay, has_person, has_product,
                 dominant_color, brief_description, thumbnail_url, ad_copy,
                 tagged_at, tagged_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ad.get("ad_id"), ad.get("ad_name"), ad.get("campaign_name"),
                visual_format, ad.get("archetype_confidence") or ad.get("visual_format_confidence"),
                ad.get("messaging_angle"), ad.get("messaging_confidence"),
                ad.get("ad_type"), hook_type,
                ad.get("production_quality"),
                ad.get("has_text_overlay"), has_person, ad.get("has_product"),
                ad.get("dominant_color"), ad.get("archetype_reasoning") or ad.get("brief_description"),
                ad.get("thumbnail_url"), ad.get("ad_copy"),
                tagged_at, f"json_import:{Path(source_file).name}",
            ))
            inserted += 1
        except Exception as e:
            print(f"  WARN: {ad.get('ad_id')}: {e}", file=sys.stderr)

    conn.commit()
    conn.close()
    print(f"Inserted {inserted} tags into {DB_PATH} (tagged_at={tagged_at})")


def main():
    json_path = None
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--file" and i < len(sys.argv) - 1:
            json_path = Path(sys.argv[i + 1])

    if not json_path:
        json_path = find_latest_json()

    if not json_path or not json_path.exists():
        print("ERROR: No tagger JSON found. Run the precise tagger first.")
        sys.exit(1)

    data = load_tags(json_path)
    insert_tags(data, str(json_path))


if __name__ == "__main__":
    main()
