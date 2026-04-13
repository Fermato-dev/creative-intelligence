"""Comparative Analysis — cross-dimensional performance comparison.

Inspired by Motion App's Ad Type Comparison, Visual Format Breakdown,
Landing Page Analysis, and Ad Length Comparison reports.
"""

import sqlite3
from datetime import datetime, timedelta


# ══════════════════════════════════════════════════════
# AD TYPE COMPARISON (Video vs Image vs Carousel)
# ══════════════════════════════════════════════════════

def _has_table(conn, name):
    """Check if a table exists in the database."""
    return conn.execute(
        "SELECT count(*) as c FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()["c"] > 0


def compare_ad_types(conn, days=14):
    """Compare performance by ad type (Video / Image / Carousel).

    Uses creative_tags for type when available, falls back to is_video heuristic.

    Returns:
        list of {ad_type, count, total_spend, avg_roas, avg_cpa, avg_ctr, avg_hook_rate}
    """
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    if _has_table(conn, "creative_tags"):
        rows = conn.execute("""
            SELECT
                COALESCE(ct.ad_type,
                         CASE WHEN s.hook_rate IS NOT NULL THEN 'Video' ELSE 'Image' END
                ) as ad_type,
                COUNT(DISTINCT s.ad_id) as count,
                SUM(s.spend) as total_spend, SUM(s.revenue) as total_revenue,
                SUM(s.purchases) as total_purchases, SUM(s.impressions) as total_impressions,
                SUM(s.clicks) as total_clicks,
                AVG(s.hook_rate) as avg_hook_rate, AVG(s.hold_rate) as avg_hold_rate
            FROM ad_daily_snapshots s
            LEFT JOIN creative_tags ct ON s.ad_id = ct.ad_id
            WHERE s.snapshot_date >= ?
            GROUP BY ad_type
            ORDER BY total_spend DESC
        """, (since,)).fetchall()
    else:
        rows = conn.execute("""
            SELECT
                CASE WHEN hook_rate IS NOT NULL THEN 'Video' ELSE 'Image' END as ad_type,
                COUNT(DISTINCT ad_id) as count,
                SUM(spend) as total_spend, SUM(revenue) as total_revenue,
                SUM(purchases) as total_purchases, SUM(impressions) as total_impressions,
                SUM(clicks) as total_clicks,
                AVG(hook_rate) as avg_hook_rate, AVG(hold_rate) as avg_hold_rate
            FROM ad_daily_snapshots
            WHERE snapshot_date >= ?
            GROUP BY ad_type
            ORDER BY total_spend DESC
        """, (since,)).fetchall()

    results = []
    for r in rows:
        spend = r["total_spend"] or 0
        revenue = r["total_revenue"] or 0
        purchases = r["total_purchases"] or 0
        impressions = r["total_impressions"] or 0
        clicks = r["total_clicks"] or 0

        results.append({
            "ad_type": r["ad_type"],
            "count": r["count"],
            "total_spend": round(spend, 0),
            "avg_roas": round(revenue / spend, 2) if spend > 0 else None,
            "avg_cpa": round(spend / purchases, 0) if purchases > 0 else None,
            "avg_ctr": round(clicks / impressions * 100, 2) if impressions > 0 else None,
            "avg_hook_rate": round(r["avg_hook_rate"], 1) if r["avg_hook_rate"] else None,
            "avg_hold_rate": round(r["avg_hold_rate"], 1) if r["avg_hold_rate"] else None,
            "total_revenue": round(revenue, 0),
            "total_purchases": purchases,
        })
    return results


# ══════════════════════════════════════════════════════
# VISUAL FORMAT COMPARISON
# ══════════════════════════════════════════════════════

def compare_visual_formats(conn, days=14):
    """Compare performance by visual format tag.

    Requires creative_tags to be populated first.

    Returns:
        list of {visual_format, count, total_spend, avg_roas, avg_cpa, winning_rate}
    """
    if not _has_table(conn, "creative_tags"):
        return []

    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    rows = conn.execute("""
        SELECT
            ct.visual_format,
            COUNT(DISTINCT s.ad_id) as count,
            SUM(s.spend) as total_spend,
            SUM(s.revenue) as total_revenue,
            SUM(s.purchases) as total_purchases,
            SUM(s.impressions) as total_impressions,
            SUM(s.clicks) as total_clicks,
            AVG(s.hook_rate) as avg_hook_rate
        FROM ad_daily_snapshots s
        INNER JOIN creative_tags ct ON s.ad_id = ct.ad_id
        WHERE s.snapshot_date >= ? AND ct.visual_format IS NOT NULL
        GROUP BY ct.visual_format
        HAVING total_spend > 0
        ORDER BY total_spend DESC
    """, (since,)).fetchall()

    # Calculate overall avg ROAS for winning_rate
    total_rev = sum(r["total_revenue"] or 0 for r in rows)
    total_sp = sum(r["total_spend"] or 0 for r in rows)
    overall_roas = total_rev / total_sp if total_sp > 0 else 2.0

    results = []
    for r in rows:
        spend = r["total_spend"] or 0
        revenue = r["total_revenue"] or 0
        purchases = r["total_purchases"] or 0
        impressions = r["total_impressions"] or 0
        clicks = r["total_clicks"] or 0
        roas = revenue / spend if spend > 0 else None

        results.append({
            "visual_format": r["visual_format"],
            "count": r["count"],
            "total_spend": round(spend, 0),
            "avg_roas": round(roas, 2) if roas else None,
            "avg_cpa": round(spend / purchases, 0) if purchases > 0 else None,
            "avg_ctr": round(clicks / impressions * 100, 2) if impressions > 0 else None,
            "avg_hook_rate": round(r["avg_hook_rate"], 1) if r["avg_hook_rate"] else None,
            "vs_average": round(((roas - overall_roas) / overall_roas) * 100, 0) if roas and overall_roas else None,
        })
    return results


# ══════════════════════════════════════════════════════
# MESSAGING ANGLE COMPARISON
# ══════════════════════════════════════════════════════

def compare_messaging_angles(conn, days=14):
    """Compare performance by messaging angle tag.

    Returns:
        list of {messaging_angle, count, total_spend, avg_roas, avg_cpa}
    """
    if not _has_table(conn, "creative_tags"):
        return []

    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    rows = conn.execute("""
        SELECT
            ct.messaging_angle,
            COUNT(DISTINCT s.ad_id) as count,
            SUM(s.spend) as total_spend,
            SUM(s.revenue) as total_revenue,
            SUM(s.purchases) as total_purchases
        FROM ad_daily_snapshots s
        INNER JOIN creative_tags ct ON s.ad_id = ct.ad_id
        WHERE s.snapshot_date >= ? AND ct.messaging_angle IS NOT NULL
        GROUP BY ct.messaging_angle
        HAVING total_spend > 0
        ORDER BY total_spend DESC
    """, (since,)).fetchall()

    results = []
    for r in rows:
        spend = r["total_spend"] or 0
        revenue = r["total_revenue"] or 0
        purchases = r["total_purchases"] or 0
        roas = revenue / spend if spend > 0 else None

        results.append({
            "messaging_angle": r["messaging_angle"],
            "count": r["count"],
            "total_spend": round(spend, 0),
            "avg_roas": round(roas, 2) if roas else None,
            "avg_cpa": round(spend / purchases, 0) if purchases > 0 else None,
        })
    return results


# ══════════════════════════════════════════════════════
# AD LENGTH COMPARISON (video only)
# ══════════════════════════════════════════════════════

# Buckets for video length comparison
LENGTH_BUCKETS = [
    ("0-6s", 0, 6),
    ("6-15s", 6, 15),
    ("15-30s", 15, 30),
    ("30-60s", 30, 60),
    ("60s+", 60, 9999),
]


def compare_ad_lengths(conn, days=14):
    """Compare video ad performance by duration.

    Uses component library (decomposition) for video duration data.

    Returns:
        list of {bucket, count, total_spend, avg_roas, avg_hook_rate, avg_hold_rate}
    """
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    # Get video durations from components table
    durations = {}
    try:
        dur_rows = conn.execute("""
            SELECT ad_id, MAX(end_time) as duration
            FROM components
            WHERE component_type = 'cta'
            GROUP BY ad_id
        """).fetchall()
        for r in dur_rows:
            durations[r["ad_id"]] = r["duration"]
    except Exception:
        pass  # components table might not exist yet

    if not durations:
        return []

    # Get performance per ad
    perf_rows = conn.execute("""
        SELECT ad_id, SUM(spend) as spend, SUM(revenue) as revenue,
               SUM(purchases) as purchases, AVG(hook_rate) as hook_rate,
               AVG(hold_rate) as hold_rate
        FROM ad_daily_snapshots
        WHERE snapshot_date >= ? AND hook_rate IS NOT NULL
        GROUP BY ad_id
    """, (since,)).fetchall()

    # Bucket
    buckets = {name: {"count": 0, "spend": 0, "revenue": 0, "purchases": 0,
                       "hook_rates": [], "hold_rates": []}
               for name, _, _ in LENGTH_BUCKETS}

    for r in perf_rows:
        dur = durations.get(r["ad_id"])
        if dur is None:
            continue

        for name, lo, hi in LENGTH_BUCKETS:
            if lo <= dur < hi:
                b = buckets[name]
                b["count"] += 1
                b["spend"] += r["spend"] or 0
                b["revenue"] += r["revenue"] or 0
                b["purchases"] += r["purchases"] or 0
                if r["hook_rate"]:
                    b["hook_rates"].append(r["hook_rate"])
                if r["hold_rate"]:
                    b["hold_rates"].append(r["hold_rate"])
                break

    results = []
    for name, _, _ in LENGTH_BUCKETS:
        b = buckets[name]
        if b["count"] == 0:
            continue
        results.append({
            "bucket": name,
            "count": b["count"],
            "total_spend": round(b["spend"], 0),
            "avg_roas": round(b["revenue"] / b["spend"], 2) if b["spend"] > 0 else None,
            "avg_cpa": round(b["spend"] / b["purchases"], 0) if b["purchases"] > 0 else None,
            "avg_hook_rate": round(sum(b["hook_rates"]) / len(b["hook_rates"]), 1) if b["hook_rates"] else None,
            "avg_hold_rate": round(sum(b["hold_rates"]) / len(b["hold_rates"]), 1) if b["hold_rates"] else None,
        })
    return results


# ══════════════════════════════════════════════════════
# TEXT REPORT
# ══════════════════════════════════════════════════════

def analyze_landing_pages(conn, days=14):
    """Compare ad performance by destination URL.

    Fetches destination URLs from Meta API and joins with snapshot performance.

    Returns:
        list of {landing_page, count, total_spend, avg_roas, avg_cpa}
    """
    import json
    from urllib.parse import urlparse
    from .meta_client import meta_fetch_all
    from .config import AD_ACCOUNT_ID

    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    # Step 1: Fetch destination URLs from Meta
    params = {
        "fields": "id,creative{object_story_spec}",
        "filtering": json.dumps([{
            "field": "effective_status", "operator": "IN",
            "value": ["ACTIVE", "PAUSED"]
        }]),
        "limit": "200",
    }
    try:
        ads = meta_fetch_all(f"{AD_ACCOUNT_ID}/ads", params, timeout=60)
    except Exception:
        return []

    url_map = {}  # ad_id -> landing page
    for ad in ads:
        creative = ad.get("creative", {})
        oss = creative.get("object_story_spec", {})
        link_data = oss.get("link_data", {})
        video_data = oss.get("video_data", {})
        url = (link_data.get("link")
               or video_data.get("call_to_action", {}).get("value", {}).get("link")
               or "")
        if url:
            # Normalize: strip query params, keep path
            parsed = urlparse(url)
            normalized = f"{parsed.netloc}{parsed.path}".rstrip("/")
            url_map[ad["id"]] = normalized

    if not url_map:
        return []

    # Step 2: Join with performance
    perf = conn.execute("""
        SELECT ad_id, SUM(spend) as spend, SUM(revenue) as revenue,
               SUM(purchases) as purchases
        FROM ad_daily_snapshots
        WHERE snapshot_date >= ?
        GROUP BY ad_id
        HAVING spend > 0
    """, (since,)).fetchall()

    # Aggregate by landing page
    from collections import defaultdict
    lp_data = defaultdict(lambda: {"count": 0, "spend": 0, "revenue": 0, "purchases": 0})
    for r in perf:
        lp = url_map.get(r["ad_id"])
        if not lp:
            continue
        d = lp_data[lp]
        d["count"] += 1
        d["spend"] += r["spend"] or 0
        d["revenue"] += r["revenue"] or 0
        d["purchases"] += r["purchases"] or 0

    results = []
    for lp, d in sorted(lp_data.items(), key=lambda x: x[1]["spend"], reverse=True):
        spend = d["spend"]
        revenue = d["revenue"]
        purchases = d["purchases"]
        results.append({
            "landing_page": lp,
            "count": d["count"],
            "total_spend": round(spend, 0),
            "avg_roas": round(revenue / spend, 2) if spend > 0 else None,
            "avg_cpa": round(spend / purchases, 0) if purchases > 0 else None,
            "total_purchases": purchases,
        })
    return results


def format_comparative_report(ad_types=None, visual_formats=None,
                               messaging_angles=None, ad_lengths=None,
                               landing_pages=None):
    """Format all comparative data as readable text."""
    lines = ["COMPARATIVE ANALYSIS", ""]

    if ad_types:
        lines.append("AD TYPE COMPARISON:")
        for t in ad_types:
            roas = f"ROAS {t['avg_roas']:.2f}" if t.get("avg_roas") else "no ROAS"
            lines.append(
                f"  {t['ad_type']}: {t['count']} ads, "
                f"{t['total_spend']:,.0f} CZK, {roas}"
            )
        lines.append("")

    if visual_formats:
        lines.append("VISUAL FORMAT BREAKDOWN:")
        for f in visual_formats[:8]:
            roas = f"ROAS {f['avg_roas']:.2f}" if f.get("avg_roas") else "N/A"
            vs = f" ({f['vs_average']:+.0f}% vs avg)" if f.get("vs_average") is not None else ""
            lines.append(f"  {f['visual_format']}: {roas}{vs} ({f['count']} ads)")
        lines.append("")

    if messaging_angles:
        lines.append("MESSAGING ANGLE BREAKDOWN:")
        for m in messaging_angles[:6]:
            roas = f"ROAS {m['avg_roas']:.2f}" if m.get("avg_roas") else "N/A"
            lines.append(f"  {m['messaging_angle']}: {roas} ({m['count']} ads)")
        lines.append("")

    if ad_lengths:
        lines.append("VIDEO LENGTH COMPARISON:")
        for l in ad_lengths:
            roas = f"ROAS {l['avg_roas']:.2f}" if l.get("avg_roas") else "N/A"
            hook = f"hook {l['avg_hook_rate']:.0f}%" if l.get("avg_hook_rate") else ""
            lines.append(f"  {l['bucket']}: {roas}, {hook} ({l['count']} ads)")
        lines.append("")

    if landing_pages:
        lines.append("LANDING PAGE ANALYSIS:")
        for lp in landing_pages[:8]:
            roas = f"ROAS {lp['avg_roas']:.2f}" if lp.get("avg_roas") else "N/A"
            lines.append(f"  {lp['landing_page'][:50]}: {roas}, {lp['total_spend']:,.0f} Kc ({lp['count']} ads)")
        lines.append("")

    return "\n".join(lines)
