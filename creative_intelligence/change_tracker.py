"""Change Tracker — daily ad snapshots, change detection, lift measurement.

Tracks what changes happen in Meta Ads (spend, status, creative, budget)
and measures their before/after impact (lift).
"""

import json
import sqlite3
import sys
from datetime import datetime, timedelta

from .config import AD_ACCOUNT_ID, TARGET_ROAS
from .meta_client import meta_fetch, meta_fetch_all


# ══════════════════════════════════════════════════════
# SCHEMA
# ══════════════════════════════════════════════════════

CHANGE_TRACKING_SCHEMA = """
CREATE TABLE IF NOT EXISTS ad_daily_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date TEXT NOT NULL,
    ad_id TEXT NOT NULL,
    ad_name TEXT,
    campaign_id TEXT,
    campaign_name TEXT,
    adset_id TEXT,
    adset_name TEXT,
    effective_status TEXT,
    creative_id TEXT,
    daily_budget REAL,
    optimization_goal TEXT,
    impressions INTEGER DEFAULT 0,
    reach INTEGER DEFAULT 0,
    clicks INTEGER DEFAULT 0,
    spend REAL DEFAULT 0,
    purchases INTEGER DEFAULT 0,
    revenue REAL DEFAULT 0,
    ctr REAL,
    cpm REAL,
    cpa REAL,
    roas REAL,
    frequency REAL,
    video_thruplay INTEGER DEFAULT 0,
    hook_rate REAL,
    hold_rate REAL,
    fetched_at TEXT NOT NULL,
    UNIQUE(snapshot_date, ad_id)
);
CREATE INDEX IF NOT EXISTS idx_snap_date ON ad_daily_snapshots(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_snap_ad ON ad_daily_snapshots(ad_id);
CREATE INDEX IF NOT EXISTS idx_snap_ad_date ON ad_daily_snapshots(ad_id, snapshot_date);

CREATE TABLE IF NOT EXISTS change_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    detected_date TEXT NOT NULL,
    ad_id TEXT NOT NULL,
    ad_name TEXT,
    campaign_id TEXT,
    campaign_name TEXT,
    change_type TEXT NOT NULL,
    change_category TEXT NOT NULL,
    field_changed TEXT,
    old_value TEXT,
    new_value TEXT,
    change_magnitude REAL,
    spend_at_change REAL,
    roas_at_change REAL,
    lift_status TEXT DEFAULT 'pending',
    pre_window_start TEXT,
    pre_window_end TEXT,
    post_window_start TEXT,
    post_window_end TEXT,
    pre_spend REAL, pre_revenue REAL, pre_roas REAL, pre_cpa REAL,
    pre_purchases INTEGER, pre_impressions INTEGER, pre_hook_rate REAL,
    post_spend REAL, post_revenue REAL, post_roas REAL, post_cpa REAL,
    post_purchases INTEGER, post_impressions INTEGER, post_hook_rate REAL,
    roas_lift REAL, cpa_lift REAL, spend_lift REAL, revenue_lift REAL,
    confidence_score REAL,
    verdict TEXT,
    created_at TEXT NOT NULL,
    measured_at TEXT,
    notes TEXT,
    UNIQUE(detected_date, ad_id, change_type, field_changed)
);
CREATE INDEX IF NOT EXISTS idx_ce_date ON change_events(detected_date);
CREATE INDEX IF NOT EXISTS idx_ce_type ON change_events(change_type);
CREATE INDEX IF NOT EXISTS idx_ce_verdict ON change_events(verdict);

CREATE TABLE IF NOT EXISTS learnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    learning_type TEXT NOT NULL,
    change_type TEXT,
    description TEXT NOT NULL,
    evidence_json TEXT,
    sample_size INTEGER,
    avg_roas_lift REAL,
    avg_cpa_lift REAL,
    confidence TEXT,
    generated_at TEXT NOT NULL,
    status TEXT DEFAULT 'active',
    UNIQUE(learning_type, change_type, description)
);
"""


def init_change_tracking_schema(conn):
    """Create change tracking tables if missing."""
    conn.executescript(CHANGE_TRACKING_SCHEMA)
    conn.commit()


# ══════════════════════════════════════════════════════
# DATA COLLECTION
# ══════════════════════════════════════════════════════

INSIGHTS_FIELDS = ",".join([
    "ad_id", "ad_name", "campaign_id", "campaign_name",
    "adset_id", "adset_name",
    "impressions", "reach", "clicks", "spend", "ctr", "cpm", "frequency",
    "actions", "action_values", "purchase_roas",
    "video_thruplay_watched_actions",
    "video_p25_watched_actions",
])


def fetch_daily_snapshots(date_str):
    """Fetch daily ad insights from Meta API with time_increment=1.

    Returns list of dicts, one per ad for the given date.
    """
    params = {
        "fields": INSIGHTS_FIELDS,
        "level": "ad",
        "time_range": json.dumps({"since": date_str, "until": date_str}),
        "time_increment": "1",
        "limit": "200",
        "filtering": json.dumps([{
            "field": "impressions", "operator": "GREATER_THAN", "value": "0"
        }]),
    }
    return meta_fetch_all(f"{AD_ACCOUNT_ID}/insights", params, timeout=60)


def fetch_ad_states():
    """Fetch current state of all ads (status, creative, budget).

    Returns list of dicts.
    """
    params = {
        "fields": ",".join([
            "id", "name", "effective_status",
            "creative{id}",
            "adset{id,name,daily_budget,optimization_goal}",
            "campaign_id",
        ]),
        "limit": "200",
    }
    return meta_fetch_all(f"{AD_ACCOUNT_ID}/ads", params, timeout=60)


def _extract_actions(actions_list, action_type):
    """Extract a specific action value from Meta actions array."""
    if not actions_list:
        return 0
    for a in actions_list:
        if a.get("action_type") == action_type:
            return int(a.get("value", 0))
    return 0


def _extract_action_values(values_list, action_type):
    """Extract a specific action monetary value."""
    if not values_list:
        return 0.0
    for a in values_list:
        if a.get("action_type") == action_type:
            return float(a.get("value", 0))
    return 0.0


def save_daily_snapshots(conn, insights, ad_states, date_str):
    """Save daily snapshots to DB.

    Merges insights (performance) with ad_states (status/creative/budget).
    """
    # Build state lookup by ad_id
    state_map = {}
    for ad in ad_states:
        ad_id = ad.get("id", "")
        creative = ad.get("creative", {})
        adset = ad.get("adset", {})
        state_map[ad_id] = {
            "effective_status": ad.get("effective_status"),
            "creative_id": creative.get("id") if creative else None,
            "daily_budget": float(adset.get("daily_budget", 0)) / 100 if adset.get("daily_budget") else None,
            "optimization_goal": adset.get("optimization_goal"),
            "adset_id": adset.get("id") if adset else None,
            "adset_name": adset.get("name") if adset else None,
        }

    now = datetime.now().isoformat()
    saved = 0

    for row in insights:
        ad_id = row.get("ad_id", "")
        state = state_map.get(ad_id, {})

        spend = float(row.get("spend", 0))
        purchases = _extract_actions(row.get("actions"), "purchase")
        revenue = _extract_action_values(row.get("action_values"), "purchase")
        impressions = int(row.get("impressions", 0))
        clicks = int(row.get("clicks", 0))

        roas = revenue / spend if spend > 0 else None
        cpa = spend / purchases if purchases > 0 else None

        # Video metrics
        video_3s = _extract_actions(row.get("video_p25_watched_actions"), "video_view")
        video_thruplay = _extract_actions(row.get("video_thruplay_watched_actions"), "video_view")
        hook_rate = (video_3s / impressions * 100) if impressions > 0 and video_3s else None
        hold_rate = (video_thruplay / video_3s * 100) if video_3s > 0 and video_thruplay else None

        try:
            conn.execute("""
                INSERT OR REPLACE INTO ad_daily_snapshots (
                    snapshot_date, ad_id, ad_name, campaign_id, campaign_name,
                    adset_id, adset_name, effective_status, creative_id,
                    daily_budget, optimization_goal,
                    impressions, reach, clicks, spend, purchases, revenue,
                    ctr, cpm, cpa, roas, frequency,
                    video_thruplay, hook_rate, hold_rate, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                date_str, ad_id, row.get("ad_name"), row.get("campaign_id"), row.get("campaign_name"),
                state.get("adset_id") or row.get("adset_id"),
                state.get("adset_name") or row.get("adset_name"),
                state.get("effective_status"), state.get("creative_id"),
                state.get("daily_budget"), state.get("optimization_goal"),
                impressions, int(row.get("reach", 0)), clicks, spend, purchases, revenue,
                float(row.get("ctr", 0)), float(row.get("cpm", 0)),
                cpa, roas, float(row.get("frequency", 0)),
                video_thruplay, hook_rate, hold_rate, now,
            ))
            saved += 1
        except Exception as e:
            print(f"  WARN: save snapshot {ad_id}: {e}", file=sys.stderr)

    conn.commit()
    return saved


# ══════════════════════════════════════════════════════
# CHANGE DETECTION
# ══════════════════════════════════════════════════════

MIN_BUDGET_CHANGE = 50      # CZK — ignore tiny budget changes
MIN_SPEND_FOR_ANOMALY = 100  # CZK/day avg — ignore low-spend ads
MIN_DAYS_FOR_ANOMALY = 5     # need N days of history for spike/drop detection
SPEND_SPIKE_FACTOR = 1.5
SPEND_DROP_FACTOR = 0.5


def detect_changes(conn, date_str):
    """Detect changes by comparing today's snapshots with yesterday's.

    Returns number of change events created.
    """
    yesterday = (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    now = datetime.now().isoformat()

    # Load today and yesterday
    today_ads = {r["ad_id"]: dict(r) for r in conn.execute(
        "SELECT * FROM ad_daily_snapshots WHERE snapshot_date = ?", (date_str,)).fetchall()}
    yesterday_ads = {r["ad_id"]: dict(r) for r in conn.execute(
        "SELECT * FROM ad_daily_snapshots WHERE snapshot_date = ?", (yesterday,)).fetchall()}

    changes = []

    for ad_id, today in today_ads.items():
        prev = yesterday_ads.get(ad_id)

        # NEW_AD
        if prev is None:
            if today.get("spend", 0) > 0:
                changes.append(_make_event(today, date_str, "NEW_AD", "manual",
                                           "ad_id", None, ad_id, None, now))
            continue

        # STATUS_CHANGE
        if today.get("effective_status") != prev.get("effective_status"):
            old_status = prev.get("effective_status")
            new_status = today.get("effective_status")
            ct = "AD_STOPPED" if new_status in ("PAUSED", "ARCHIVED") and old_status == "ACTIVE" else "STATUS_CHANGE"
            changes.append(_make_event(today, date_str, ct, "manual",
                                       "effective_status", old_status, new_status, None, now))

        # CREATIVE_SWAP
        if (today.get("creative_id") and prev.get("creative_id")
                and today["creative_id"] != prev["creative_id"]):
            changes.append(_make_event(today, date_str, "CREATIVE_SWAP", "manual",
                                       "creative_id", prev["creative_id"], today["creative_id"], None, now))

        # BUDGET_CHANGE
        old_budget = prev.get("daily_budget") or 0
        new_budget = today.get("daily_budget") or 0
        if old_budget > 0 and abs(new_budget - old_budget) >= MIN_BUDGET_CHANGE:
            mag = ((new_budget - old_budget) / old_budget) * 100
            changes.append(_make_event(today, date_str, "BUDGET_CHANGE", "manual",
                                       "daily_budget", str(old_budget), str(new_budget), mag, now))

    # SPEND_SPIKE / SPEND_DROP — needs 7-day average
    for ad_id, today in today_ads.items():
        avg_row = conn.execute("""
            SELECT AVG(spend) as avg_spend, COUNT(*) as days
            FROM ad_daily_snapshots
            WHERE ad_id = ? AND snapshot_date BETWEEN date(?, '-8 days') AND date(?, '-1 day')
        """, (ad_id, date_str, date_str)).fetchone()

        avg_spend = avg_row["avg_spend"] if avg_row and avg_row["avg_spend"] else 0
        days = avg_row["days"] if avg_row else 0
        today_spend = today.get("spend", 0)

        if days < MIN_DAYS_FOR_ANOMALY or avg_spend < MIN_SPEND_FOR_ANOMALY:
            continue

        if today_spend > avg_spend * SPEND_SPIKE_FACTOR:
            mag = ((today_spend / avg_spend) - 1) * 100
            changes.append(_make_event(today, date_str, "SPEND_SPIKE", "algorithmic",
                                       "spend", f"{avg_spend:.0f}", f"{today_spend:.0f}", mag, now))
        elif today_spend > 0 and today_spend < avg_spend * SPEND_DROP_FACTOR:
            mag = (1 - today_spend / avg_spend) * 100
            changes.append(_make_event(today, date_str, "SPEND_DROP", "algorithmic",
                                       "spend", f"{avg_spend:.0f}", f"{today_spend:.0f}", -mag, now))

    # AD_STOPPED — ads in yesterday but not today (or spend=0 + status change)
    for ad_id, prev in yesterday_ads.items():
        if ad_id not in today_ads and prev.get("effective_status") == "ACTIVE":
            changes.append({
                "detected_date": date_str, "ad_id": ad_id,
                "ad_name": prev.get("ad_name"), "campaign_id": prev.get("campaign_id"),
                "campaign_name": prev.get("campaign_name"),
                "change_type": "AD_STOPPED", "change_category": "manual",
                "field_changed": "effective_status", "old_value": "ACTIVE", "new_value": "DISAPPEARED",
                "change_magnitude": None,
                "spend_at_change": prev.get("spend"), "roas_at_change": prev.get("roas"),
                "created_at": now,
            })

    # Save
    saved = 0
    for ch in changes:
        try:
            conn.execute("""
                INSERT OR IGNORE INTO change_events (
                    detected_date, ad_id, ad_name, campaign_id, campaign_name,
                    change_type, change_category, field_changed, old_value, new_value,
                    change_magnitude, spend_at_change, roas_at_change, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ch["detected_date"], ch["ad_id"], ch.get("ad_name"),
                ch.get("campaign_id"), ch.get("campaign_name"),
                ch["change_type"], ch["change_category"],
                ch.get("field_changed"), ch.get("old_value"), ch.get("new_value"),
                ch.get("change_magnitude"), ch.get("spend_at_change"), ch.get("roas_at_change"),
                ch["created_at"],
            ))
            saved += 1
        except Exception as e:
            print(f"  WARN: save change {ch.get('ad_id')}/{ch.get('change_type')}: {e}", file=sys.stderr)

    conn.commit()
    return saved


def _make_event(today, date_str, change_type, category, field, old_val, new_val, magnitude, now):
    return {
        "detected_date": date_str, "ad_id": today.get("ad_id"),
        "ad_name": today.get("ad_name"), "campaign_id": today.get("campaign_id"),
        "campaign_name": today.get("campaign_name"),
        "change_type": change_type, "change_category": category,
        "field_changed": field, "old_value": str(old_val) if old_val is not None else None,
        "new_value": str(new_val) if new_val is not None else None,
        "change_magnitude": magnitude,
        "spend_at_change": today.get("spend"), "roas_at_change": today.get("roas"),
        "created_at": now,
    }


# ══════════════════════════════════════════════════════
# LIFT MEASUREMENT
# ══════════════════════════════════════════════════════

PRE_WINDOW_DAYS = 7
POST_WINDOW_DAYS = 7
COOLDOWN_DAYS = 1
MIN_DAYS_SINCE_CHANGE = PRE_WINDOW_DAYS + COOLDOWN_DAYS + POST_WINDOW_DAYS  # 15


def measure_lift(conn):
    """Calculate lift for all pending change events with enough elapsed time."""
    cutoff = (datetime.now() - timedelta(days=COOLDOWN_DAYS + POST_WINDOW_DAYS)).strftime("%Y-%m-%d")

    pending = conn.execute("""
        SELECT * FROM change_events
        WHERE lift_status = 'pending' AND detected_date <= ?
    """, (cutoff,)).fetchall()

    measured = 0
    for event in pending:
        event = dict(event)
        result = _calculate_lift(conn, event)
        if result:
            conn.execute("""
                UPDATE change_events SET
                    lift_status = ?, pre_window_start = ?, pre_window_end = ?,
                    post_window_start = ?, post_window_end = ?,
                    pre_spend = ?, pre_revenue = ?, pre_roas = ?, pre_cpa = ?,
                    pre_purchases = ?, pre_impressions = ?, pre_hook_rate = ?,
                    post_spend = ?, post_revenue = ?, post_roas = ?, post_cpa = ?,
                    post_purchases = ?, post_impressions = ?, post_hook_rate = ?,
                    roas_lift = ?, cpa_lift = ?, spend_lift = ?, revenue_lift = ?,
                    confidence_score = ?, verdict = ?, measured_at = ?
                WHERE id = ?
            """, (
                result["lift_status"], result["pre_start"], result["pre_end"],
                result["post_start"], result["post_end"],
                result["pre_spend"], result["pre_revenue"], result["pre_roas"], result["pre_cpa"],
                result["pre_purchases"], result["pre_impressions"], result.get("pre_hook_rate"),
                result["post_spend"], result["post_revenue"], result["post_roas"], result["post_cpa"],
                result["post_purchases"], result["post_impressions"], result.get("post_hook_rate"),
                result.get("roas_lift"), result.get("cpa_lift"),
                result.get("spend_lift"), result.get("revenue_lift"),
                result["confidence"], result["verdict"], datetime.now().isoformat(),
                event["id"],
            ))
            measured += 1

    conn.commit()
    return measured


def _calculate_lift(conn, event):
    """Calculate before/after lift for a single change event."""
    change_date = datetime.strptime(event["detected_date"], "%Y-%m-%d")
    ad_id = event["ad_id"]

    pre_start = (change_date - timedelta(days=PRE_WINDOW_DAYS + 1)).strftime("%Y-%m-%d")
    pre_end = (change_date - timedelta(days=1)).strftime("%Y-%m-%d")
    post_start = (change_date + timedelta(days=COOLDOWN_DAYS)).strftime("%Y-%m-%d")
    post_end = (change_date + timedelta(days=COOLDOWN_DAYS + POST_WINDOW_DAYS)).strftime("%Y-%m-%d")

    def _agg(start, end):
        row = conn.execute("""
            SELECT SUM(spend) as spend, SUM(revenue) as revenue,
                   SUM(purchases) as purchases, SUM(impressions) as impressions,
                   AVG(hook_rate) as hook_rate, COUNT(*) as days
            FROM ad_daily_snapshots
            WHERE ad_id = ? AND snapshot_date BETWEEN ? AND ?
        """, (ad_id, start, end)).fetchone()
        if not row or not row["days"]:
            return None
        spend = row["spend"] or 0
        revenue = row["revenue"] or 0
        purchases = row["purchases"] or 0
        return {
            "spend": spend, "revenue": revenue,
            "purchases": purchases, "impressions": row["impressions"] or 0,
            "roas": revenue / spend if spend > 0 else None,
            "cpa": spend / purchases if purchases > 0 else None,
            "hook_rate": row["hook_rate"], "days": row["days"],
        }

    pre = _agg(pre_start, pre_end)
    post = _agg(post_start, post_end)

    if not pre or not post:
        return {"lift_status": "insufficient_data", "pre_start": pre_start, "pre_end": pre_end,
                "post_start": post_start, "post_end": post_end,
                "pre_spend": 0, "pre_revenue": 0, "pre_roas": None, "pre_cpa": None,
                "pre_purchases": 0, "pre_impressions": 0,
                "post_spend": 0, "post_revenue": 0, "post_roas": None, "post_cpa": None,
                "post_purchases": 0, "post_impressions": 0,
                "confidence": 0, "verdict": "inconclusive"}

    # Lift calculations
    def _pct(post_val, pre_val):
        if pre_val and pre_val > 0 and post_val is not None:
            return ((post_val - pre_val) / pre_val) * 100
        return None

    roas_lift = _pct(post["roas"], pre["roas"])
    cpa_lift = _pct(post["cpa"], pre["cpa"])
    spend_lift = _pct(post["spend"], pre["spend"])
    revenue_lift = _pct(post["revenue"], pre["revenue"])

    # Confidence
    min_purchases = min(pre["purchases"], post["purchases"])
    min_spend = min(pre["spend"], post["spend"])
    conf = min(min_purchases / 10, 1.0) * 0.6 + min(min_spend / 3000, 1.0) * 0.4

    # Verdict
    if conf < 0.3:
        verdict = "inconclusive"
    elif roas_lift is not None and (roas_lift > 10 or (cpa_lift is not None and cpa_lift < -10)):
        verdict = "positive"
    elif roas_lift is not None and (roas_lift < -10 or (cpa_lift is not None and cpa_lift > 10)):
        verdict = "negative"
    else:
        verdict = "neutral"

    return {
        "lift_status": "measured",
        "pre_start": pre_start, "pre_end": pre_end,
        "post_start": post_start, "post_end": post_end,
        "pre_spend": pre["spend"], "pre_revenue": pre["revenue"],
        "pre_roas": pre["roas"], "pre_cpa": pre["cpa"],
        "pre_purchases": pre["purchases"], "pre_impressions": pre["impressions"],
        "pre_hook_rate": pre.get("hook_rate"),
        "post_spend": post["spend"], "post_revenue": post["revenue"],
        "post_roas": post["roas"], "post_cpa": post["cpa"],
        "post_purchases": post["purchases"], "post_impressions": post["impressions"],
        "post_hook_rate": post.get("hook_rate"),
        "roas_lift": roas_lift, "cpa_lift": cpa_lift,
        "spend_lift": spend_lift, "revenue_lift": revenue_lift,
        "confidence": round(conf, 2), "verdict": verdict,
    }


# ══════════════════════════════════════════════════════
# LEARNINGS
# ══════════════════════════════════════════════════════

def generate_learnings(conn):
    """Aggregate measured change events into learnings."""
    now = datetime.now().isoformat()
    generated = 0

    for change_type in ["BUDGET_CHANGE", "CREATIVE_SWAP", "STATUS_CHANGE",
                        "SPEND_SPIKE", "SPEND_DROP", "NEW_AD", "AD_STOPPED"]:
        events = [dict(r) for r in conn.execute("""
            SELECT * FROM change_events
            WHERE change_type = ? AND lift_status = 'measured' AND confidence_score >= 0.3
        """, (change_type,)).fetchall()]

        if len(events) < 3:
            continue

        positive = [e for e in events if e["verdict"] == "positive"]
        negative = [e for e in events if e["verdict"] == "negative"]

        roas_lifts = [e["roas_lift"] for e in events if e["roas_lift"] is not None]
        cpa_lifts = [e["cpa_lift"] for e in events if e["cpa_lift"] is not None]
        avg_roas = sum(roas_lifts) / len(roas_lifts) if roas_lifts else None
        avg_cpa = sum(cpa_lifts) / len(cpa_lifts) if cpa_lifts else None

        # Determine confidence level
        n = len(events)
        majority = max(len(positive), len(negative)) / n if n > 0 else 0
        if n >= 10 and majority > 0.7:
            conf = "vysoka"
        elif n >= 5 and majority > 0.6:
            conf = "stredni"
        else:
            conf = "nizka"

        # Generate learning description
        if len(positive) > len(negative) * 2 and avg_roas and avg_roas > 5:
            desc = f"{change_type}: typicky zlepsuje vykon (prumerny ROAS lift +{avg_roas:.0f}%)"
            ltype = "best_practice"
        elif len(negative) > len(positive) * 2 and avg_roas and avg_roas < -5:
            desc = f"{change_type}: typicky zhorsuje vykon (prumerny ROAS lift {avg_roas:.0f}%)"
            ltype = "warning"
        else:
            desc = f"{change_type}: mixovane vysledky ({len(positive)} pozitivnich, {len(negative)} negativnich)"
            ltype = "change_pattern"

        try:
            conn.execute("""
                INSERT OR REPLACE INTO learnings
                (learning_type, change_type, description, evidence_json, sample_size,
                 avg_roas_lift, avg_cpa_lift, confidence, generated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (ltype, change_type, desc,
                  json.dumps([e["id"] for e in events]),
                  n, avg_roas, avg_cpa, conf, now))
            generated += 1
        except Exception as e:
            print(f"  WARN: save learning: {e}", file=sys.stderr)

    conn.commit()
    return generated
