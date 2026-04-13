"""
Startup DB validation — ensures all SQLite DBs have correct schema.
Runs before Streamlit on Railway deploy.

Autor: Claude Code + CEO
Datum: 2026-04-04
"""

import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
DATA_DIR = REPO_ROOT / "data"
COMPONENT_DB = DATA_DIR / "creative_analysis.db"
VOICE_DB = DATA_DIR / "customer_voice.db"


def init():
    """Validate all DBs exist and have correct schemas."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    _init_component_db()
    _init_voice_db()


def _init_component_db():
    """Validate component library DB + change tracking tables."""
    required = ["components", "tested_combinations", "recommendations",
                "ad_daily_snapshots", "change_events", "learnings",
                "creative_tags"]

    if not COMPONENT_DB.exists() or COMPONENT_DB.stat().st_size == 0:
        print(f"INIT: Component DB missing/empty, creating schema...")
        _create_component_schema()
        return

    conn = sqlite3.connect(str(COMPONENT_DB))
    tables = [t[0] for t in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    conn.close()

    missing = [t for t in required if t not in tables]
    if missing:
        print(f"INIT: Component DB missing tables {missing}, initializing...")
        _create_component_schema()
        return

    conn = sqlite3.connect(str(COMPONENT_DB))
    count = conn.execute("SELECT count(*) FROM components").fetchone()[0]
    rec_count = conn.execute("SELECT count(*) FROM recommendations").fetchone()[0]
    snap_count = conn.execute("SELECT count(*) FROM ad_daily_snapshots").fetchone()[0]
    change_count = conn.execute("SELECT count(*) FROM change_events").fetchone()[0]
    conn.close()
    print(f"INIT: Component DB OK — {count} components, {rec_count} recommendations, "
          f"{snap_count} snapshots, {change_count} changes")


def _init_voice_db():
    """Validate customer voice DB."""
    required = ["voice_sources", "customer_profiles"]

    if not VOICE_DB.exists() or VOICE_DB.stat().st_size == 0:
        print(f"INIT: Voice DB missing/empty, creating schema...")
        _create_voice_schema()
        return

    conn = sqlite3.connect(str(VOICE_DB))
    tables = [t[0] for t in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    conn.close()

    missing = [t for t in required if t not in tables]
    if missing:
        print(f"INIT: Voice DB missing tables {missing}, initializing...")
        _create_voice_schema()
        return

    conn = sqlite3.connect(str(VOICE_DB))
    profiles = conn.execute("SELECT count(*) FROM customer_profiles").fetchone()[0]
    sources = conn.execute("SELECT count(*) FROM voice_sources").fetchone()[0]
    conn.close()
    print(f"INIT: Voice DB OK — {profiles} profiles, {sources} sources")


def _create_component_schema():
    """Create v3 component library schema + change tracking tables."""
    conn = sqlite3.connect(str(COMPONENT_DB))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS components (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ad_id TEXT NOT NULL,
            component_type TEXT NOT NULL CHECK(component_type IN ('hook', 'body', 'cta')),
            video_id TEXT,
            start_time REAL NOT NULL DEFAULT 0,
            end_time REAL NOT NULL DEFAULT 0,
            duration REAL GENERATED ALWAYS AS (end_time - start_time) STORED,
            analysis TEXT,
            transcript TEXT,
            hook_rate REAL,
            hold_rate REAL,
            completion_rate REAL,
            roas REAL,
            cpa REAL,
            cvr REAL,
            spend REAL,
            purchases INTEGER,
            impressions INTEGER,
            campaign_name TEXT,
            ad_name TEXT,
            thumbnail_path TEXT,
            analyzed_at TEXT NOT NULL,
            updated_at TEXT,
            UNIQUE(ad_id, component_type)
        );
        CREATE INDEX IF NOT EXISTS idx_comp_type ON components(component_type);
        CREATE INDEX IF NOT EXISTS idx_comp_ad ON components(ad_id);
        CREATE INDEX IF NOT EXISTS idx_comp_hook_rate ON components(hook_rate DESC);
        CREATE INDEX IF NOT EXISTS idx_comp_roas ON components(roas DESC);

        CREATE TABLE IF NOT EXISTS tested_combinations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hook_component_id INTEGER REFERENCES components(id),
            body_component_id INTEGER REFERENCES components(id),
            cta_component_id INTEGER REFERENCES components(id),
            ad_id TEXT,
            roas REAL,
            cpa REAL,
            cvr REAL,
            spend REAL,
            noted_at TEXT NOT NULL,
            UNIQUE(hook_component_id, body_component_id, cta_component_id)
        );

        CREATE TABLE IF NOT EXISTS recommendations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rec_type TEXT NOT NULL,
            description TEXT NOT NULL,
            details TEXT,
            created_at TEXT NOT NULL,
            status TEXT DEFAULT 'pending'
        );
    """)
    # Creative diversity tags
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS creative_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ad_id TEXT NOT NULL,
            ad_name TEXT,
            campaign_name TEXT,
            archetype TEXT,
            archetype_confidence REAL,
            archetype_reasoning TEXT,
            hook_strategy TEXT,
            energy_level TEXT,
            visual_style TEXT,
            person_present TEXT,
            person_type TEXT,
            food_visible TEXT,
            text_overlay_content TEXT,
            production_quality TEXT,
            dominant_color TEXT,
            frames_count INTEGER,
            has_transcript BOOLEAN DEFAULT 0,
            ad_copy TEXT,
            impressions INTEGER,
            spend REAL,
            purchases INTEGER,
            hook_rate REAL,
            roas REAL,
            cpa REAL,
            thumbnail_url TEXT,
            image_url TEXT,
            video_id TEXT,
            tagged_at TEXT NOT NULL,
            UNIQUE(ad_id, tagged_at)
        );
        CREATE INDEX IF NOT EXISTS idx_tags_archetype ON creative_tags(archetype);
        CREATE INDEX IF NOT EXISTS idx_tags_ad ON creative_tags(ad_id);
        CREATE INDEX IF NOT EXISTS idx_tags_tagged ON creative_tags(tagged_at);
    """)

    # Change tracking tables
    from creative_intelligence.change_tracker import CHANGE_TRACKING_SCHEMA
    conn.executescript(CHANGE_TRACKING_SCHEMA)

    conn.commit()
    conn.close()
    print(f"INIT: Component schema created ({COMPONENT_DB.stat().st_size} bytes)")


def _create_voice_schema():
    """Create customer voice schema."""
    conn = sqlite3.connect(str(VOICE_DB))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS voice_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_key TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_url TEXT,
            raw_content TEXT NOT NULL,
            fetched_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS customer_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_key TEXT NOT NULL,
            profile_json TEXT NOT NULL,
            voice_vocabulary TEXT NOT NULL,
            source_count INTEGER,
            created_at TEXT NOT NULL,
            cost_usd REAL
        );
        CREATE INDEX IF NOT EXISTS idx_voice_product ON voice_sources(product_key);
        CREATE INDEX IF NOT EXISTS idx_profile_product ON customer_profiles(product_key);
    """)
    conn.commit()
    conn.close()
    print(f"INIT: Voice schema created ({VOICE_DB.stat().st_size} bytes)")


if __name__ == "__main__":
    try:
        init()
    except Exception as e:
        print(f"INIT ERROR: {e}", file=sys.stderr)
        sys.exit(1)
