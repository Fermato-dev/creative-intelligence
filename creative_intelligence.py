#!/usr/bin/env python3
"""
Fermato Creative Intelligence — Meta Ads
=========================================
Stahuje ad-level data z Meta API vcetne video metrik,
pocita hook rate / hold rate / fatigue skore,
generuje kill / scale / iterate doporuceni.

Pouziti:
    python creative_intelligence.py                # last 14 days, report
    python creative_intelligence.py --days 30      # last 30 days
    python creative_intelligence.py --json          # JSON output
    python creative_intelligence.py --csv           # CSV export
"""

import json
import os
import sys
import csv
import io
import urllib.request
import urllib.parse
from datetime import datetime, timedelta

# ── Config ──

ACCESS_TOKEN = os.environ.get("META_ADS_ACCESS_TOKEN")
AD_ACCOUNT_ID = "act_346692147206629"
API_VERSION = "v23.0"
API_BASE = f"https://graph.facebook.com/{API_VERSION}"

# Target metriky pro Fermato (uprav podle svych targetu)
TARGET_CPA = 250  # CZK, target cost per purchase
TARGET_ROAS = 2.5
MIN_SPEND_FOR_DECISION = 200  # CZK, min spend pro kill/scale rozhodnuti
MIN_IMPRESSIONS = 1000  # min impressions pro hook rate vypocet

# ── API helpers ──

def meta_fetch(endpoint, params=None):
    """Single API call."""
    if params is None:
        params = {}
    params["access_token"] = ACCESS_TOKEN
    url = f"{API_BASE}/{endpoint}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())

def meta_fetch_all(endpoint, params=None, max_pages=10):
    """Paginated API call."""
    if params is None:
        params = {}
    params["access_token"] = ACCESS_TOKEN
    url = f"{API_BASE}/{endpoint}?" + urllib.parse.urlencode(params)

    results = []
    page = 0
    while url and page < max_pages:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
        results.extend(data.get("data", []))
        url = data.get("paging", {}).get("next")
        page += 1
    return results

# ── Data fetching ──

INSIGHTS_FIELDS = ",".join([
    "ad_id", "ad_name", "campaign_id", "campaign_name",
    "adset_id", "adset_name",
    "impressions", "reach", "frequency",
    "spend", "clicks", "cpc", "cpm", "ctr",
    "actions", "action_values", "cost_per_action_type", "purchase_roas",
    # Video metriky
    "video_avg_time_watched_actions",
    "video_p25_watched_actions",
    "video_p50_watched_actions",
    "video_p75_watched_actions",
    "video_p100_watched_actions",
    "video_thruplay_watched_actions",
    "video_30_sec_watched_actions",
])

# 3s video views vyzaduji specialni handling - jsou v actions jako video_view
# Ale muzeme je ziskat pres video_play_actions field
VIDEO_EXTRA_FIELDS = "video_play_actions"


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

# ── Metrics calculation ──

def extract_action(row, action_type, field="actions"):
    """Extrahuje hodnotu konkretni akce z actions pole."""
    actions = row.get(field, [])
    if not actions:
        return 0
    for a in actions:
        if a.get("action_type") == action_type:
            return float(a.get("value", 0))
    return 0


def extract_video_metric(row, field_name):
    """Extrahuje video metriku (soucet pres vsechny action_type)."""
    items = row.get(field_name, [])
    if not items:
        return 0
    total = 0
    for item in items:
        total += float(item.get("value", 0))
    return total


def calculate_metrics(row):
    """Vypocita vsechny metriky pro jeden ad."""
    impressions = float(row.get("impressions", 0))
    spend = float(row.get("spend", 0))
    clicks = float(row.get("clicks", 0))
    frequency = float(row.get("frequency", 0))
    ctr = float(row.get("ctr", 0))
    cpm = float(row.get("cpm", 0))

    # Konverze
    purchases = extract_action(row, "purchase")
    add_to_cart = extract_action(row, "add_to_cart")

    # Revenue
    purchase_value = extract_action(row, "purchase", field="action_values")

    # CPA
    cpa = spend / purchases if purchases > 0 else None

    # CVR (post-click conversion rate) — klicova metrika, CTR sam = 4% ROI
    cvr = (purchases / clicks * 100) if clicks > 0 and purchases > 0 else None

    # ROAS
    roas_raw = row.get("purchase_roas", [])
    roas = float(roas_raw[0]["value"]) if roas_raw else (purchase_value / spend if spend > 0 and purchase_value > 0 else None)

    # Video metriky
    video_views = extract_action(row, "video_view")  # 3s views
    video_thruplay = extract_video_metric(row, "video_thruplay_watched_actions")
    video_p25 = extract_video_metric(row, "video_p25_watched_actions")
    video_p50 = extract_video_metric(row, "video_p50_watched_actions")
    video_p75 = extract_video_metric(row, "video_p75_watched_actions")
    video_p100 = extract_video_metric(row, "video_p100_watched_actions")

    # Hook Rate = 3s video views / impressions
    hook_rate = (video_views / impressions * 100) if impressions > 0 and video_views > 0 else None

    # Hold Rate = thruplay (15s+) / 3s views
    hold_rate = (video_thruplay / video_views * 100) if video_views > 0 and video_thruplay > 0 else None

    # Completion Rate = 100% watched / 3s views
    completion_rate = (video_p100 / video_views * 100) if video_views > 0 and video_p100 > 0 else None

    # Video je kreativa pokud existuji video views
    is_video = video_views > 0

    # Video drop-off diagnoza — kde se ztraci lidi
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
        # Video retention po 3s views (% tech co presli 3s)
        "retention_p25": round((video_p25 / video_views * 100), 1) if video_views > 0 and video_p25 > 0 else None,
        "retention_p50": round((video_p50 / video_views * 100), 1) if video_views > 0 and video_p50 > 0 else None,
        "retention_p75": round((video_p75 / video_views * 100), 1) if video_views > 0 and video_p75 > 0 else None,
        "retention_p100": round((video_p100 / video_views * 100), 1) if video_views > 0 and video_p100 > 0 else None,
        # Confidence: jak moc muzeme verit datum pro rozhodnuti
        # 0.0-0.3 = nizka (malo dat), 0.3-0.7 = stredni, 0.7-1.0 = vysoka
        "confidence": round(
            min(purchases / 10, 1.0) * 0.6 + min(spend / 5000, 1.0) * 0.4,
            2
        ),
        "confidence_level": (
            "vysoka" if (min(purchases / 10, 1.0) * 0.6 + min(spend / 5000, 1.0) * 0.4) >= 0.7
            else "stredni" if (min(purchases / 10, 1.0) * 0.6 + min(spend / 5000, 1.0) * 0.4) >= 0.3
            else "nizka"
        ),
        # Weighted ROAS: zohlednuje spolehlivost dat
        "weighted_roas": round(
            (roas or 0) * (min(purchases / 10, 1.0) * 0.6 + min(spend / 5000, 1.0) * 0.4),
            2
        ),
    }

# ── Kill / Scale / Iterate engine ──

def evaluate_creative(m):
    """Vraci seznam doporuceni pro kreativu.

    Engine v2 — vylepsen na zaklade reserse:
    - CVR jako klicova metrika (CTR = 4% ROI, kreativa = 56% ROI)
    - Multi-signalova fatigue detekce (CVR drop > CTR drop > freq > CPA spike)
    - Video drop-off diagnoza (hook/middle/CTA problem)
    - Aktualizovane benchmarky: hook 25%, hold 40%, freq 3.0 cold / 6.0 retarg
    - Clickbait detekce: vysoky CTR + nizka CVR
    """
    recommendations = []
    spend = m["spend"]
    impressions = m["impressions"]

    # Nedostatek dat
    if spend < MIN_SPEND_FOR_DECISION and impressions < MIN_IMPRESSIONS:
        return [("INFO", "Nedostatek dat pro rozhodnuti", f"Spend {spend} CZK, {impressions} impr")]

    # ── KILL rules ──

    # CPA vysoko nad targetem
    if m["cpa"] and m["cpa"] > TARGET_CPA * 2 and spend > MIN_SPEND_FOR_DECISION:
        recommendations.append(("KILL", "CPA 2x+ nad targetem",
            f"CPA {m['cpa']} CZK vs target {TARGET_CPA} CZK"))
    elif m["cpa"] and m["cpa"] > TARGET_CPA * 1.3 and spend > MIN_SPEND_FOR_DECISION * 2:
        recommendations.append(("KILL", "CPA 30%+ nad targetem pri vyssim spendu",
            f"CPA {m['cpa']} CZK vs target {TARGET_CPA} CZK, spend {spend} CZK"))

    # Multi-signalova fatigue detekce (hierarchie: freq + CTR + CVR)
    # Tier 3 fatigue: extremni frekvence (5+ cold)
    if m["frequency"] > 5.0 and m["ctr"] < 1.0:
        recommendations.append(("KILL", "Extremni ad fatigue — okamzite zastavit",
            f"Frekvence {m['frequency']} (>5), CTR {m['ctr']}% — audience maximalne saturovana"))
    # Tier 2 fatigue: vysoka frekvence (3+ cold)
    elif m["frequency"] > 3.0 and m["ctr"] < 0.8:
        recommendations.append(("KILL", "Ad fatigue — vysoka frekvence + nizky CTR",
            f"Frekvence {m['frequency']}, CTR {m['ctr']}%"))
    # Tier 1 fatigue: stredni frekvence + spatna CVR (nejdrivejsi signal)
    elif m["frequency"] > 2.5 and m.get("cvr") is not None and m["cvr"] < 1.0 and m["ctr"] > 1.0:
        recommendations.append(("KILL", "Skryta fatigue — CTR OK ale CVR pada",
            f"Freq {m['frequency']}, CTR {m['ctr']}% ale CVR jen {m['cvr']}% — audience uz nekonvertuje"))

    # Hodne spendu, zadne nakupy
    if spend > TARGET_CPA * 3 and m["purchases"] == 0:
        recommendations.append(("KILL", "Zadne nakupy pri vysokem spendu",
            f"Spend {spend} CZK, 0 purchases"))

    # Nizky ROAS
    if m["roas"] is not None and m["roas"] < 1.0 and spend > MIN_SPEND_FOR_DECISION:
        recommendations.append(("KILL", "ROAS pod 1.0 — ztratovy",
            f"ROAS {m['roas']}"))

    # Clickbait detekce: vysoky CTR ale miziva CVR = kreativa laka spatne lidi
    if m["ctr"] > 2.0 and m.get("cvr") is not None and m["cvr"] < 0.5 and spend > MIN_SPEND_FOR_DECISION * 2:
        recommendations.append(("KILL", "Clickbait kreativa — vysoky CTR, nulova konverze",
            f"CTR {m['ctr']}% ale CVR {m['cvr']}% — uprav sdělení nebo landing page"))

    # ── SCALE rules (vyzaduji dostatecnou confidence) ──

    confidence = m.get("confidence", 0)

    # Vysoky ROAS — ale jen pokud mame dost dat
    if m["roas"] and m["roas"] > TARGET_ROAS * 1.2 and spend > MIN_SPEND_FOR_DECISION:
        if confidence >= 0.5:
            recommendations.append(("SCALE", "ROAS 20%+ nad targetem",
                f"ROAS {m['roas']} vs target {TARGET_ROAS}, {m['purchases']} nakupu"))
        else:
            recommendations.append(("WATCH", "Slibny ROAS ale malo dat",
                f"ROAS {m['roas']}, jen {m['purchases']} nakupu — cekej na vic dat"))

    # Nizky CPA s dostatecnym vzorkem
    if m["cpa"] and m["cpa"] < TARGET_CPA * 0.7 and m["purchases"] >= 5:
        recommendations.append(("SCALE", "CPA 30%+ pod targetem s dostatkem konverzi",
            f"CPA {m['cpa']} CZK, {m['purchases']} nakupu"))

    # Vysoka CVR = kreativa prodava (ne jen laka kliky)
    if m.get("cvr") and m["cvr"] > 3.0 and m["purchases"] >= 5 and confidence >= 0.5:
        recommendations.append(("SCALE", "Vysoka konverzni mira — kreativa prodava",
            f"CVR {m['cvr']}% (benchmark >2%), {m['purchases']} nakupu"))

    # ── ITERATE rules — VIDEO ──

    if m["is_video"] and m["hook_rate"] is not None:
        # Hook rate benchmarky (research: 25% minimum, 30% dobre, 35% elite)
        if m["hook_rate"] >= 30 and m["hold_rate"] is not None and m["hold_rate"] < 40:
            recommendations.append(("ITERATE", "Dobry hook, slaby hold — uprav stred videa",
                f"Hook {m['hook_rate']}% (OK), Hold {m['hold_rate']}% (benchmark >40%)"))
        elif m["hook_rate"] >= 25 and m["hold_rate"] is not None and m["hold_rate"] < 30:
            recommendations.append(("ITERATE", "Solidni hook, slaby hold",
                f"Hook {m['hook_rate']}%, Hold {m['hold_rate']}% — middle sag, uprav pace videa"))

        if m["hook_rate"] < 25 and m["roas"] and m["roas"] > TARGET_ROAS * 0.8:
            recommendations.append(("ITERATE", "Podprumerny hook ale slusny ROAS — natoc novy hook",
                f"Hook {m['hook_rate']}% (benchmark >=25%), ROAS {m['roas']}"))

        if m["hook_rate"] >= 35 and confidence >= 0.5:
            recommendations.append(("SCALE", "Vynikajici hook rate",
                f"Hook {m['hook_rate']}% (elite >35%)"))

        if m["hook_rate"] < 20 and impressions > MIN_IMPRESSIONS:
            recommendations.append(("ITERATE", "Nizky hook — 1. frame a text overlay nefunguje",
                f"Hook {m['hook_rate']}% (benchmark >=25%, minimum 20%)"))

        # Video drop-off diagnoza
        dropoff = m.get("video_dropoff")
        if dropoff == "SPATNY_HOOK":
            recommendations.append(("ITERATE", "Video drop-off: spatny opening",
                f"Hook {m['hook_rate']}% — zmen 1. frame, pridej text/movement v prvnich 2s"))
        elif dropoff == "MIDDLE_SAG":
            recommendations.append(("ITERATE", "Video drop-off: propad uprostred",
                f"Silny drop mezi 25-50% videa — zkrat, pridej napeti, preradesuj story"))
        elif dropoff == "POZDNI_CTA":
            recommendations.append(("ITERATE", "Video drop-off: CTA prilis pozde",
                f"75% retention OK ({m.get('retention_p75')}%) ale 100% propad ({m.get('retention_p100')}%) — presun CTA drive"))

    # ── ITERATE rules — STATICKE / BANNERY ──

    if not m["is_video"]:
        # Nizky CTR = banner neoslovuje (benchmark food & bev: 1.67%)
        if m["ctr"] < 1.0 and impressions > MIN_IMPRESSIONS and spend > MIN_SPEND_FOR_DECISION:
            recommendations.append(("ITERATE", "Nizky CTR — zmen vizual nebo text",
                f"CTR {m['ctr']}% (benchmark food&bev >1.5%)"))

        # Vysoky CTR ale nizky ROAS = clickbait nebo spatna LP
        if m["ctr"] > 2.0 and m["roas"] and m["roas"] < TARGET_ROAS * 0.6 and spend > MIN_SPEND_FOR_DECISION:
            detail = f"CTR {m['ctr']}%, ROAS {m['roas']}"
            if m.get("cvr") is not None:
                detail += f", CVR {m['cvr']}%"
            recommendations.append(("ITERATE", "Vysoky CTR ale nizky ROAS — disconnect kreativa vs. LP",
                detail))

        # Nizka CVR pri slusnem CTR = problem na landing page, ne v kreative
        if m.get("cvr") is not None and m["cvr"] < 1.0 and m["ctr"] > 1.5 and spend > MIN_SPEND_FOR_DECISION:
            recommendations.append(("ITERATE", "LP problem — CTR OK ale CVR nizka",
                f"CTR {m['ctr']}%, CVR {m['cvr']}% — kreativa funguje, landing page nekonvertuje"))

        # Vysoky CTR a ROAS = skvely banner
        if m["ctr"] > 2.0 and m["roas"] and m["roas"] > TARGET_ROAS and confidence >= 0.5:
            recommendations.append(("SCALE", "Silny CTR + ROAS",
                f"CTR {m['ctr']}%, ROAS {m['roas']}"))

        # Vysoka CVR = banner ktery prodava
        if m.get("cvr") and m["cvr"] > 3.0 and m["roas"] and m["roas"] > TARGET_ROAS * 0.9 and confidence >= 0.4:
            recommendations.append(("SCALE", "Vysoka CVR — banner ktery konvertuje",
                f"CVR {m['cvr']}%, ROAS {m['roas']}"))

    # ── WATCH rules (oba typy) ──

    # Frequency tiers pro fatigue monitoring
    if m["frequency"] > 2.0 and m["frequency"] <= 3.0:
        typ = "videa" if m["is_video"] else "banneru"
        recommendations.append(("WATCH", f"Frekvence {typ} roste — priprav refresh kreativy",
            f"Frekvence {m['frequency']} (alert na 3.0 cold / 6.0 retargeting)"))
    elif m["frequency"] > 3.0 and m["frequency"] <= 5.0 and m["ctr"] >= 0.8:
        # Vysoka freq ale CTR jeste drzi — brzy spadne
        recommendations.append(("WATCH", "Vysoka frekvence, CTR jeste drzi — casovana bomba",
            f"Freq {m['frequency']}, CTR {m['ctr']}% — refresh do 7 dni"))

    if not recommendations:
        if m["roas"] and m["roas"] >= TARGET_ROAS * 0.8:
            cvr_info = f", CVR {m['cvr']}%" if m.get("cvr") else ""
            recommendations.append(("OK", "V norme", f"ROAS {m['roas']}, CPA {m['cpa']}{cvr_info}"))
        else:
            recommendations.append(("WATCH", "Bez jasneho signalu", "Sleduj dalsi dny"))

    return recommendations

# ── Report generation ──

def generate_report(ads_metrics):
    """Generuje textovy report (v2 — s CVR, portfolio health, drop-off diagnozou)."""
    lines = []
    lines.append("=" * 70)
    lines.append("  FERMATO CREATIVE INTELLIGENCE REPORT v2")
    lines.append(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("=" * 70)

    # Summary
    total_spend = sum(m["spend"] for m in ads_metrics)
    total_purchases = sum(m["purchases"] for m in ads_metrics)
    total_revenue = sum(m["revenue"] for m in ads_metrics)
    total_clicks = sum(m["clicks"] for m in ads_metrics)
    overall_roas = total_revenue / total_spend if total_spend > 0 else 0
    overall_cvr = (total_purchases / total_clicks * 100) if total_clicks > 0 else 0
    video_ads = [m for m in ads_metrics if m["is_video"]]
    static_ads = [m for m in ads_metrics if not m["is_video"]]
    avg_hook = sum(m["hook_rate"] for m in video_ads if m["hook_rate"]) / max(len([m for m in video_ads if m["hook_rate"]]), 1)

    # Portfolio health: ad concentration
    sorted_by_spend = sorted(ads_metrics, key=lambda x: x["spend"], reverse=True)
    top5_spend = sum(m["spend"] for m in sorted_by_spend[:5])
    ad_concentration = (top5_spend / total_spend * 100) if total_spend > 0 else 0

    lines.append(f"\n## Souhrn")
    lines.append(f"  Aktivnich ads:     {len(ads_metrics)} (video: {len(video_ads)}, static: {len(static_ads)})")
    lines.append(f"  Celkovy spend:     {total_spend:,.0f} CZK")
    lines.append(f"  Celkove nakupy:    {total_purchases}")
    lines.append(f"  Celkova trzba:     {total_revenue:,.0f} CZK")
    lines.append(f"  Overall ROAS:      {overall_roas:.2f}  (7-day click atribuce)")
    lines.append(f"  Overall CVR:       {overall_cvr:.2f}%  (purchases/clicks)")
    lines.append(f"  Video hook rate:   {avg_hook:.1f}%  (benchmark: >=25%)")
    lines.append(f"  Ad concentration:  {ad_concentration:.1f}% spendu v top 5 ads")

    # Data reliability note
    lines.append(f"\n  !! DATA RELIABILITY: ROAS je Meta 7-day click atribuce.")
    lines.append(f"    Skutecny inkrementalni dopad muze byt +/-30-70%.")
    lines.append(f"    Pouzivej pro relativni srovnani (A vs B), ne absolutni pravdu.")

    # Evaluate all
    evaluations = []
    for m in ads_metrics:
        recs = evaluate_creative(m)
        evaluations.append((m, recs))

    # Sort by priority
    priority = {"KILL": 0, "ITERATE": 1, "SCALE": 2, "WATCH": 3, "OK": 4, "INFO": 5}

    # Group by recommendation type
    kills = [(m, r) for m, recs in evaluations for r in recs if r[0] == "KILL"]
    scales = [(m, r) for m, recs in evaluations for r in recs if r[0] == "SCALE"]
    iterates = [(m, r) for m, recs in evaluations for r in recs if r[0] == "ITERATE"]
    watches = [(m, r) for m, recs in evaluations for r in recs if r[0] == "WATCH"]

    # Action summary
    lines.append(f"\n## Akce")
    lines.append(f"  KILL (zastavit):    {len(kills)}")
    lines.append(f"  SCALE (skalovat):   {len(scales)}")
    lines.append(f"  ITERATE (upravit):  {len(iterates)}")
    lines.append(f"  WATCH (sledovat):   {len(watches)}")

    # KILL section
    if kills:
        lines.append(f"\n{'='*70}")
        lines.append(f"  KILL — ZASTAVIT")
        lines.append(f"{'='*70}")
        for m, (action, reason, detail) in sorted(kills, key=lambda x: x[0]["spend"], reverse=True):
            lines.append(f"\n  [{m['ad_id']}] {m['ad_name'][:50]}")
            lines.append(f"    Kampan: {m['campaign_name']}")
            cvr_str = f" | CVR: {m['cvr']}%" if m.get('cvr') else ""
            lines.append(f"    Spend: {m['spend']} CZK | ROAS: {m['roas']} | CPA: {m['cpa']} CZK{cvr_str}")
            lines.append(f"    Freq: {m['frequency']} | CTR: {m['ctr']}%")
            if m["is_video"]:
                lines.append(f"    Hook: {m['hook_rate']}% | Hold: {m['hold_rate']}%")
            lines.append(f"    >> {reason}: {detail}")

    # SCALE section
    if scales:
        lines.append(f"\n{'='*70}")
        lines.append(f"  SCALE — SKALOVAT")
        lines.append(f"{'='*70}")
        for m, (action, reason, detail) in sorted(scales, key=lambda x: x[0].get("roas") or 0, reverse=True):
            lines.append(f"\n  [{m['ad_id']}] {m['ad_name'][:50]}")
            lines.append(f"    Kampan: {m['campaign_name']}")
            cvr_str = f" | CVR: {m['cvr']}%" if m.get('cvr') else ""
            lines.append(f"    Spend: {m['spend']} CZK | ROAS: {m['roas']} | CPA: {m['cpa']} CZK{cvr_str}")
            lines.append(f"    Purchases: {m['purchases']} | Revenue: {m['revenue']} CZK")
            if m["is_video"]:
                lines.append(f"    Hook: {m['hook_rate']}% | Hold: {m['hold_rate']}%")
            lines.append(f"    >> {reason}: {detail}")

    # ITERATE section
    if iterates:
        lines.append(f"\n{'='*70}")
        lines.append(f"  ITERATE — UPRAVIT KREATIVU")
        lines.append(f"{'='*70}")
        for m, (action, reason, detail) in iterates:
            lines.append(f"\n  [{m['ad_id']}] {m['ad_name'][:50]}")
            lines.append(f"    Kampan: {m['campaign_name']}")
            lines.append(f"    Spend: {m['spend']} CZK | ROAS: {m['roas']} | CTR: {m['ctr']}%")
            if m["is_video"]:
                lines.append(f"    Hook: {m['hook_rate']}% | Hold: {m['hold_rate']}% | Complete: {m['completion_rate']}%")
            lines.append(f"    >> {reason}: {detail}")

    # Top performers table
    lines.append(f"\n{'='*70}")
    lines.append(f"  TOP PERFORMERS (by ROAS)")
    lines.append(f"{'='*70}")
    by_roas = sorted([m for m in ads_metrics if m["roas"] and m["spend"] > 100],
                     key=lambda x: x["roas"], reverse=True)[:10]

    lines.append(f"\n  {'Ad Name':<35} {'Spend':>8} {'ROAS':>6} {'CPA':>7} {'Hook':>6} {'Hold':>6}")
    lines.append(f"  {'-'*35} {'-'*8} {'-'*6} {'-'*7} {'-'*6} {'-'*6}")
    for m in by_roas:
        hook = f"{m['hook_rate']}%" if m['hook_rate'] else "—"
        hold = f"{m['hold_rate']}%" if m['hold_rate'] else "—"
        cpa = f"{m['cpa']}" if m['cpa'] else "—"
        lines.append(f"  {m['ad_name'][:35]:<35} {m['spend']:>7.0f} {m['roas']:>6.2f} {cpa:>7} {hook:>6} {hold:>6}")

    # Video hook rate leaderboard
    if video_ads:
        lines.append(f"\n{'='*70}")
        lines.append(f"  VIDEO HOOK RATE LEADERBOARD")
        lines.append(f"{'='*70}")
        by_hook = sorted([m for m in video_ads if m["hook_rate"] and m["impressions"] > MIN_IMPRESSIONS],
                         key=lambda x: x["hook_rate"], reverse=True)[:10]

        lines.append(f"\n  {'Ad Name':<35} {'Hook':>6} {'Hold':>6} {'Compl':>6} {'ROAS':>6} {'Spend':>8}")
        lines.append(f"  {'-'*35} {'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*8}")
        for m in by_hook:
            roas = f"{m['roas']:.2f}" if m['roas'] else "—"
            hold = f"{m['hold_rate']}%" if m['hold_rate'] else "—"
            compl = f"{m['completion_rate']}%" if m['completion_rate'] else "—"
            lines.append(f"  {m['ad_name'][:35]:<35} {m['hook_rate']:>5.1f}% {hold:>6} {compl:>6} {roas:>6} {m['spend']:>7.0f}")

    # CVR leaderboard (klicova metrika — CTR = 4% ROI, CVR rozhoduje)
    ads_with_cvr = [m for m in ads_metrics if m.get("cvr") and m["purchases"] >= 3]
    if ads_with_cvr:
        lines.append(f"\n{'='*70}")
        lines.append(f"  CVR LEADERBOARD (konverzni mira — kreativa ktera PRODAVA)")
        lines.append(f"{'='*70}")
        by_cvr = sorted(ads_with_cvr, key=lambda x: x["cvr"], reverse=True)[:10]

        lines.append(f"\n  {'Ad Name':<30} {'CVR':>6} {'CTR':>6} {'ROAS':>6} {'CPA':>7} {'Purch':>6} {'Type':>6}")
        lines.append(f"  {'-'*30} {'-'*6} {'-'*6} {'-'*6} {'-'*7} {'-'*6} {'-'*6}")
        for m in by_cvr:
            roas = f"{m['roas']:.2f}" if m['roas'] else "—"
            cpa = f"{m['cpa']:.0f}" if m['cpa'] else "—"
            typ = "VIDEO" if m["is_video"] else "STAT"
            lines.append(f"  {m['ad_name'][:30]:<30} {m['cvr']:>5.2f}% {m['ctr']:>5.2f}% {roas:>6} {cpa:>7} {m['purchases']:>6} {typ:>6}")

        lines.append(f"\n  Insight: Reklama s CTR 0.8% a CVR 5% > reklama s CTR 3% a CVR 0.5%")
        lines.append(f"  CVR benchmark food&bev: >2% = dobre, >3% = vyborne")

    # Video drop-off diagnoza
    diagnosed = [m for m in video_ads if m.get("video_dropoff") and m["spend"] > MIN_SPEND_FOR_DECISION]
    if diagnosed:
        lines.append(f"\n{'='*70}")
        lines.append(f"  VIDEO DROP-OFF DIAGNOZA")
        lines.append(f"{'='*70}")
        lines.append(f"\n  Kde se ztraci lidi v konkretnim videu:")

        dropoff_labels = {
            "SPATNY_HOOK": "HOOK (0-3s)",
            "MIDDLE_SAG": "STRED (25-50%)",
            "POZDNI_CTA": "CTA (75-100%)",
            "ZDRAVY_FUNNEL": "OK",
        }

        for diagnosis_type, label in dropoff_labels.items():
            group = [m for m in diagnosed if m["video_dropoff"] == diagnosis_type]
            if group:
                lines.append(f"\n  {label}:")
                for m in sorted(group, key=lambda x: x["spend"], reverse=True)[:5]:
                    ret_info = ""
                    if m.get("retention_p25"):
                        ret_info = f" | p25:{m['retention_p25']}% p50:{m.get('retention_p50','—')}% p75:{m.get('retention_p75','—')}%"
                    lines.append(f"    {m['ad_name'][:40]:<40} Hook:{m['hook_rate'] or '—'}%{ret_info}")

        # Stats
        counts = {}
        for m in diagnosed:
            d = m.get("video_dropoff", "UNKNOWN")
            counts[d] = counts.get(d, 0) + 1
        lines.append(f"\n  Souhrn: " + " | ".join(f"{dropoff_labels.get(k,k)}: {v}" for k, v in sorted(counts.items())))

    # Portfolio health
    lines.append(f"\n{'='*70}")
    lines.append(f"  PORTFOLIO HEALTH")
    lines.append(f"{'='*70}")

    # Ad concentration
    if ad_concentration > 50:
        lines.append(f"\n  !! Ad concentration: {ad_concentration:.1f}% spendu v top 5 ads — VYSOKE RIZIKO")
        lines.append(f"    Zavislost na malém poctu kreativ. Pokud top ad vyhorí, ROAS spadne.")
    elif ad_concentration > 35:
        lines.append(f"\n  Ad concentration: {ad_concentration:.1f}% spendu v top 5 ads — OK")
    else:
        lines.append(f"\n  Ad concentration: {ad_concentration:.1f}% spendu v top 5 ads — ZDRAVY rozptyl")

    # Format split
    video_spend = sum(m["spend"] for m in video_ads)
    static_spend = sum(m["spend"] for m in static_ads)
    video_purchases = sum(m["purchases"] for m in video_ads)
    static_purchases = sum(m["purchases"] for m in static_ads)
    video_roas = sum(m["revenue"] for m in video_ads) / video_spend if video_spend > 0 else 0
    static_roas = sum(m["revenue"] for m in static_ads) / static_spend if static_spend > 0 else 0
    video_cvr = (video_purchases / sum(m["clicks"] for m in video_ads) * 100) if sum(m["clicks"] for m in video_ads) > 0 else 0
    static_cvr = (static_purchases / sum(m["clicks"] for m in static_ads) * 100) if sum(m["clicks"] for m in static_ads) > 0 else 0

    lines.append(f"\n  Format split:")
    lines.append(f"  {'':>15} {'Spend':>10} {'ROAS':>6} {'CVR':>6} {'Purchases':>10} {'Ads':>5}")
    lines.append(f"  {'Video':<15} {video_spend:>9,.0f} {video_roas:>6.2f} {video_cvr:>5.2f}% {video_purchases:>10} {len(video_ads):>5}")
    lines.append(f"  {'Static':<15} {static_spend:>9,.0f} {static_roas:>6.2f} {static_cvr:>5.2f}% {static_purchases:>10} {len(static_ads):>5}")

    # Fatigue overview
    freq_high = [m for m in ads_metrics if m["frequency"] > 3.0 and m["spend"] > MIN_SPEND_FOR_DECISION]
    freq_warning = [m for m in ads_metrics if 2.0 < m["frequency"] <= 3.0 and m["spend"] > MIN_SPEND_FOR_DECISION]
    lines.append(f"\n  Fatigue monitoring:")
    lines.append(f"    Freq > 3.0 (akce): {len(freq_high)} ads")
    lines.append(f"    Freq 2.0-3.0 (sledovat): {len(freq_warning)} ads")

    # Clickbait detection summary
    clickbait = [m for m in ads_metrics if m["ctr"] > 2.0 and m.get("cvr") is not None and m["cvr"] < 0.5 and m["spend"] > MIN_SPEND_FOR_DECISION]
    if clickbait:
        wasted = sum(m["spend"] for m in clickbait)
        lines.append(f"\n  !! Clickbait detekce: {len(clickbait)} ads s vysokym CTR ale mizivou CVR")
        lines.append(f"    Celkovy spend na clickbait kreativy: {wasted:,.0f} CZK")

    lines.append(f"\n{'='*70}")
    lines.append(f"  BENCHMARKY v2 (research-backed)")
    lines.append(f"{'='*70}")
    lines.append(f"  Video:  Hook >=25% standard, >=30% dobre, >=35% elite")
    lines.append(f"          Hold >=40% standard, >=50% dobre, >=60% elite")
    lines.append(f"  Static: CTR >=1.0% minimum, >=1.5% dobre, >=2.0% elite")
    lines.append(f"  Oba:    CVR >=2.0% dobre, >=3.0% vyborne (food&bev)")
    lines.append(f"          Frequency <3.0 cold, <6.0 retargeting")
    lines.append(f"  Target: ROAS {TARGET_ROAS} | CPA {TARGET_CPA} CZK | Min spend {MIN_SPEND_FOR_DECISION} CZK")
    lines.append(f"{'='*70}")

    return "\n".join(lines)


def export_csv(ads_metrics):
    """Exportuje do CSV."""
    output = io.StringIO()
    if not ads_metrics:
        return ""
    writer = csv.DictWriter(output, fieldnames=ads_metrics[0].keys())
    writer.writeheader()
    writer.writerows(ads_metrics)
    return output.getvalue()


# ── Main ──

def main():
    if not ACCESS_TOKEN:
        print("CHYBA: Nastav META_ADS_ACCESS_TOKEN v environment variables")
        sys.exit(1)

    # Parse args
    days = 14
    output_format = "report"

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--days" and i + 1 < len(args):
            days = int(args[i + 1])
            i += 2
        elif args[i] == "--json":
            output_format = "json"
            i += 1
        elif args[i] == "--csv":
            output_format = "csv"
            i += 1
        elif args[i] == "--target-cpa" and i + 1 < len(args):
            global TARGET_CPA
            TARGET_CPA = float(args[i + 1])
            i += 2
        elif args[i] == "--target-roas" and i + 1 < len(args):
            global TARGET_ROAS
            TARGET_ROAS = float(args[i + 1])
            i += 2
        else:
            i += 1

    print(f"Stahuji ad-level data za poslednich {days} dni...", file=sys.stderr)
    raw_data = fetch_ad_insights(days)
    print(f"Stazeno {len(raw_data)} ad records.", file=sys.stderr)

    # Calculate metrics
    ads_metrics = [calculate_metrics(row) for row in raw_data]

    # Sort by spend desc
    ads_metrics.sort(key=lambda x: x["spend"], reverse=True)

    if output_format == "json":
        # Add recommendations to JSON
        for m in ads_metrics:
            m["recommendations"] = [
                {"action": a, "reason": r, "detail": d}
                for a, r, d in evaluate_creative(m)
            ]
        print(json.dumps(ads_metrics, indent=2, ensure_ascii=False))
    elif output_format == "csv":
        print(export_csv(ads_metrics))
    else:
        report = generate_report(ads_metrics)
        print(report)

        # Save report
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "outputs")
        os.makedirs(output_dir, exist_ok=True)
        report_path = os.path.join(output_dir, f"creative-intelligence-{datetime.now().strftime('%Y-%m-%d')}.txt")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\nReport ulozen: {report_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
