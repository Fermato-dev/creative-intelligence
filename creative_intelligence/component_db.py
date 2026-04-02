"""v3: Component Library — SQLite database of hooks, bodies, CTAs with metrics.

Kazda kreativa se rozlozi na komponenty. Komponenty se ukladaji
do SQLite DB se svymi performance metrikami. Umoznuje:
- Hledani top hooku, bodies, CTA
- Cross-ad srovnani komponent
- Zaklad pro kombinatoricka doporuceni
"""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from .config import DB_PATH, DATA_DIR, COMPONENT_REANALYSIS_DAYS


def get_db():
    """Get SQLite connection with initialized schema."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    _init_schema(conn)
    return conn


def _init_schema(conn):
    conn.executescript("""
        -- Component library: hooks, bodies, CTAs
        CREATE TABLE IF NOT EXISTS components (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ad_id TEXT NOT NULL,
            component_type TEXT NOT NULL CHECK(component_type IN ('hook', 'body', 'cta')),
            video_id TEXT,

            -- Timing
            start_time REAL NOT NULL DEFAULT 0,
            end_time REAL NOT NULL DEFAULT 0,
            duration REAL GENERATED ALWAYS AS (end_time - start_time) STORED,

            -- AI analysis (JSON)
            analysis TEXT,
            transcript TEXT,

            -- Performance metrics (from parent ad at time of analysis)
            hook_rate REAL,
            hold_rate REAL,
            completion_rate REAL,
            roas REAL,
            cpa REAL,
            cvr REAL,
            spend REAL,
            purchases INTEGER,
            impressions INTEGER,

            -- Metadata
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

        -- Component combinations that have been tested
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

        -- Recommendations log
        CREATE TABLE IF NOT EXISTS recommendations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rec_type TEXT NOT NULL,  -- SWAP_HOOK, NEW_COMBINATION, REFRESH_ALERT
            description TEXT NOT NULL,
            details TEXT,  -- JSON with full recommendation data
            created_at TEXT NOT NULL,
            status TEXT DEFAULT 'pending'  -- pending, accepted, rejected, expired
        );
    """)
    conn.commit()


# ── Component CRUD ──

def save_component(conn, ad_id, component_type, start_time, end_time,
                   analysis=None, transcript=None, performance=None,
                   campaign_name=None, ad_name=None, thumbnail_path=None,
                   video_id=None):
    """Save or update a component in the library."""
    perf = performance or {}
    now = datetime.now().isoformat()

    # Upsert: delete + insert
    conn.execute("DELETE FROM components WHERE ad_id = ? AND component_type = ?",
                 (ad_id, component_type))
    conn.execute("""
        INSERT INTO components
        (ad_id, component_type, video_id, start_time, end_time,
         analysis, transcript,
         hook_rate, hold_rate, completion_rate, roas, cpa, cvr,
         spend, purchases, impressions,
         campaign_name, ad_name, thumbnail_path, analyzed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        ad_id, component_type, video_id, start_time, end_time,
        json.dumps(analysis, ensure_ascii=False) if analysis else None,
        transcript,
        perf.get("hook_rate"), perf.get("hold_rate"), perf.get("completion_rate"),
        perf.get("roas"), perf.get("cpa"), perf.get("cvr"),
        perf.get("spend"), perf.get("purchases"), perf.get("impressions"),
        campaign_name, ad_name, thumbnail_path, now,
    ))
    conn.commit()


def get_component(conn, ad_id, component_type):
    """Get a specific component."""
    row = conn.execute(
        "SELECT * FROM components WHERE ad_id = ? AND component_type = ?",
        (ad_id, component_type)
    ).fetchone()
    return _row_to_dict(row) if row else None


def get_top_components(conn, component_type, metric="hook_rate", limit=20, min_spend=200):
    """Get top components by a given metric."""
    valid_metrics = {"hook_rate", "hold_rate", "roas", "cpa", "cvr", "spend", "completion_rate"}
    if metric not in valid_metrics:
        raise ValueError(f"Invalid metric: {metric}. Use: {valid_metrics}")

    order = "ASC" if metric == "cpa" else "DESC"

    rows = conn.execute(f"""
        SELECT * FROM components
        WHERE component_type = ?
          AND {metric} IS NOT NULL
          AND spend >= ?
        ORDER BY {metric} {order}
        LIMIT ?
    """, (component_type, min_spend, limit)).fetchall()

    return [_row_to_dict(r) for r in rows]


def get_all_components(conn, component_type=None):
    """Get all components, optionally filtered by type."""
    if component_type:
        rows = conn.execute(
            "SELECT * FROM components WHERE component_type = ? ORDER BY analyzed_at DESC",
            (component_type,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM components ORDER BY component_type, analyzed_at DESC"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def count_components(conn):
    """Count components by type."""
    rows = conn.execute("""
        SELECT component_type, COUNT(*) as count,
               AVG(hook_rate) as avg_hook_rate,
               AVG(roas) as avg_roas
        FROM components
        GROUP BY component_type
    """).fetchall()
    return {r["component_type"]: {"count": r["count"], "avg_hook_rate": r["avg_hook_rate"],
                                   "avg_roas": r["avg_roas"]} for r in rows}


def needs_reanalysis(conn, ad_id, component_type):
    """Check if component needs re-analysis."""
    comp = get_component(conn, ad_id, component_type)
    if not comp:
        return True
    analyzed = datetime.fromisoformat(comp["analyzed_at"])
    return datetime.now() - analyzed > timedelta(days=COMPONENT_REANALYSIS_DAYS)


# ── Tested combinations ──

def save_tested_combination(conn, hook_id, body_id, cta_id, ad_id=None,
                            roas=None, cpa=None, cvr=None, spend=None):
    """Record a tested hook×body×CTA combination."""
    conn.execute("""
        INSERT OR REPLACE INTO tested_combinations
        (hook_component_id, body_component_id, cta_component_id,
         ad_id, roas, cpa, cvr, spend, noted_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (hook_id, body_id, cta_id, ad_id, roas, cpa, cvr, spend,
          datetime.now().isoformat()))
    conn.commit()


def get_tested_combinations(conn, limit=50):
    """Get tested combinations with performance data."""
    rows = conn.execute("""
        SELECT tc.*,
               h.ad_name as hook_ad_name, h.analysis as hook_analysis,
               b.ad_name as body_ad_name,
               c.ad_name as cta_ad_name
        FROM tested_combinations tc
        LEFT JOIN components h ON tc.hook_component_id = h.id
        LEFT JOIN components b ON tc.body_component_id = b.id
        LEFT JOIN components c ON tc.cta_component_id = c.id
        ORDER BY tc.roas DESC NULLS LAST
        LIMIT ?
    """, (limit,)).fetchall()
    return [_row_to_dict(r) for r in rows]


def is_combination_tested(conn, hook_id, body_id, cta_id):
    """Check if a specific combination was already tested."""
    row = conn.execute("""
        SELECT id FROM tested_combinations
        WHERE hook_component_id = ? AND body_component_id = ? AND cta_component_id = ?
    """, (hook_id, body_id, cta_id)).fetchone()
    return row is not None


# ── Recommendations ──

def save_recommendation(conn, rec_type, description, details=None):
    """Save a recommendation."""
    conn.execute("""
        INSERT INTO recommendations (rec_type, description, details, created_at)
        VALUES (?, ?, ?, ?)
    """, (rec_type, description,
          json.dumps(details, ensure_ascii=False) if details else None,
          datetime.now().isoformat()))
    conn.commit()


def get_pending_recommendations(conn, limit=20):
    """Get pending recommendations."""
    rows = conn.execute("""
        SELECT * FROM recommendations
        WHERE status = 'pending'
        ORDER BY created_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    return [_row_to_dict(r) for r in rows]


# ── Build library from ads_metrics ──

def build_library_from_analysis(conn, ad_id, decomposition_result, performance):
    """Save decomposed components from a full analysis result into the library."""
    decomp = decomposition_result.get("decomposition", {})

    for comp_type in ["hook", "body", "cta"]:
        analysis = decomposition_result.get(f"{comp_type}_analysis")
        time_range = decomp.get(f"{comp_type}_range", [0, 0])

        save_component(
            conn,
            ad_id=ad_id,
            component_type=comp_type,
            start_time=time_range[0] if len(time_range) > 0 else 0,
            end_time=time_range[1] if len(time_range) > 1 else 0,
            analysis=analysis,
            performance=performance,
            ad_name=performance.get("ad_name", ""),
            campaign_name=performance.get("campaign_name", ""),
        )


# ── Helpers ──

def _row_to_dict(row):
    if row is None:
        return None
    d = dict(row)
    # Parse JSON fields
    for field in ["analysis", "details"]:
        if field in d and d[field] and isinstance(d[field], str):
            try:
                d[field] = json.loads(d[field])
            except json.JSONDecodeError:
                pass
    return d


def print_library_summary(conn):
    """Print a human-readable summary of the component library."""
    counts = count_components(conn)
    total = sum(c["count"] for c in counts.values())
    print(f"\nComponent Library: {total} komponent")
    print(f"{'Type':<8} {'Count':>6} {'Avg Hook':>10} {'Avg ROAS':>10}")
    print(f"{'-'*8} {'-'*6} {'-'*10} {'-'*10}")
    for comp_type in ["hook", "body", "cta"]:
        c = counts.get(comp_type, {"count": 0, "avg_hook_rate": None, "avg_roas": None})
        hook = f"{c['avg_hook_rate']:.1f}%" if c["avg_hook_rate"] else "—"
        roas = f"{c['avg_roas']:.2f}" if c["avg_roas"] else "—"
        print(f"{comp_type:<8} {c['count']:>6} {hook:>10} {roas:>10}")
