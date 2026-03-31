#!/usr/bin/env python3
"""
Fermato Creative Intelligence — Weekly Runner
==============================================
Orchestrator pro tydenni automaticky beh:
1. Spusti creative_intelligence analyzu (poslednich 7 dni)
2. Ulozi snapshot (SnapshotManager) pro historicke trendy
3. Zkontroluje ThresholdMonitor pravidla
4. Posle Pumble tydenni report do #meta-ads (pro performance specialisty)
5. Spusti AI analyzu kreativ (creative_vision) pokud je dostupna

Pumble report obsahuje:
- Klicove metriky: ROAS, CPA, CVR, Hook/Hold Rate + WoW trendy
- Format performance: Video vs. Static ROAS srovnani
- Alerty: fatigue, clickbait, threshold violations
- TOP kreativy ke skalovani (ROAS + CVR + confidence)
- KILL kreativy k zastaveni (waste spendu)
- ITERATE kreativy s konkretni diagnozou (hook/hold/LP problem)
- Video drop-off diagnoza (SPATNY_HOOK, MIDDLE_SAG, POZDNI_CTA)
- Portfolio health: ad concentration, fatigue risk, confidence coverage
- Doporucene akce na dalsi tyden

Pouziti:
    python creative_weekly_runner.py              # plny beh (7 dni)
    python creative_weekly_runner.py --days 14    # poslednich 14 dni
    python creative_weekly_runner.py --no-pumble  # bez Pumble notifikace
    python creative_weekly_runner.py --no-vision  # bez AI analyzy
"""

import json
import os
import sys
import traceback
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path

# ── Paths ──

SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent.parent.parent.parent  # projects/cmo/rust-a-akvizice/scripts → root
OUTPUT_DIR = SCRIPT_DIR.parent / "outputs"

# Add repo root to path for CoS tools
sys.path.insert(0, str(REPO_ROOT))
# Add scripts dir to path for creative_intelligence
sys.path.insert(0, str(SCRIPT_DIR))

import creative_intelligence as ci

# ── CoS Tools ──

def _load_cos_tools():
    """Lazy-load CoS tools (may not exist in all environments)."""
    try:
        from tools.cos.snapshot_manager import SnapshotManager
        from tools.cos.threshold_monitor import ThresholdMonitor
        return SnapshotManager, ThresholdMonitor
    except ImportError:
        return None, None

# ── Pumble notification ──

PUMBLE_CHANNEL = "meta-ads"
PUMBLE_API_TOKEN = os.environ.get("PUMBLE_API_TOKEN", "")
PUMBLE_API_BASE = "https://pumble-api-keys.addons.marketplace.cake.com"
PUMBLE_NOTIFICATION_FILE = OUTPUT_DIR / "pumble_notification.txt"


def send_pumble(text, channel=PUMBLE_CHANNEL):
    """Posle zpravu do Pumble kanalu primo pres HTTP API."""
    if not PUMBLE_API_TOKEN:
        print("WARN: PUMBLE_API_TOKEN neni nastaven, ukladam do souboru", file=sys.stderr)
        return _save_pumble_fallback(text, channel)

    try:
        # 1. Resolve channel name to ID
        req = urllib.request.Request(
            f"{PUMBLE_API_BASE}/listChannels",
            headers={"Api-Key": PUMBLE_API_TOKEN, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            channels = json.loads(resp.read())

        channel_id = None
        for item in channels:
            ch = item.get("channel", item)  # handle both formats
            if ch.get("name", "").lower() == channel.lower():
                channel_id = ch["id"]
                break

        if not channel_id:
            print(f"WARN: Pumble kanal '{channel}' nenalezen", file=sys.stderr)
            return _save_pumble_fallback(text, channel)

        # 2. Send message
        body = json.dumps({"channelId": channel_id, "text": text}).encode()
        req = urllib.request.Request(
            f"{PUMBLE_API_BASE}/sendMessage",
            data=body,
            method="POST",
            headers={"Api-Key": PUMBLE_API_TOKEN, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return True

    except Exception as e:
        print(f"WARN: Pumble odeslani selhalo: {e} — ukladam do souboru", file=sys.stderr)
        return _save_pumble_fallback(text, channel)


def _save_pumble_fallback(text, channel):
    """Fallback: ulozi zpravu do souboru."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PUMBLE_NOTIFICATION_FILE.write_text(
        json.dumps({"channel": channel, "text": text, "generated_at": datetime.now().isoformat()},
                   ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    (OUTPUT_DIR / "pumble_notification_plain.txt").write_text(text, encoding="utf-8")
    return False


# ── Snapshot & Threshold ──

def build_snapshot(ads_metrics):
    """Sestavi snapshot data z ads_metrics — rozsirena verze pro tydenni report."""
    total_spend = sum(m["spend"] for m in ads_metrics)
    total_purchases = sum(m["purchases"] for m in ads_metrics)
    total_revenue = sum(m["revenue"] for m in ads_metrics)
    total_clicks = sum(m["clicks"] for m in ads_metrics)
    overall_roas = total_revenue / total_spend if total_spend > 0 else 0
    overall_cvr = (total_purchases / total_clicks * 100) if total_clicks > 0 else 0
    overall_cpa = total_spend / total_purchases if total_purchases > 0 else None

    video_ads = [m for m in ads_metrics if m["is_video"]]
    static_ads = [m for m in ads_metrics if not m["is_video"]]
    hook_rates = [m["hook_rate"] for m in video_ads if m["hook_rate"] is not None]
    hold_rates = [m["hold_rate"] for m in video_ads if m["hold_rate"] is not None]
    avg_hook = sum(hook_rates) / len(hook_rates) if hook_rates else 0
    avg_hold = sum(hold_rates) / len(hold_rates) if hold_rates else 0

    # Evaluate all — sbira doporuceni s detaily
    evaluations = {}
    all_evals = []
    for m in ads_metrics:
        recs = ci.evaluate_creative(m)
        all_evals.append((m, recs))
        for action, _, _ in recs:
            evaluations[action] = evaluations.get(action, 0) + 1

    # Top performers — razeni podle weighted_roas (zohlednuje confidence)
    top_by_roas = sorted(
        [m for m in ads_metrics if m["roas"] and m["spend"] > 200],
        key=lambda x: x.get("weighted_roas", 0), reverse=True
    )[:7]

    # Urgent kills (highest spend = biggest waste)
    kills = []
    for m, recs in all_evals:
        for action, reason, detail in recs:
            if action == "KILL":
                kills.append((m, reason, detail))
                break
    urgent_kills = sorted(kills, key=lambda x: x[0]["spend"], reverse=True)[:7]

    # Iterate candidates — s konkretni diagnozou
    iterates = []
    for m, recs in all_evals:
        for action, reason, detail in recs:
            if action == "ITERATE":
                iterates.append((m, reason, detail))
                break
    iterates_top = sorted(iterates, key=lambda x: x[0]["spend"], reverse=True)[:7]

    # Portfolio health
    sorted_by_spend = sorted(ads_metrics, key=lambda x: x["spend"], reverse=True)
    top5_spend = sum(m["spend"] for m in sorted_by_spend[:5])
    ad_concentration = (top5_spend / total_spend * 100) if total_spend > 0 else 0

    # Format split — Video vs Static
    video_spend = sum(m["spend"] for m in video_ads)
    static_spend = sum(m["spend"] for m in static_ads)
    video_revenue = sum(m["revenue"] for m in video_ads)
    static_revenue = sum(m["revenue"] for m in static_ads)
    video_roas = video_revenue / video_spend if video_spend > 0 else 0
    static_roas = static_revenue / static_spend if static_spend > 0 else 0
    video_purchases = sum(m["purchases"] for m in video_ads)
    static_purchases = sum(m["purchases"] for m in static_ads)
    video_cpa = video_spend / video_purchases if video_purchases > 0 else None
    static_cpa = static_spend / static_purchases if static_purchases > 0 else None

    # Fatigue counts
    freq_high = len([m for m in ads_metrics if m["frequency"] > 3.0 and m["spend"] > 200])
    freq_extreme = len([m for m in ads_metrics if m["frequency"] > 5.0 and m["spend"] > 200])
    clickbait = len([m for m in ads_metrics if m["ctr"] > 2.0 and m.get("cvr") is not None and m["cvr"] < 0.5 and m["spend"] > 400])

    # Video drop-off diagnoza — souhrn
    dropoff_counts = {"SPATNY_HOOK": 0, "MIDDLE_SAG": 0, "POZDNI_CTA": 0, "ZDRAVY_FUNNEL": 0}
    for m in video_ads:
        d = m.get("video_dropoff")
        if d and d in dropoff_counts:
            dropoff_counts[d] += 1

    # Confidence coverage — kolik ads ma dostatek dat pro rozhodnuti
    high_conf = len([m for m in ads_metrics if m.get("confidence", 0) >= 0.7])
    mid_conf = len([m for m in ads_metrics if 0.3 <= m.get("confidence", 0) < 0.7])
    low_conf = len([m for m in ads_metrics if m.get("confidence", 0) < 0.3])

    # Waste estimation (spend na KILL kreativach)
    kill_waste = sum(m["spend"] for m, _, _ in kills)

    return {
        "meta_ads": {
            "total_ads": len(ads_metrics),
            "total_spend": round(total_spend, 0),
            "total_purchases": total_purchases,
            "total_revenue": round(total_revenue, 0),
            "overall_roas": round(overall_roas, 2),
            "overall_cvr": round(overall_cvr, 2),
            "overall_cpa": round(overall_cpa, 0) if overall_cpa else None,
            "avg_hook_rate": round(avg_hook, 1),
            "avg_hold_rate": round(avg_hold, 1),
            "video_ads_count": len(video_ads),
            "static_ads_count": len(static_ads),
            "ad_concentration_top5": round(ad_concentration, 1),
            "video_roas": round(video_roas, 2),
            "static_roas": round(static_roas, 2),
            "video_spend": round(video_spend, 0),
            "static_spend": round(static_spend, 0),
            "video_cpa": round(video_cpa, 0) if video_cpa else None,
            "static_cpa": round(static_cpa, 0) if static_cpa else None,
            "freq_high_count": freq_high,
            "freq_extreme_count": freq_extreme,
            "clickbait_count": clickbait,
            "kill_waste": round(kill_waste, 0),
        },
        "actions": {
            "kill_count": evaluations.get("KILL", 0),
            "scale_count": evaluations.get("SCALE", 0),
            "iterate_count": evaluations.get("ITERATE", 0),
            "watch_count": evaluations.get("WATCH", 0),
        },
        "video_dropoff": dropoff_counts,
        "confidence": {
            "high": high_conf,
            "mid": mid_conf,
            "low": low_conf,
        },
        "top_performers": [
            {
                "name": m["ad_name"][:50],
                "roas": m["roas"],
                "spend": m["spend"],
                "purchases": m["purchases"],
                "cvr": m.get("cvr"),
                "cpa": m.get("cpa"),
                "confidence": m.get("confidence_level", "?"),
                "is_video": m["is_video"],
                "hook_rate": m.get("hook_rate"),
            }
            for m in top_by_roas
        ],
        "urgent_kills": [
            {
                "name": m["ad_name"][:50],
                "spend": m["spend"],
                "roas": m["roas"],
                "reason": reason,
                "cpa": m.get("cpa"),
            }
            for m, reason, detail in urgent_kills
        ],
        "iterate_candidates": [
            {
                "name": m["ad_name"][:50],
                "spend": m["spend"],
                "roas": m["roas"],
                "reason": reason,
                "detail": detail,
                "is_video": m["is_video"],
                "hook_rate": m.get("hook_rate"),
                "hold_rate": m.get("hold_rate"),
                "cvr": m.get("cvr"),
                "ctr": m.get("ctr"),
            }
            for m, reason, detail in iterates_top
        ],
    }


def setup_threshold_rules(monitor):
    """Nastavi pravidla pro ThresholdMonitor (idempotentni)."""
    rules = [
        ("roas_critical", "meta_ads.overall_roas", "<", 1.5, "critical", "ROAS kriticky nizky (<1.5)"),
        ("roas_warning", "meta_ads.overall_roas", "<", 2.0, "warning", "ROAS pod targetem (<2.0)"),
        ("hook_low", "meta_ads.avg_hook_rate", "<", 20.0, "warning", "Prumerny hook rate pod 20% (benchmark >=25%)"),
        ("hook_critical", "meta_ads.avg_hook_rate", "<", 15.0, "critical", "Hook rate kriticky nizky (<15%)"),
        ("cvr_low", "meta_ads.overall_cvr", "<", 1.5, "warning", "CVR nizka (<1.5%, benchmark >2%)"),
        ("kill_surge", "actions.kill_count", ">", 80, "warning", "Vysoke mnozstvi KILL doporuceni (>80)"),
        ("concentration_high", "meta_ads.ad_concentration_top5", ">", 50, "warning", "Top 5 ads = >50% spendu — vysoke riziko"),
    ]
    for name, metric, op, threshold, severity, message in rules:
        try:
            monitor.add_rule(name, metric, op, threshold, severity, message)
        except Exception:
            pass  # Rule already exists or other issue


# ── Pumble message builder ──

def _trend_arrow(current, previous):
    """Vraci trend srovnani s sipkou."""
    if previous is None or previous == 0:
        return ""
    delta = current - previous
    pct = (delta / previous * 100)
    arrow = "+" if delta >= 0 else ""
    return f" ({arrow}{pct:.1f}% WoW)"


def _cpa_fmt(cpa):
    """Formatuje CPA."""
    if cpa is None:
        return "—"
    return f"{cpa:,.0f} CZK"


def build_pumble_message(snapshot, prev_snapshot, violations):
    """Sestavi tydenni Pumble report pro performance specialisty.

    Struktura zpravy:
    1. Klicove metriky + WoW trendy (ROAS, CPA, CVR, Hook/Hold)
    2. Format performance (Video vs Static)
    3. Alerty a threshold violations
    4. TOP kreativy ke skalovani (s confidence a CVR)
    5. KILL kreativy k zastaveni (s waste odhadem)
    6. ITERATE kreativy s konkretni diagnozou
    7. Video drop-off diagnoza
    8. Portfolio health
    9. Doporucene akce na dalsi tyden
    """
    s = snapshot["meta_ads"]
    a = snapshot["actions"]
    prev = prev_snapshot.get("meta_ads", {}) if prev_snapshot else {}
    lines = []

    # ── HEADER ──
    lines.append(f"**FERMATO Creative Intelligence — Tydenni Report {datetime.now().strftime('%Y-%m-%d')}**")
    lines.append("=" * 55)

    # ── 1. KLICOVE METRIKY ──
    lines.append("")
    lines.append("**KLICOVE METRIKY**")

    roas_trend = _trend_arrow(s["overall_roas"], prev.get("overall_roas"))
    cpa_trend = _trend_arrow(s.get("overall_cpa") or 0, prev.get("overall_cpa")) if s.get("overall_cpa") else ""
    cvr_trend = _trend_arrow(s["overall_cvr"], prev.get("overall_cvr"))

    lines.append(f"ROAS: **{s['overall_roas']}**{roas_trend} | CPA: **{_cpa_fmt(s.get('overall_cpa'))}**{cpa_trend}")
    lines.append(f"CVR: **{s['overall_cvr']}%**{cvr_trend} | Spend: {s['total_spend']:,.0f} CZK | Purchases: {s['total_purchases']}")
    lines.append(f"Hook Rate: **{s['avg_hook_rate']}%** (benchmark >=25%) | Hold Rate: **{s.get('avg_hold_rate', 0)}%** (benchmark >=40%)")

    # ── 2. FORMAT PERFORMANCE ──
    lines.append("")
    lines.append("**FORMAT PERFORMANCE (Video vs. Static)**")
    video_roas = s.get("video_roas", 0)
    static_roas = s.get("static_roas", 0)
    lines.append(f"Video: ROAS {video_roas} | {s.get('video_ads_count', 0)} ads | spend {s.get('video_spend', 0):,.0f} CZK | CPA {_cpa_fmt(s.get('video_cpa'))}")
    lines.append(f"Static: ROAS {static_roas} | {s.get('static_ads_count', 0)} ads | spend {s.get('static_spend', 0):,.0f} CZK | CPA {_cpa_fmt(s.get('static_cpa'))}")
    if video_roas > 0 and static_roas > 0:
        if static_roas > video_roas:
            diff_pct = ((static_roas - video_roas) / video_roas * 100)
            lines.append(f"-> Static outperformuje video o {diff_pct:.0f}% na ROAS (pouzit pro BOF/konverze)")
        elif video_roas > static_roas:
            diff_pct = ((video_roas - static_roas) / static_roas * 100)
            lines.append(f"-> Video outperformuje static o {diff_pct:.0f}% na ROAS")

    # ── 3. ALERTY ──
    alerts = []
    if violations:
        for v in violations:
            emoji = "!!!" if v.get("severity") == "critical" else "!"
            alerts.append(f"{emoji} {v.get('message', v.get('rule', ''))}: {v.get('metric', '')} = {v.get('value', '')}")
    if s.get("freq_extreme_count", 0) > 0:
        alerts.append(f"!!! {s['freq_extreme_count']} ads s freq >5.0 — extremni fatigue, OKAMZITE pausnout")
    if s.get("freq_high_count", 0) > 0:
        alerts.append(f"! {s['freq_high_count']} ads s freq >3.0 — pripravit refresh kreativ")
    if s.get("clickbait_count", 0) > 0:
        alerts.append(f"! {s['clickbait_count']} clickbait kreativ (CTR >2%, CVR <0.5%) — zmen sdeleni nebo LP")
    if s.get("ad_concentration_top5", 0) > 50:
        alerts.append(f"! Top 5 ads = {s['ad_concentration_top5']}% spendu — vysoke riziko zavislosti")
    if s.get("overall_cpa") and s["overall_cpa"] > 300:
        alerts.append(f"! CPA {s['overall_cpa']:,.0f} CZK nad benchmarkem (target <250 CZK)")

    if alerts:
        lines.append("")
        lines.append("**ALERTY**")
        for al in alerts:
            lines.append(al)

    # ── 4. TOP SCALE ──
    top = snapshot.get("top_performers", [])[:5]
    if top:
        lines.append("")
        lines.append("**TOP KREATIVY — SKALOVAT**")
        for i, t in enumerate(top, 1):
            typ = "V" if t.get("is_video") else "S"
            cvr_str = f" | CVR {t['cvr']}%" if t.get("cvr") else ""
            hook_str = f" | Hook {t['hook_rate']}%" if t.get("hook_rate") else ""
            conf = t.get("confidence", "?")
            lines.append(f"  {i}. [{typ}] {t['name']} | ROAS {t['roas']} | {t['purchases']} purch | CPA {_cpa_fmt(t.get('cpa'))}{cvr_str}{hook_str} | conf: {conf}")

    # ── 5. KILL ──
    urgent = snapshot.get("urgent_kills", [])[:5]
    if urgent:
        waste_total = s.get("kill_waste", 0)
        lines.append("")
        lines.append(f"**KILL — ZASTAVIT** (celkovy waste: ~{waste_total:,.0f} CZK)")
        for i, k in enumerate(urgent, 1):
            lines.append(f"  {i}. {k['name']} | spend {k['spend']:,.0f} CZK | ROAS {k['roas']} | {k['reason']}")

    # ── 6. ITERATE ──
    iterate_list = snapshot.get("iterate_candidates", [])[:5]
    if iterate_list:
        lines.append("")
        lines.append("**ITERATE — UPRAVIT (konkretni diagnoza)**")
        for i, it in enumerate(iterate_list, 1):
            typ = "V" if it.get("is_video") else "S"
            diag_parts = [it["reason"]]
            if it.get("is_video"):
                if it.get("hook_rate") is not None:
                    diag_parts.append(f"Hook {it['hook_rate']}%")
                if it.get("hold_rate") is not None:
                    diag_parts.append(f"Hold {it['hold_rate']}%")
            else:
                if it.get("ctr") is not None:
                    diag_parts.append(f"CTR {it['ctr']}%")
                if it.get("cvr") is not None:
                    diag_parts.append(f"CVR {it['cvr']}%")
            lines.append(f"  {i}. [{typ}] {it['name']} | ROAS {it['roas']} | {' | '.join(diag_parts)}")

    # ── 7. VIDEO DIAGNOZA ──
    vd = snapshot.get("video_dropoff", {})
    if any(v > 0 for v in vd.values()):
        lines.append("")
        lines.append("**VIDEO DROP-OFF DIAGNOZA**")
        parts = []
        if vd.get("SPATNY_HOOK", 0) > 0:
            parts.append(f"Spatny hook: {vd['SPATNY_HOOK']} (zmen 1. frame/text)")
        if vd.get("MIDDLE_SAG", 0) > 0:
            parts.append(f"Propad uprostred: {vd['MIDDLE_SAG']} (zkrat/preradesuj)")
        if vd.get("POZDNI_CTA", 0) > 0:
            parts.append(f"Pozdni CTA: {vd['POZDNI_CTA']} (presun CTA drive)")
        if vd.get("ZDRAVY_FUNNEL", 0) > 0:
            parts.append(f"Zdravy funnel: {vd['ZDRAVY_FUNNEL']}")
        lines.append("  " + " | ".join(parts))

    # ── 8. PORTFOLIO HEALTH ──
    lines.append("")
    lines.append("**PORTFOLIO HEALTH**")
    conc = s.get("ad_concentration_top5", 0)
    conc_status = "OK" if conc < 40 else ("!! Vysoke riziko" if conc > 50 else "! Sledovat")
    lines.append(f"  Ad concentration (top 5): {conc}% — {conc_status}")
    lines.append(f"  Fatigue risk: {s.get('freq_high_count', 0)} ads freq >3.0 | {s.get('freq_extreme_count', 0)} ads freq >5.0")
    conf = snapshot.get("confidence", {})
    total_ads = s.get("total_ads", 1)
    conf_pct = round(conf.get("high", 0) / total_ads * 100) if total_ads > 0 else 0
    lines.append(f"  Data confidence: {conf.get('high', 0)} vysoka / {conf.get('mid', 0)} stredni / {conf.get('low', 0)} nizka ({conf_pct}% ads s dostatkem dat)")
    lines.append(f"  Akce: KILL {a['kill_count']} | SCALE {a['scale_count']} | ITERATE {a['iterate_count']} | WATCH {a['watch_count']}")

    # ── 9. DOPORUCENE AKCE ──
    lines.append("")
    lines.append("**DOPORUCENE AKCE NA TENTO TYDEN**")
    action_num = 1
    if urgent:
        waste = s.get("kill_waste", 0)
        lines.append(f"  {action_num}. Zastavit {len(urgent)} KILL kreativ (uspora ~{waste:,.0f} CZK/tyden)")
        action_num += 1
    if top:
        best = top[0]
        lines.append(f"  {action_num}. Zvysit budget na top performer: {best['name']} (ROAS {best['roas']})")
        action_num += 1
    if s.get("freq_high_count", 0) > 2:
        lines.append(f"  {action_num}. Pripravit refresh pro {s['freq_high_count']} fatigued kreativ (freq >3.0)")
        action_num += 1
    if iterate_list:
        video_iterates = [it for it in iterate_list if it.get("is_video")]
        static_iterates = [it for it in iterate_list if not it.get("is_video")]
        if video_iterates:
            lines.append(f"  {action_num}. Video: opravit hook/hold u {len(video_iterates)} videi (viz diagnoza vyse)")
            action_num += 1
        if static_iterates:
            lines.append(f"  {action_num}. Bannery: upravit {len(static_iterates)} kreativ (CTR/CVR disconnect)")
            action_num += 1
    if s.get("clickbait_count", 0) > 0:
        lines.append(f"  {action_num}. Opravit {s['clickbait_count']} clickbait kreativ — zmen copy nebo landing page")
        action_num += 1

    # Footer
    lines.append("")
    lines.append(f"_Pozn: ROAS = Meta 7-day click atribuce (pro relativni srovnani, ne absolutni pravdu). Data za {s['total_ads']} ads._")

    return "\n".join(lines)


# ── Main ──

def main():
    # Parse args
    days = 7  # tydenni frekvence
    do_pumble = True
    do_vision = True
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--days" and i + 1 < len(args):
            days = int(args[i + 1])
            i += 2
        elif args[i] == "--no-pumble":
            do_pumble = False
            i += 1
        elif args[i] == "--no-vision":
            do_vision = False
            i += 1
        else:
            i += 1

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Creative Intelligence Weekly Runner", file=sys.stderr)
    print(f"  Days: {days} | Pumble: {do_pumble} | Vision: {do_vision}", file=sys.stderr)

    # ── Step 1: Run creative intelligence ──
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Stahuji Meta Ads data...", file=sys.stderr)
    try:
        raw_data = ci.fetch_ad_insights(days)
    except Exception as e:
        error_msg = f"Creative Intelligence FAILED: {e}"
        print(f"ERROR: {error_msg}", file=sys.stderr)
        if do_pumble:
            save_pumble_message(f"🔴 {error_msg}")
        sys.exit(1)

    ads_metrics = [ci.calculate_metrics(row) for row in raw_data]
    ads_metrics.sort(key=lambda x: x["spend"], reverse=True)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Stazeno {len(ads_metrics)} ads", file=sys.stderr)

    # Generate full report
    report = ci.generate_report(ads_metrics)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = OUTPUT_DIR / f"creative-intelligence-{datetime.now().strftime('%Y-%m-%d')}.txt"
    report_path.write_text(report, encoding="utf-8")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Report ulozen: {report_path}", file=sys.stderr)

    # ── Step 2: Snapshot ──
    snapshot_data = build_snapshot(ads_metrics)

    SnapshotManager, ThresholdMonitor = _load_cos_tools()
    prev_snapshot = None
    violations = []

    if SnapshotManager:
        db_path = str(REPO_ROOT / "data" / "snapshots.db")
        sm = SnapshotManager(db_path)

        # Get previous snapshot before creating new one
        try:
            diff = sm.compare_snapshots("creative_weekly")
            if diff and "previous" in diff:
                prev_snapshot = diff["previous"]
        except Exception:
            pass

        sm.create_snapshot("creative_weekly", snapshot_data)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Snapshot ulozen", file=sys.stderr)

    # ── Step 3: Threshold check ──
    if ThresholdMonitor:
        db_path = str(REPO_ROOT / "data" / "thresholds.db")
        mon = ThresholdMonitor(db_path)
        setup_threshold_rules(mon)
        violations = mon.check(snapshot_data)
        if violations:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ThresholdMonitor: {len(violations)} violations", file=sys.stderr)
            for v in violations:
                sev = v.get("severity", "info")
                print(f"  [{sev.upper()}] {v.get('message', '')}", file=sys.stderr)

    # ── Step 4: Pumble notification ──
    if do_pumble:
        msg = build_pumble_message(snapshot_data, prev_snapshot, violations)
        success = send_pumble(msg)
        status = "odeslana" if success else "ulozena do souboru (fallback)"
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Pumble notifikace: {status}", file=sys.stderr)

    # ── Step 5: Vision analysis (optional) ──
    if do_vision:
        try:
            import creative_vision as cv
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if api_key:
                # Analyzuj videa i staticke oddelene aby oba typy dostaly prostor
                video_metrics = [m for m in ads_metrics if m["is_video"]]
                static_metrics = [m for m in ads_metrics if not m["is_video"]]

                if video_metrics:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] AI analyza: {len(video_metrics)} videi...", file=sys.stderr)
                    av = cv.run_daily_analysis(video_metrics, max_creatives=10)
                    print(f"[{datetime.now().strftime('%H:%M:%S')}]   Analyzovano {av} videi", file=sys.stderr)

                if static_metrics:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] AI analyza: {len(static_metrics)} banneru...", file=sys.stderr)
                    ab = cv.run_daily_analysis(static_metrics, max_creatives=10)
                    print(f"[{datetime.now().strftime('%H:%M:%S')}]   Analyzovano {ab} banneru", file=sys.stderr)
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ANTHROPIC_API_KEY neni nastaven — preskakuji AI analyzu", file=sys.stderr)
        except ImportError:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] creative_vision.py nenalezen — preskakuji AI analyzu", file=sys.stderr)
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] AI analyza selhala: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)

    # ── Step 6: Component decomposition (v3) ──
    try:
        import creative_decomposer as cd
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if api_key:
            video_metrics = [m for m in ads_metrics if m["is_video"] and m["spend"] > 200 and m["impressions"] > 1000]
            if video_metrics:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Component decompose: {len(video_metrics)} videi...", file=sys.stderr)
                ads_with_data = [(m["ad_id"], m) for m in video_metrics]
                cd.run_decomposition(ads_with_data, max_ads=5)

                # Generate recommendations
                conn = cd.get_db()
                combos = cd.recommend_combinations(conn, top_n=5)
                conn.close()
                if combos:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}]   {len(combos)} novych kombinaci doporuceno", file=sys.stderr)
        else:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ANTHROPIC_API_KEY neni nastaven — preskakuji decompose", file=sys.stderr)
    except ImportError:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] creative_decomposer.py nenalezen — preskakuji", file=sys.stderr)
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Component decompose selhalo: {e}", file=sys.stderr)

    # ── Summary ──
    s = snapshot_data["meta_ads"]
    a = snapshot_data["actions"]
    print(f"\n{'='*50}", file=sys.stderr)
    print(f"  ROAS: {s['overall_roas']} | Spend: {s['total_spend']:,.0f} CZK | Purchases: {s['total_purchases']}", file=sys.stderr)
    print(f"  Hook rate: {s['avg_hook_rate']}% | Ads: {s['total_ads']}", file=sys.stderr)
    print(f"  KILL: {a['kill_count']} | SCALE: {a['scale_count']} | ITERATE: {a['iterate_count']}", file=sys.stderr)
    print(f"{'='*50}", file=sys.stderr)


if __name__ == "__main__":
    main()
