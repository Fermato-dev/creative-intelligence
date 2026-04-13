"""Performance Shifts — automatic categorization of creative trends.

Inspired by Motion App's Scaling/Declining/Newly Launched/Recently Paused view.
Uses daily snapshots from change_tracker to detect WoW trends.
"""

import sqlite3
from datetime import datetime, timedelta


# ══════════════════════════════════════════════════════
# THRESHOLDS
# ══════════════════════════════════════════════════════

SCALING_SPEND_DELTA = 30     # spend +30% WoW AND ROAS not tanking
SCALING_ROAS_FLOOR = -10     # ROAS can drop max 10% and still count as scaling
DECLINING_SPEND_DELTA = -20  # spend -20% WoW
DECLINING_ROAS_DELTA = -20   # OR ROAS -20% WoW
NEW_LAUNCH_DAYS = 7          # first seen within last N days
PAUSED_DAYS = 7              # paused within last N days
MIN_SPEND_FOR_TREND = 200    # CZK — ignore low-spend ads


# ══════════════════════════════════════════════════════
# WOW DELTA CALCULATION
# ══════════════════════════════════════════════════════

def calculate_wow_deltas(conn, ad_id, reference_date=None):
    """Calculate week-over-week deltas for a single ad.

    Compares last 7 days vs previous 7 days.

    Returns:
        dict with {spend_delta, roas_delta, cpa_delta, ctr_delta, ...} as percentages,
        plus {this_week_spend, last_week_spend, ...} absolutes.
        Returns None if insufficient data.
    """
    if reference_date is None:
        reference_date = datetime.now().strftime("%Y-%m-%d")

    ref = datetime.strptime(reference_date, "%Y-%m-%d")
    this_week_start = (ref - timedelta(days=6)).strftime("%Y-%m-%d")
    last_week_start = (ref - timedelta(days=13)).strftime("%Y-%m-%d")
    last_week_end = (ref - timedelta(days=7)).strftime("%Y-%m-%d")

    def _sum_period(start, end):
        row = conn.execute("""
            SELECT SUM(spend) as spend, SUM(revenue) as revenue,
                   SUM(purchases) as purchases, SUM(impressions) as impressions,
                   SUM(clicks) as clicks, AVG(hook_rate) as hook_rate,
                   AVG(hold_rate) as hold_rate, COUNT(*) as days
            FROM ad_daily_snapshots
            WHERE ad_id = ? AND snapshot_date BETWEEN ? AND ?
        """, (ad_id, start, end)).fetchone()
        if not row or not row["days"]:
            return None
        spend = row["spend"] or 0
        revenue = row["revenue"] or 0
        purchases = row["purchases"] or 0
        impressions = row["impressions"] or 0
        clicks = row["clicks"] or 0
        return {
            "spend": spend, "revenue": revenue,
            "purchases": purchases, "impressions": impressions,
            "clicks": clicks,
            "roas": revenue / spend if spend > 0 else None,
            "cpa": spend / purchases if purchases > 0 else None,
            "ctr": (clicks / impressions * 100) if impressions > 0 else None,
            "hook_rate": row["hook_rate"],
            "hold_rate": row["hold_rate"],
            "days": row["days"],
        }

    this_week = _sum_period(this_week_start, reference_date)
    last_week = _sum_period(last_week_start, last_week_end)

    if not this_week or not last_week:
        return None

    def _pct_delta(current, previous):
        if previous is not None and previous > 0 and current is not None:
            return round(((current - previous) / previous) * 100, 1)
        return None

    return {
        "this_week_spend": this_week["spend"],
        "last_week_spend": last_week["spend"],
        "this_week_roas": this_week["roas"],
        "last_week_roas": last_week["roas"],
        "this_week_cpa": this_week["cpa"],
        "last_week_cpa": last_week["cpa"],
        "this_week_ctr": this_week["ctr"],
        "last_week_ctr": last_week["ctr"],
        "this_week_purchases": this_week["purchases"],
        "last_week_purchases": last_week["purchases"],
        "spend_delta": _pct_delta(this_week["spend"], last_week["spend"]),
        "roas_delta": _pct_delta(this_week["roas"], last_week["roas"]),
        "cpa_delta": _pct_delta(this_week["cpa"], last_week["cpa"]),
        "ctr_delta": _pct_delta(this_week["ctr"], last_week["ctr"]),
        "hook_rate_delta": _pct_delta(this_week["hook_rate"], last_week["hook_rate"]),
        "hold_rate_delta": _pct_delta(this_week["hold_rate"], last_week["hold_rate"]),
    }


# ══════════════════════════════════════════════════════
# PERFORMANCE SHIFT CATEGORIZATION
# ══════════════════════════════════════════════════════

def categorize_performance_shifts(conn, reference_date=None):
    """Categorize all ads into performance shift buckets.

    Returns:
        {
            "scaling": [{"ad_id", "ad_name", "spend_delta", "roas_delta", ...}],
            "declining": [...],
            "newly_launched": [...],
            "recently_paused": [...],
            "summary": {"total_spend", "total_spend_delta", "avg_roas", "avg_roas_delta",
                        "creatives_launched", "creatives_paused"}
        }
    """
    if reference_date is None:
        reference_date = datetime.now().strftime("%Y-%m-%d")

    ref = datetime.strptime(reference_date, "%Y-%m-%d")

    # Get all unique ads from last 14 days
    two_weeks_ago = (ref - timedelta(days=13)).strftime("%Y-%m-%d")
    rows = conn.execute("""
        SELECT DISTINCT ad_id, ad_name, campaign_name,
               MIN(snapshot_date) as first_seen,
               MAX(snapshot_date) as last_seen
        FROM ad_daily_snapshots
        WHERE snapshot_date BETWEEN ? AND ?
        GROUP BY ad_id
    """, (two_weeks_ago, reference_date)).fetchall()

    scaling = []
    declining = []
    newly_launched = []
    recently_paused = []

    for row in rows:
        ad_id = row["ad_id"]
        ad_name = row["ad_name"] or ad_id
        campaign = row["campaign_name"] or ""
        first_seen = row["first_seen"]
        last_seen = row["last_seen"]

        # Check: newly launched (first seen within last N days)
        first_seen_dt = datetime.strptime(first_seen, "%Y-%m-%d")
        launch_days = (ref - first_seen_dt).days
        if launch_days <= NEW_LAUNCH_DAYS:
            # Get current metrics
            latest = conn.execute("""
                SELECT spend, roas, cpa, hook_rate
                FROM ad_daily_snapshots
                WHERE ad_id = ? AND snapshot_date = ?
            """, (ad_id, last_seen)).fetchone()

            newly_launched.append({
                "ad_id": ad_id, "ad_name": ad_name,
                "campaign_name": campaign,
                "days_since_launch": launch_days,
                "spend": latest["spend"] if latest else 0,
                "roas": latest["roas"] if latest else None,
            })
            continue

        # Check: recently paused
        last_seen_dt = datetime.strptime(last_seen, "%Y-%m-%d")
        days_since_seen = (ref - last_seen_dt).days
        if days_since_seen >= 2:
            # Not seen in last 2 days = likely paused
            recent_paused_check = conn.execute("""
                SELECT effective_status FROM ad_daily_snapshots
                WHERE ad_id = ? ORDER BY snapshot_date DESC LIMIT 1
            """, (ad_id,)).fetchone()

            status = recent_paused_check["effective_status"] if recent_paused_check else "UNKNOWN"
            if status != "ACTIVE" or days_since_seen >= 2:
                # Get last known metrics
                last_metrics = conn.execute("""
                    SELECT spend, roas, cpa FROM ad_daily_snapshots
                    WHERE ad_id = ? ORDER BY snapshot_date DESC LIMIT 1
                """, (ad_id,)).fetchone()

                recently_paused.append({
                    "ad_id": ad_id, "ad_name": ad_name,
                    "campaign_name": campaign,
                    "days_since_seen": days_since_seen,
                    "last_status": status,
                    "last_spend": last_metrics["spend"] if last_metrics else 0,
                    "last_roas": last_metrics["roas"] if last_metrics else None,
                })
                continue

        # Calculate WoW deltas for active ads
        deltas = calculate_wow_deltas(conn, ad_id, reference_date)
        if not deltas:
            continue

        # Skip low-spend ads
        if deltas["this_week_spend"] < MIN_SPEND_FOR_TREND:
            continue

        entry = {
            "ad_id": ad_id, "ad_name": ad_name,
            "campaign_name": campaign,
            **deltas,
        }

        # Categorize
        spend_d = deltas.get("spend_delta")
        roas_d = deltas.get("roas_delta")

        if spend_d is not None and spend_d >= SCALING_SPEND_DELTA:
            if roas_d is None or roas_d >= SCALING_ROAS_FLOOR:
                scaling.append(entry)
                continue

        if (spend_d is not None and spend_d <= DECLINING_SPEND_DELTA) or \
           (roas_d is not None and roas_d <= DECLINING_ROAS_DELTA):
            declining.append(entry)
            continue

    # Sort
    scaling.sort(key=lambda x: x.get("spend_delta") or 0, reverse=True)
    declining.sort(key=lambda x: x.get("roas_delta") or 0)
    newly_launched.sort(key=lambda x: x.get("spend") or 0, reverse=True)
    recently_paused.sort(key=lambda x: x.get("days_since_seen") or 0)

    # Summary metrics
    this_week_start = (ref - timedelta(days=6)).strftime("%Y-%m-%d")
    last_week_start = (ref - timedelta(days=13)).strftime("%Y-%m-%d")
    last_week_end = (ref - timedelta(days=7)).strftime("%Y-%m-%d")

    tw_agg = conn.execute("""
        SELECT SUM(spend) as spend, SUM(revenue) as revenue,
               SUM(purchases) as purchases
        FROM ad_daily_snapshots
        WHERE snapshot_date BETWEEN ? AND ?
    """, (this_week_start, reference_date)).fetchone()

    lw_agg = conn.execute("""
        SELECT SUM(spend) as spend, SUM(revenue) as revenue,
               SUM(purchases) as purchases
        FROM ad_daily_snapshots
        WHERE snapshot_date BETWEEN ? AND ?
    """, (last_week_start, last_week_end)).fetchone()

    tw_spend = tw_agg["spend"] or 0 if tw_agg else 0
    lw_spend = lw_agg["spend"] or 0 if lw_agg else 0
    tw_revenue = tw_agg["revenue"] or 0 if tw_agg else 0
    lw_revenue = lw_agg["revenue"] or 0 if lw_agg else 0

    spend_delta = round(((tw_spend - lw_spend) / lw_spend) * 100, 1) if lw_spend > 0 else None
    tw_roas = tw_revenue / tw_spend if tw_spend > 0 else None
    lw_roas = lw_revenue / lw_spend if lw_spend > 0 else None
    roas_delta = round(((tw_roas - lw_roas) / lw_roas) * 100, 1) if lw_roas and lw_roas > 0 else None

    return {
        "scaling": scaling,
        "declining": declining,
        "newly_launched": newly_launched,
        "recently_paused": recently_paused,
        "summary": {
            "total_spend": round(tw_spend, 0),
            "total_spend_delta": spend_delta,
            "avg_roas": round(tw_roas, 2) if tw_roas else None,
            "avg_roas_delta": roas_delta,
            "creatives_launched": len(newly_launched),
            "creatives_paused": len(recently_paused),
            "creatives_scaling": len(scaling),
            "creatives_declining": len(declining),
        },
    }


# ══════════════════════════════════════════════════════
# TEXT REPORT
# ══════════════════════════════════════════════════════

def format_shifts_report(shifts):
    """Format performance shifts as readable text for Pumble/reports."""
    s = shifts["summary"]
    lines = [
        "PERFORMANCE SHIFTS",
        "",
        f"Spend: {s['total_spend']:,.0f} CZK ({_fmt_delta(s['total_spend_delta'])})",
        f"ROAS: {s['avg_roas']:.2f} ({_fmt_delta(s['avg_roas_delta'])})" if s['avg_roas'] else "",
        f"Launched: {s['creatives_launched']} | Paused: {s['creatives_paused']}",
        "",
    ]

    if shifts["scaling"]:
        lines.append(f"SCALING ({len(shifts['scaling'])})")
        for ad in shifts["scaling"][:5]:
            lines.append(
                f"  {ad['ad_name'][:40]}: "
                f"spend {_fmt_delta(ad.get('spend_delta'))}, "
                f"ROAS {ad.get('this_week_roas', 0):.2f} ({_fmt_delta(ad.get('roas_delta'))})"
            )
        lines.append("")

    if shifts["declining"]:
        lines.append(f"DECLINING ({len(shifts['declining'])})")
        for ad in shifts["declining"][:5]:
            lines.append(
                f"  {ad['ad_name'][:40]}: "
                f"spend {_fmt_delta(ad.get('spend_delta'))}, "
                f"ROAS {ad.get('this_week_roas', 0):.2f} ({_fmt_delta(ad.get('roas_delta'))})"
            )
        lines.append("")

    if shifts["newly_launched"]:
        lines.append(f"NEWLY LAUNCHED ({len(shifts['newly_launched'])})")
        for ad in shifts["newly_launched"][:5]:
            roas_str = f"ROAS {ad['roas']:.2f}" if ad.get("roas") else "no conversions yet"
            lines.append(
                f"  {ad['ad_name'][:40]}: "
                f"{ad.get('days_since_launch', '?')}d, "
                f"spend {ad.get('spend', 0):,.0f} CZK, {roas_str}"
            )
        lines.append("")

    return "\n".join(lines)


def _fmt_delta(val):
    """Format a percentage delta with + or - sign."""
    if val is None:
        return "N/A"
    sign = "+" if val >= 0 else ""
    return f"{sign}{val:.0f}%"
