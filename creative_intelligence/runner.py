"""Weekly runner — orchestrator for automated pipeline.

Steps:
1. Fetch Meta Ads data + calculate metrics
2. Run rule engine (KILL/SCALE/ITERATE)
3. Generate text report
4. v3: Decompose top creatives + build component library
5. v3: Generate combinatorial recommendations
6. Send Pumble notification
"""

import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

from . import metrics as m
from . import rules
from . import report
from .pumble import send_pumble
from .config import REPO_ROOT, DATA_DIR, TARGET_ROAS, TARGET_CPA


OUTPUT_DIR = DATA_DIR


def main(days=7, do_pumble=True, do_vision=True, do_decompose=True, do_recommend=True):
    """Run full weekly pipeline."""
    print(f"[{_ts()}] Creative Intelligence v3 Runner", file=sys.stderr)
    print(f"  Days: {days} | Pumble: {do_pumble} | Vision: {do_vision} | Decompose: {do_decompose}", file=sys.stderr)

    # ── Step 1: Fetch & calculate ──
    print(f"[{_ts()}] Stahuji Meta Ads data...", file=sys.stderr)
    try:
        raw_data = m.fetch_ad_insights(days)
    except Exception as e:
        error_msg = f"Creative Intelligence FAILED: {e}"
        print(f"ERROR: {error_msg}", file=sys.stderr)
        if do_pumble:
            send_pumble(f"!!! {error_msg}")
        return

    ads_metrics = [m.calculate_metrics(row) for row in raw_data]
    ads_metrics.sort(key=lambda x: x["spend"], reverse=True)
    print(f"[{_ts()}] Stazeno {len(ads_metrics)} ads", file=sys.stderr)

    # ── Step 2: Generate report ──
    full_report = report.generate_report(ads_metrics)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = OUTPUT_DIR / f"creative-intelligence-{datetime.now().strftime('%Y-%m-%d')}.txt"
    report_path.write_text(full_report, encoding="utf-8")
    print(f"[{_ts()}] Report ulozen: {report_path}", file=sys.stderr)

    # ── Step 3: v3 Decomposition ──
    if do_decompose:
        try:
            from .decomposition import download_and_decompose
            from .component_db import get_db, build_library_from_analysis, print_library_summary

            conn = get_db()
            # Decompose top video ads (by spend, video only)
            video_ads = [ad for ad in ads_metrics if ad["is_video"] and ad["spend"] > 300][:15]

            decomposed = 0
            for ad in video_ads:
                video_id = _get_video_id_for_ad(ad["ad_id"])
                if not video_id:
                    continue

                print(f"[{_ts()}] Decomposing: {ad['ad_name'][:40]}...", file=sys.stderr)
                try:
                    result = download_and_decompose(
                        ad["ad_id"], video_id,
                        performance={
                            "hook_rate": ad["hook_rate"],
                            "hold_rate": ad["hold_rate"],
                            "completion_rate": ad["completion_rate"],
                            "roas": ad["roas"],
                            "cpa": ad["cpa"],
                            "cvr": ad.get("cvr"),
                            "spend": ad["spend"],
                            "purchases": ad["purchases"],
                            "impressions": ad["impressions"],
                            "ad_name": ad["ad_name"],
                            "campaign_name": ad["campaign_name"],
                        }
                    )
                    if result:
                        build_library_from_analysis(conn, ad["ad_id"], result, ad)
                        decomposed += 1
                        print(f"  OK (cost: ${result.get('total_cost', 0):.4f})", file=sys.stderr)
                except Exception as e:
                    print(f"  ERROR: {e}", file=sys.stderr)

            print(f"[{_ts()}] Decomposed: {decomposed} videi", file=sys.stderr)
            print_library_summary(conn)

            # ── Step 4: v3 Recommendations ──
            if do_recommend:
                from .combinator import generate_all_recommendations, format_recommendations_report

                results = generate_all_recommendations(conn, min_spend=200)
                rec_report = format_recommendations_report(results)

                rec_path = OUTPUT_DIR / f"recommendations-{datetime.now().strftime('%Y-%m-%d')}.txt"
                rec_path.write_text(rec_report, encoding="utf-8")
                print(f"[{_ts()}] Recommendations ulozen: {rec_path}", file=sys.stderr)

            conn.close()

        except Exception as e:
            print(f"[{_ts()}] Decomposition/Recommend failed: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)

    # ── Step 5: Pumble ──
    if do_pumble:
        msg = _build_pumble_summary(ads_metrics)
        success = send_pumble(msg)
        status = "odeslana" if success else "ulozena (fallback)"
        print(f"[{_ts()}] Pumble: {status}", file=sys.stderr)

    # Summary
    total_spend = sum(ad["spend"] for ad in ads_metrics)
    total_purchases = sum(ad["purchases"] for ad in ads_metrics)
    total_revenue = sum(ad["revenue"] for ad in ads_metrics)
    overall_roas = total_revenue / total_spend if total_spend > 0 else 0

    print(f"\n{'='*50}", file=sys.stderr)
    print(f"  ROAS: {overall_roas:.2f} | Spend: {total_spend:,.0f} CZK | Purchases: {total_purchases}", file=sys.stderr)
    print(f"  Ads: {len(ads_metrics)}", file=sys.stderr)
    print(f"{'='*50}", file=sys.stderr)


def _get_video_id_for_ad(ad_id):
    """Fetch video_id for an ad from Meta API."""
    try:
        from .meta_client import meta_fetch
        data = meta_fetch(ad_id, {"fields": "creative{video_id}"})
        return data.get("creative", {}).get("video_id")
    except Exception:
        return None


def _build_pumble_summary(ads_metrics):
    """Build compact Pumble message."""
    total_spend = sum(ad["spend"] for ad in ads_metrics)
    total_purchases = sum(ad["purchases"] for ad in ads_metrics)
    total_revenue = sum(ad["revenue"] for ad in ads_metrics)
    overall_roas = total_revenue / total_spend if total_spend > 0 else 0

    video_ads = [ad for ad in ads_metrics if ad["is_video"]]
    hook_rates = [ad["hook_rate"] for ad in video_ads if ad["hook_rate"]]
    avg_hook = sum(hook_rates) / len(hook_rates) if hook_rates else 0

    # Count actions
    actions = {"KILL": 0, "SCALE": 0, "ITERATE": 0, "WATCH": 0}
    for ad in ads_metrics:
        recs = rules.evaluate_creative(ad)
        for action, _, _ in recs:
            if action in actions:
                actions[action] += 1

    lines = [
        f"**FERMATO Creative Intelligence v3 — {datetime.now().strftime('%Y-%m-%d')}**",
        f"ROAS: **{overall_roas:.2f}** | Spend: {total_spend:,.0f} CZK | Purchases: {total_purchases}",
        f"Hook Rate: **{avg_hook:.1f}%** | Ads: {len(ads_metrics)}",
        f"KILL: {actions['KILL']} | SCALE: {actions['SCALE']} | ITERATE: {actions['ITERATE']} | WATCH: {actions['WATCH']}",
    ]

    # Top 3 performers
    top = sorted([ad for ad in ads_metrics if ad["roas"] and ad["spend"] > 200],
                 key=lambda x: x.get("weighted_roas", 0), reverse=True)[:3]
    if top:
        lines.append("\n**TOP:**")
        for t in top:
            lines.append(f"  {t['ad_name'][:35]} | ROAS {t['roas']} | {t['purchases']} purch")

    return "\n".join(lines)


def _ts():
    return datetime.now().strftime('%H:%M:%S')
