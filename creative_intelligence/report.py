"""Text report generation + CSV export."""

import csv
import io
from datetime import datetime

from .config import TARGET_ROAS, TARGET_CPA, MIN_SPEND_FOR_DECISION, MIN_IMPRESSIONS
from .rules import evaluate_creative


def generate_report(ads_metrics):
    """Generate full text report (v2)."""
    lines = []
    lines.append("=" * 70)
    lines.append("  FERMATO CREATIVE INTELLIGENCE REPORT v3")
    lines.append(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("=" * 70)

    total_spend = sum(m["spend"] for m in ads_metrics)
    total_purchases = sum(m["purchases"] for m in ads_metrics)
    total_revenue = sum(m["revenue"] for m in ads_metrics)
    total_clicks = sum(m["clicks"] for m in ads_metrics)
    overall_roas = total_revenue / total_spend if total_spend > 0 else 0
    overall_cvr = (total_purchases / total_clicks * 100) if total_clicks > 0 else 0
    video_ads = [m for m in ads_metrics if m["is_video"]]
    static_ads = [m for m in ads_metrics if not m["is_video"]]
    avg_hook = sum(m["hook_rate"] for m in video_ads if m["hook_rate"]) / max(len([m for m in video_ads if m["hook_rate"]]), 1)

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

    lines.append(f"\n  !! DATA RELIABILITY: ROAS je Meta 7-day click atribuce.")
    lines.append(f"    Skutecny inkrementalni dopad muze byt +/-30-70%.")

    evaluations = []
    for m in ads_metrics:
        recs = evaluate_creative(m)
        evaluations.append((m, recs))

    kills = [(m, r) for m, recs in evaluations for r in recs if r[0] == "KILL"]
    scales = [(m, r) for m, recs in evaluations for r in recs if r[0] == "SCALE"]
    iterates = [(m, r) for m, recs in evaluations for r in recs if r[0] == "ITERATE"]
    watches = [(m, r) for m, recs in evaluations for r in recs if r[0] == "WATCH"]

    lines.append(f"\n## Akce")
    lines.append(f"  KILL:    {len(kills)}")
    lines.append(f"  SCALE:   {len(scales)}")
    lines.append(f"  ITERATE: {len(iterates)}")
    lines.append(f"  WATCH:   {len(watches)}")

    for section_name, section_data, sort_key in [
        ("KILL — ZASTAVIT", kills, lambda x: x[0]["spend"]),
        ("SCALE — SKALOVAT", scales, lambda x: x[0].get("roas") or 0),
    ]:
        if section_data:
            lines.append(f"\n{'='*70}")
            lines.append(f"  {section_name}")
            lines.append(f"{'='*70}")
            for m, (action, reason, detail) in sorted(section_data, key=sort_key, reverse=True):
                lines.append(f"\n  [{m['ad_id']}] {m['ad_name'][:50]}")
                lines.append(f"    Kampan: {m['campaign_name']}")
                cvr_str = f" | CVR: {m['cvr']}%" if m.get('cvr') else ""
                lines.append(f"    Spend: {m['spend']} CZK | ROAS: {m['roas']} | CPA: {m['cpa']} CZK{cvr_str}")
                if m["is_video"]:
                    lines.append(f"    Hook: {m['hook_rate']}% | Hold: {m['hold_rate']}%")
                lines.append(f"    >> {reason}: {detail}")

    if iterates:
        lines.append(f"\n{'='*70}")
        lines.append(f"  ITERATE — UPRAVIT KREATIVU")
        lines.append(f"{'='*70}")
        for m, (action, reason, detail) in iterates:
            lines.append(f"\n  [{m['ad_id']}] {m['ad_name'][:50]}")
            lines.append(f"    Spend: {m['spend']} CZK | ROAS: {m['roas']} | CTR: {m['ctr']}%")
            if m["is_video"]:
                lines.append(f"    Hook: {m['hook_rate']}% | Hold: {m['hold_rate']}%")
            lines.append(f"    >> {reason}: {detail}")

    # Top performers
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

    # Benchmarks
    lines.append(f"\n{'='*70}")
    lines.append(f"  BENCHMARKY v2 (research-backed)")
    lines.append(f"{'='*70}")
    lines.append(f"  Video:  Hook >=25% standard, >=30% dobre, >=35% elite")
    lines.append(f"          Hold >=40% standard, >=50% dobre, >=60% elite")
    lines.append(f"  Static: CTR >=1.0% minimum, >=1.5% dobre, >=2.0% elite")
    lines.append(f"  Oba:    CVR >=2.0% dobre, >=3.0% vyborne (food&bev)")
    lines.append(f"  Target: ROAS {TARGET_ROAS} | CPA {TARGET_CPA} CZK")
    lines.append(f"{'='*70}")

    return "\n".join(lines)


def export_csv(ads_metrics):
    """Export to CSV string."""
    output = io.StringIO()
    if not ads_metrics:
        return ""
    writer = csv.DictWriter(output, fieldnames=ads_metrics[0].keys())
    writer.writeheader()
    writer.writerows(ads_metrics)
    return output.getvalue()
