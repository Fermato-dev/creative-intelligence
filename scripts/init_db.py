"""
Startup DB validation — ensures creative_analysis.db has correct schema.
Runs before Streamlit on Railway deploy.

Autor: Claude Code + CEO
Datum: 2026-04-04
"""

import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
DB_PATH = REPO_ROOT / "data" / "creative_analysis.db"

REQUIRED_TABLES = ["components", "tested_combinations", "recommendations"]


def init():
    """Validate DB exists and has v3 schema. Create schema if missing."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    if not DB_PATH.exists() or DB_PATH.stat().st_size == 0:
        print(f"INIT: DB missing or empty at {DB_PATH}, creating schema...")
        _create_schema()
        return

    # DB exists — check tables
    conn = sqlite3.connect(str(DB_PATH))
    tables = [t[0] for t in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    conn.close()

    missing = [t for t in REQUIRED_TABLES if t not in tables]
    if missing:
        print(f"INIT: DB missing tables {missing}, initializing schema...")
        _create_schema()
        return

    # All good — report status
    conn = sqlite3.connect(str(DB_PATH))
    count = conn.execute("SELECT count(*) FROM components").fetchone()[0]
    rec_count = conn.execute("SELECT count(*) FROM recommendations").fetchone()[0]
    conn.close()
    print(f"INIT: DB OK — {count} components, {rec_count} recommendations ({DB_PATH.stat().st_size} bytes)")


def _create_schema():
    """Create v3 component library schema."""
    conn = sqlite3.connect(str(DB_PATH))
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
    conn.commit()
    conn.close()
    print(f"INIT: Schema created ({DB_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    try:
        init()
    except Exception as e:
        print(f"INIT ERROR: {e}", file=sys.stderr)
        sys.exit(1)
