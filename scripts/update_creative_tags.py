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


def insert_tags(data, source_file):
    """Insert tags into creative_analysis.db."""
    conn = sqlite3.connect(str(DB_PATH))
    tagged_at = datetime.now().strftime("%Y-%m-%d")

    inserted = 0
    for ad in data:
        if not ad.get("ad_id"):
            continue
        try:
            conn.execute("""
                INSERT OR REPLACE INTO creative_tags
                (ad_id, ad_name, campaign_name, archetype, archetype_confidence,
                 archetype_reasoning, hook_strategy, energy_level, visual_style,
                 person_present, person_type, food_visible, text_overlay_content,
                 production_quality, dominant_color, frames_count, has_transcript,
                 ad_copy, impressions, spend, purchases, hook_rate, roas, cpa, tagged_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ad.get("ad_id"), ad.get("ad_name"), ad.get("campaign_name"),
                ad.get("archetype"), ad.get("archetype_confidence"),
                ad.get("archetype_reasoning"), ad.get("hook_strategy"),
                ad.get("energy_level"), ad.get("visual_style"),
                ad.get("person_present"), ad.get("person_type"),
                ad.get("food_visible"), ad.get("text_overlay_content"),
                ad.get("production_quality"), ad.get("dominant_color"),
                ad.get("frames_count"), 1 if ad.get("has_transcript") else 0,
                ad.get("ad_copy"), ad.get("impressions"), ad.get("spend"),
                ad.get("purchases"), ad.get("hook_rate"), ad.get("roas"),
                ad.get("cpa"), tagged_at,
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
