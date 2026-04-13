"""Creative Leaderboard — weekly ranking with position tracking.

Inspired by Motion App's Billboard-style Creative Leaderboard.
Tracks how long a creative holds its position and rank changes WoW.
"""

import sqlite3
from datetime import datetime, timedelta


# ══════════════════════════════════════════════════════
# SCHEMA
# ══════════════════════════════════════════════════════

LEADERBOARD_SCHEMA = """
CREATE TABLE IF NOT EXISTS leaderboard_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    week_start TEXT NOT NULL,
    ad_id TEXT NOT NULL,
    ad_name TEXT,
    campaign_name TEXT,
    rank INTEGER NOT NULL,
    spend REAL,
    revenue REAL,
    roas REAL,
    cpa REAL,
    purchases INTEGER,
    overall_score INTEGER,
    ad_type TEXT,
    UNIQUE(week_start, ad_id)
);
CREATE INDEX IF NOT EXISTS idx_lb_week ON leaderboard_history(week_start);
CREATE INDEX IF NOT EXISTS idx_lb_ad ON leaderboard_history(ad_id);
"""


def init_leaderboard_schema(conn):
    """Create leaderboard table if missing."""
    conn.executescript(LEADERBOARD_SCHEMA)
    conn.commit()


# ══════════════════════════════════════════════════════
# LEADERBOARD GENERATION
# ══════════════════════════════════════════════════════

def generate_leaderboard(conn, days=7, limit=20, reference_date=None):
    """Generate weekly creative leaderboard.

    Ranked by spend (primary). Includes position changes vs last week.

    Returns:
        list of {rank, ad_id, ad_name, campaign_name, spend, spend_delta,
                 roas, roas_delta, wks_on_board, rank_change, ad_type, overall_score}
    """
    if reference_date is None:
        reference_date = datetime.now().strftime("%Y-%m-%d")

    ref = datetime.strptime(reference_date, "%Y-%m-%d")
    this_week_start = (ref - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    last_week_start = (ref - timedelta(days=days * 2 - 1)).strftime("%Y-%m-%d")
    last_week_end = (ref - timedelta(days=days)).strftime("%Y-%m-%d")

    # Check if creative_tags table exists
    has_tags = conn.execute(
        "SELECT count(*) as c FROM sqlite_master WHERE type='table' AND name='creative_tags'"
    ).fetchone()["c"] > 0

    # This week performance
    if has_tags:
        this_week = conn.execute("""
            SELECT
                s.ad_id, s.ad_name, s.campaign_name,
                SUM(s.spend) as spend,
                SUM(s.revenue) as revenue,
                SUM(s.purchases) as purchases,
                COALESCE(ct.ad_type,
                         CASE WHEN AVG(s.hook_rate) IS NOT NULL THEN 'Video' ELSE 'Image' END
                ) as ad_type
            FROM ad_daily_snapshots s
            LEFT JOIN creative_tags ct ON s.ad_id = ct.ad_id
            WHERE s.snapshot_date BETWEEN ? AND ?
            GROUP BY s.ad_id
            HAVING spend > 0
            ORDER BY spend DESC
            LIMIT ?
        """, (this_week_start, reference_date, limit)).fetchall()
    else:
        this_week = conn.execute("""
            SELECT
                ad_id, ad_name, campaign_name,
                SUM(spend) as spend,
                SUM(revenue) as revenue,
                SUM(purchases) as purchases,
                CASE WHEN AVG(hook_rate) IS NOT NULL THEN 'Video' ELSE 'Image' END as ad_type
            FROM ad_daily_snapshots
            WHERE snapshot_date BETWEEN ? AND ?
            GROUP BY ad_id
            HAVING spend > 0
            ORDER BY spend DESC
            LIMIT ?
        """, (this_week_start, reference_date, limit)).fetchall()

    # Last week performance (for deltas)
    last_week_map = {}
    for r in conn.execute("""
        SELECT ad_id, SUM(spend) as spend, SUM(revenue) as revenue,
               SUM(purchases) as purchases
        FROM ad_daily_snapshots
        WHERE snapshot_date BETWEEN ? AND ?
        GROUP BY ad_id
    """, (last_week_start, last_week_end)).fetchall():
        last_week_map[r["ad_id"]] = dict(r)

    # Last week's leaderboard ranks (for rank_change)
    last_lb = {}
    try:
        for r in conn.execute("""
            SELECT ad_id, rank FROM leaderboard_history
            WHERE week_start = ?
        """, (last_week_start,)).fetchall():
            last_lb[r["ad_id"]] = r["rank"]
    except Exception:
        pass  # table might not exist yet

    # Weeks on board (how many consecutive weeks in leaderboard)
    wks_cache = {}
    try:
        for r in conn.execute("""
            SELECT ad_id, COUNT(DISTINCT week_start) as weeks
            FROM leaderboard_history
            GROUP BY ad_id
        """).fetchall():
            wks_cache[r["ad_id"]] = r["weeks"]
    except Exception:
        pass

    # Funnel scores
    scores_map = {}
    try:
        for r in conn.execute("""
            SELECT ad_id, overall_score FROM funnel_scores
            WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM funnel_scores)
        """).fetchall():
            scores_map[r["ad_id"]] = r["overall_score"]
    except Exception:
        pass

    # Build leaderboard
    leaderboard = []
    for rank, row in enumerate(this_week, 1):
        ad_id = row["ad_id"]
        spend = row["spend"] or 0
        revenue = row["revenue"] or 0
        purchases = row["purchases"] or 0
        roas = revenue / spend if spend > 0 else None
        cpa = spend / purchases if purchases > 0 else None

        # Deltas vs last week
        prev = last_week_map.get(ad_id, {})
        prev_spend = prev.get("spend", 0)
        prev_revenue = prev.get("revenue", 0)
        prev_roas = prev_revenue / prev_spend if prev_spend > 0 else None

        spend_delta = round(((spend - prev_spend) / prev_spend) * 100, 1) if prev_spend > 0 else None
        roas_delta = round(((roas - prev_roas) / prev_roas) * 100, 1) if roas and prev_roas and prev_roas > 0 else None

        # Rank change
        prev_rank = last_lb.get(ad_id)
        rank_change = prev_rank - rank if prev_rank is not None else None  # positive = moved up

        # Weeks on board (+1 for this week)
        wks = wks_cache.get(ad_id, 0) + 1

        leaderboard.append({
            "rank": rank,
            "ad_id": ad_id,
            "ad_name": row["ad_name"] or ad_id,
            "campaign_name": row["campaign_name"] or "",
            "ad_type": row["ad_type"] or "Image",
            "spend": round(spend, 0),
            "spend_delta": spend_delta,
            "revenue": round(revenue, 0),
            "roas": round(roas, 2) if roas else None,
            "roas_delta": roas_delta,
            "cpa": round(cpa, 0) if cpa else None,
            "purchases": purchases,
            "rank_change": rank_change,
            "wks_on_board": wks,
            "overall_score": scores_map.get(ad_id),
            "is_new_entry": prev_rank is None,
        })

    return leaderboard


def save_leaderboard(conn, leaderboard, week_start):
    """Save leaderboard snapshot to history."""
    init_leaderboard_schema(conn)
    saved = 0
    for entry in leaderboard:
        try:
            conn.execute("""
                INSERT OR REPLACE INTO leaderboard_history (
                    week_start, ad_id, ad_name, campaign_name,
                    rank, spend, revenue, roas, cpa, purchases,
                    overall_score, ad_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                week_start, entry["ad_id"], entry["ad_name"],
                entry["campaign_name"], entry["rank"],
                entry["spend"], entry["revenue"], entry["roas"],
                entry["cpa"], entry["purchases"],
                entry.get("overall_score"), entry.get("ad_type"),
            ))
            saved += 1
        except Exception as e:
            import sys
            print(f"  WARN: save leaderboard {entry['ad_id']}: {e}", file=sys.stderr)

    conn.commit()
    return saved


# ══════════════════════════════════════════════════════
# TEXT REPORT
# ══════════════════════════════════════════════════════

def format_leaderboard_report(leaderboard, top_n=10):
    """Format leaderboard as readable text."""
    lines = ["CREATIVE LEADERBOARD", ""]
    lines.append(f"{'#':<3} {'Creative':<35} {'Type':<5} {'Wks':<4} {'Spend':>10} {'ROAS':>6}")
    lines.append("-" * 70)

    for entry in leaderboard[:top_n]:
        # Rank change indicator
        rc = entry.get("rank_change")
        if entry.get("is_new_entry"):
            indicator = "NEW"
        elif rc is not None and rc > 0:
            indicator = f"▲{rc}"
        elif rc is not None and rc < 0:
            indicator = f"▼{abs(rc)}"
        else:
            indicator = "="

        # Spend delta
        sd = entry.get("spend_delta")
        spend_str = f"{entry['spend']:>8,.0f}"
        if sd is not None:
            spend_str += f" {'+' if sd >= 0 else ''}{sd:.0f}%"

        # ROAS
        roas_str = f"{entry['roas']:.2f}" if entry.get("roas") else "N/A"
        rd = entry.get("roas_delta")
        if rd is not None:
            roas_str += f" {'+' if rd >= 0 else ''}{rd:.0f}%"

        # Weeks
        wks = entry.get("wks_on_board", 1)
        wks_str = f"{wks}w" if wks <= 6 else "6w+"

        name = entry["ad_name"][:33]
        ad_type = entry.get("ad_type", "?")[:3]

        lines.append(
            f"{entry['rank']:<3} {name:<35} {ad_type:<5} {wks_str:<4} {spend_str:>14} {roas_str:>8}  {indicator}"
        )

    lines.append("")
    return "\n".join(lines)
