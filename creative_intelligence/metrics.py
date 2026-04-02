"""Ad-level metrics calculation — 25+ metrik z Meta API dat."""

import json
from datetime import datetime, timedelta

from .meta_client import meta_fetch_all
from .config import (
    AD_ACCOUNT_ID, TARGET_CPA, TARGET_ROAS,
    MIN_SPEND_FOR_DECISION, MIN_IMPRESSIONS,
)

INSIGHTS_FIELDS = ",".join([
    "ad_id", "ad_name", "campaign_id", "campaign_name",
    "adset_id", "adset_name",
    "impressions", "reach", "frequency",
    "spend", "clicks", "cpc", "cpm", "ctr",
    "actions", "action_values", "cost_per_action_type", "purchase_roas",
    "video_avg_time_watched_actions",
    "video_p25_watched_actions",
    "video_p50_watched_actions",
    "video_p75_watched_actions",
    "video_p100_watched_actions",
    "video_thruplay_watched_actions",
    "video_30_sec_watched_actions",
])


def fetch_ad_insights(days=14):
    """Stahne ad-level insights vcetne video metrik."""
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    until = datetime.now().strftime("%Y-%m-%d")

    params = {
        "fields": INSIGHTS_FIELDS,
        "level": "ad",
        "time_range": json.dumps({"since": since, "until": until}),
        "limit": "200",
        "filtering": json.dumps([{
            "field": "impressions",
            "operator": "GREATER_THAN",
            "value": "0"
        }]),
    }
    return meta_fetch_all(f"{AD_ACCOUNT_ID}/insights", params)


def fetch_ad_creatives():
    """Stahne creative metadata pro vsechny aktivni ads."""
    params = {
        "fields": "id,name,status,effective_status,creative{id,name,title,body,image_url,thumbnail_url,video_id,object_type,call_to_action_type}",
        "filtering": json.dumps([{
            "field": "effective_status",
            "operator": "IN",
            "value": ["ACTIVE", "PAUSED"]
        }]),
        "limit": "200",
    }
    return meta_fetch_all(f"{AD_ACCOUNT_ID}/ads", params)


def calculate_confidence(purchases, spend):
    """Confidence score 0.0-1.0: purchases (60%) + spend (40%)."""
    return min(purchases / 10, 1.0) * 0.6 + min(spend / 5000, 1.0) * 0.4


def confidence_level(confidence):
    if confidence >= 0.7:
        return "vysoka"
    if confidence >= 0.3:
        return "stredni"
    return "nizka"


def extract_action(row, action_type, field="actions"):
    """Extract action value from Meta API actions array."""
    actions = row.get(field, [])
    if not actions:
        return 0
    for a in actions:
        if a.get("action_type") == action_type:
            return float(a.get("value", 0))
    return 0


def extract_video_metric(row, field_name):
    """Extract video metric (sum across all action types)."""
    items = row.get(field_name, [])
    if not items:
        return 0
    return sum(float(item.get("value", 0)) for item in items)


def calculate_metrics(row):
    """Calculate all metrics for a single ad."""
    impressions = float(row.get("impressions", 0))
    spend = float(row.get("spend", 0))
    clicks = float(row.get("clicks", 0))
    frequency = float(row.get("frequency", 0))
    ctr = float(row.get("ctr", 0))
    cpm = float(row.get("cpm", 0))

    purchases = extract_action(row, "purchase")
    add_to_cart = extract_action(row, "add_to_cart")
    purchase_value = extract_action(row, "purchase", field="action_values")

    cpa = spend / purchases if purchases > 0 else None
    cvr = (purchases / clicks * 100) if clicks > 0 and purchases > 0 else None

    roas_raw = row.get("purchase_roas", [])
    roas = float(roas_raw[0]["value"]) if roas_raw else (purchase_value / spend if spend > 0 and purchase_value > 0 else None)

    # Video metrics
    video_views = extract_action(row, "video_view")
    video_thruplay = extract_video_metric(row, "video_thruplay_watched_actions")
    video_p25 = extract_video_metric(row, "video_p25_watched_actions")
    video_p50 = extract_video_metric(row, "video_p50_watched_actions")
    video_p75 = extract_video_metric(row, "video_p75_watched_actions")
    video_p100 = extract_video_metric(row, "video_p100_watched_actions")

    hook_rate = (video_views / impressions * 100) if impressions > 0 and video_views > 0 else None
    hold_rate = (video_thruplay / video_views * 100) if video_views > 0 and video_thruplay > 0 else None
    completion_rate = (video_p100 / video_views * 100) if video_views > 0 and video_p100 > 0 else None
    is_video = video_views > 0

    # Video drop-off diagnosis
    video_dropoff_diagnosis = None
    if video_views > 0 and impressions > MIN_IMPRESSIONS:
        hook = (video_views / impressions * 100) if impressions > 0 else 0
        retention_25 = (video_p25 / video_views * 100) if video_views > 0 and video_p25 > 0 else 0
        retention_50 = (video_p50 / video_views * 100) if video_views > 0 and video_p50 > 0 else 0
        retention_75 = (video_p75 / video_views * 100) if video_views > 0 and video_p75 > 0 else 0
        retention_100 = (video_p100 / video_views * 100) if video_views > 0 and video_p100 > 0 else 0

        if hook < 20:
            video_dropoff_diagnosis = "SPATNY_HOOK"
        elif retention_25 > 0 and retention_50 > 0 and (retention_25 - retention_50) > 30:
            video_dropoff_diagnosis = "MIDDLE_SAG"
        elif retention_75 > 0 and retention_100 > 0 and retention_75 > 20 and retention_100 < 10:
            video_dropoff_diagnosis = "POZDNI_CTA"
        elif retention_50 > 40:
            video_dropoff_diagnosis = "ZDRAVY_FUNNEL"

    conf = calculate_confidence(purchases, spend)

    return {
        "ad_id": row.get("ad_id"),
        "ad_name": row.get("ad_name", ""),
        "campaign_name": row.get("campaign_name", ""),
        "adset_name": row.get("adset_name", ""),
        "impressions": int(impressions),
        "reach": int(float(row.get("reach", 0))),
        "frequency": round(frequency, 2),
        "spend": round(spend, 1),
        "clicks": int(clicks),
        "ctr": round(ctr, 2),
        "cpm": round(cpm, 1),
        "purchases": int(purchases),
        "add_to_cart": int(add_to_cart),
        "revenue": round(purchase_value, 1),
        "cpa": round(cpa, 1) if cpa else None,
        "cvr": round(cvr, 2) if cvr else None,
        "roas": round(roas, 2) if roas else None,
        "is_video": is_video,
        "video_3s_views": int(video_views),
        "video_thruplay": int(video_thruplay),
        "video_p25": int(video_p25),
        "video_p50": int(video_p50),
        "video_p75": int(video_p75),
        "video_p100": int(video_p100),
        "hook_rate": round(hook_rate, 1) if hook_rate else None,
        "hold_rate": round(hold_rate, 1) if hold_rate else None,
        "completion_rate": round(completion_rate, 1) if completion_rate else None,
        "video_dropoff": video_dropoff_diagnosis,
        "retention_p25": round((video_p25 / video_views * 100), 1) if video_views > 0 and video_p25 > 0 else None,
        "retention_p50": round((video_p50 / video_views * 100), 1) if video_views > 0 and video_p50 > 0 else None,
        "retention_p75": round((video_p75 / video_views * 100), 1) if video_views > 0 and video_p75 > 0 else None,
        "retention_p100": round((video_p100 / video_views * 100), 1) if video_views > 0 and video_p100 > 0 else None,
        "confidence": round(conf, 2),
        "confidence_level": confidence_level(conf),
        "weighted_roas": round((roas or 0) * conf, 2),
    }
